"""
Week 15 Day 105: run_eval.py — AI 研究助手 QA 自动化评测主编排入口

拼装：Golden Dataset → Agent(live|mock) → EvalTrace →
Tool F1 / Faithfulness / Relevance / G-Eval → EvalRunReport →
ThresholdGate → EvalReporter。
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable, Literal

ProgressCallback = Callable[[str, dict], Awaitable[None] | None]

logger = logging.getLogger("day105.run_eval")

# ── 路径注入 ──────────────────────────────────────────────────────────────
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, "../.."))
W04_PATH = os.path.abspath(os.path.join(CURRENT_DIR, "../w04_prompt_and_http"))
W15_ROOT = CURRENT_DIR
EVALUATORS_DIR = os.path.join(W15_ROOT, "evaluators")
GATE_DIR = os.path.join(W15_ROOT, "gate")
REPORTER_DIR = os.path.join(W15_ROOT, "reporter")

for p in (REPO_ROOT, W04_PATH, W15_ROOT, EVALUATORS_DIR, GATE_DIR, REPORTER_DIR):
    if p not in sys.path:
        sys.path.append(p)

from contracts.schemas import (  # noqa: E402
    CaseEvalResult,
    EvalRunReport,
    EvalTrace,
    GoldenCase,
    load_golden_dataset,
)
from agent_runner.mock_runner import (  # noqa: E402
    DEFAULT_FAIL_CASE_IDS,
    MockTraceRunner,
)
from tool_execution_impl import ToolExecutionEvaluator  # noqa: E402
from threshold_gate_impl import ThresholdGate  # noqa: E402
from eval_reporter_impl import EvalReporter  # noqa: E402

MetricsMode = Literal["gate", "full", "tool"]
AgentMode = Literal["live", "mock"]
Scenario = Literal["default", "demo_fail"]

DEFAULT_DATASET = Path(W15_ROOT) / "day105" / "golden_dataset.jsonl"
DEFAULT_OUT = Path(W15_ROOT) / "reports" / "eval_result.json"
DEFAULT_DIFF = Path(W15_ROOT) / "reports" / "regression_diff.md"
DEFAULT_BASELINE = Path(W15_ROOT) / "reports" / "eval_baseline.json"

TOOL_F1_PASS = 0.85
FAITH_PASS = 0.90


def _git_sha() -> str | None:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return out.strip() or None
    except Exception:  # noqa: BLE001
        return None


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 4)


def _offline_faithfulness(trace: EvalTrace) -> float:
    """无 LLM 时的启发式 Faithfulness：幻觉关键词 → 0；否则看 answer 是否贴近 context。"""
    answer = (trace.final_answer or "").lower()
    if "quantum attention" in answer or "0.99" in answer or "0.999" in answer:
        return 0.05
    if not trace.retrieved_contexts:
        return 0.0
    blob = " ".join(trace.retrieved_contexts)
    # ground_truth 被拆入 contexts 的完美 mock：answer 应几乎全在 blob 中
    overlap = sum(1 for ch in answer[:200] if ch in blob.lower())
    ratio = overlap / max(len(answer[:200]), 1)
    return round(min(1.0, max(0.0, ratio)), 4)


def _offline_relevance(case: GoldenCase, trace: EvalTrace) -> float:
    q_tokens = set(case.query.lower().split())
    a_tokens = set((trace.final_answer or "").lower().split())
    if not q_tokens:
        return 0.0
    inter = len(q_tokens & a_tokens)
    return round(min(1.0, inter / max(len(q_tokens) * 0.3, 1)), 4)


class EvalPipeline:
    """并发评测编排器。"""

    def __init__(
        self,
        *,
        agent_mode: AgentMode = "mock",
        scenario: Scenario = "default",
        metrics: MetricsMode = "gate",
        concurrency: int = 4,
        offline: bool = False,
        geval_samples: int = 1,
        fail_case_ids: tuple[str, ...] | list[str] | None = None,
        on_event: ProgressCallback | None = None,
    ):
        self.agent_mode = agent_mode
        self.scenario = scenario
        self.metrics = metrics
        self.concurrency = max(1, concurrency)
        self.offline = offline
        self.geval_samples = max(1, geval_samples)
        self.fail_case_ids = list(fail_case_ids or DEFAULT_FAIL_CASE_IDS)
        self.on_event = on_event

        self.tool_eval = ToolExecutionEvaluator()
        self.gate = ThresholdGate()
        self.reporter = EvalReporter()

        self._faith = None
        self._rel = None
        self._geval = None
        if not offline and metrics in ("gate", "full"):
            from faithfulness_impl import FaithfulnessEvaluator

            self._faith = FaithfulnessEvaluator(temperature=0.1)
            if metrics == "full":
                from relevance_impl import RelevanceEvaluator
                from g_eval_judge_impl import GEvalJudge

                self._rel = RelevanceEvaluator(temperature=0.1)
                self._geval = GEvalJudge(sample_count=self.geval_samples, temperature=0.2)

    async def _emit(self, event_type: str, data: dict) -> None:
        # CLI / 服务端双重可见
        tid = data.get("test_case_id", "")
        msg = data.get("message") or data.get("metric") or ""
        logger.info("%s %s %s", event_type, tid, msg)
        print(f"[eval] {event_type} {tid} {msg}".strip(), flush=True)
        if self.on_event is None:
            return
        result = self.on_event(event_type, data)
        if asyncio.iscoroutine(result) or isinstance(result, Awaitable):
            await result  # type: ignore[arg-type]

    async def collect_traces(self, cases: list[GoldenCase]) -> list[EvalTrace]:
        """并发收集 EvalTrace。"""
        sem = asyncio.Semaphore(self.concurrency)
        total = len(cases)

        if self.agent_mode == "mock":
            runner = MockTraceRunner(
                scenario=self.scenario,
                fail_case_ids=self.fail_case_ids,
            )

            async def _one(idx: int, case: GoldenCase) -> EvalTrace:
                async with sem:
                    await self._emit(
                        "trace_start",
                        {
                            "test_case_id": case.test_case_id,
                            "index": idx,
                            "total": total,
                            "agent": "mock",
                        },
                    )
                    trace = await asyncio.to_thread(runner.build_trace, case)
                    await self._emit(
                        "trace_done",
                        {
                            "test_case_id": case.test_case_id,
                            "index": idx,
                            "total": total,
                            "tool_count": len(trace.tool_calls),
                        },
                    )
                    return trace

            return list(
                await asyncio.gather(
                    *[_one(i + 1, c) for i, c in enumerate(cases)]
                )
            )

        from agent_runner.research_adapter import ResearchAgentTraceAdapter

        adapter = ResearchAgentTraceAdapter()

        async def _live(idx: int, case: GoldenCase) -> EvalTrace:
            async with sem:
                await self._emit(
                    "trace_start",
                    {
                        "test_case_id": case.test_case_id,
                        "index": idx,
                        "total": total,
                        "agent": "live",
                        "query": case.query[:80],
                    },
                )
                trace = await adapter.run_case(case)
                await self._emit(
                    "trace_done",
                    {
                        "test_case_id": case.test_case_id,
                        "index": idx,
                        "total": total,
                        "tool_count": len(trace.tool_calls),
                        "answer_preview": (trace.final_answer or "")[:120],
                        "errors": list(trace.errors),
                    },
                )
                return trace

        return list(
            await asyncio.gather(*[_live(i + 1, c) for i, c in enumerate(cases)])
        )

    async def evaluate_case(
        self,
        case: GoldenCase,
        trace: EvalTrace,
    ) -> CaseEvalResult:
        """对单 Case 执行选定指标评测。"""
        failure_reasons: list[str] = []

        # 1) Tool F1（确定性）
        tool_result = self.tool_eval.evaluate(case.expected_tools, trace)
        tool_f1 = tool_result.f1
        tool_precision = tool_result.precision
        tool_recall = tool_result.recall
        param_accuracy = tool_result.param_accuracy
        if tool_f1 < TOOL_F1_PASS:
            failure_reasons.append(
                f"tool_f1={tool_f1:.4f}<{TOOL_F1_PASS}"
            )
            if tool_result.unmatched_expected:
                failure_reasons.append(
                    "missing_tools=" + ",".join(tool_result.unmatched_expected)
                )

        faithfulness: float | None = None
        relevance: float | None = None
        professionalism: float | None = None

        if self.metrics == "tool":
            faithfulness = 1.0  # 不参与硬门禁时占位；Gate 仍可读
        elif self.offline:
            faithfulness = _offline_faithfulness(trace)
            if self.metrics == "full":
                relevance = _offline_relevance(case, trace)
                professionalism = 0.8 if faithfulness >= 0.8 else 0.3
        else:
            assert self._faith is not None
            await self._emit(
                "llm_call",
                {
                    "metric": "faithfulness",
                    "test_case_id": case.test_case_id,
                    "message": "调用真实 LLM Judge: Faithfulness",
                },
            )
            faith_res = await self._faith.evaluate(
                test_case_id=case.test_case_id,
                answer=trace.final_answer,
                contexts=trace.retrieved_contexts,
            )
            faithfulness = faith_res.score
            await self._emit(
                "llm_done",
                {
                    "metric": "faithfulness",
                    "test_case_id": case.test_case_id,
                    "score": faithfulness,
                },
            )

            if self.metrics == "full":
                assert self._rel is not None and self._geval is not None
                await self._emit(
                    "llm_call",
                    {
                        "metric": "relevance+g_eval",
                        "test_case_id": case.test_case_id,
                        "message": "调用真实 LLM Judge: Relevance + G-Eval",
                    },
                )
                rel_res, gev_res = await asyncio.gather(
                    self._rel.evaluate(
                        test_case_id=case.test_case_id,
                        query=case.query,
                        answer=trace.final_answer,
                    ),
                    self._geval.evaluate_professionalism(
                        query=case.query,
                        answer=trace.final_answer,
                    ),
                )
                relevance = rel_res.score
                professionalism = gev_res.weighted_mean
                await self._emit(
                    "llm_done",
                    {
                        "metric": "relevance+g_eval",
                        "test_case_id": case.test_case_id,
                        "score": relevance,
                        "professionalism": professionalism,
                    },
                )

        if faithfulness is not None and faithfulness < FAITH_PASS:
            failure_reasons.append(
                f"faithfulness={faithfulness:.4f}<{FAITH_PASS}"
            )

        passed = tool_f1 >= TOOL_F1_PASS and (
            faithfulness is None or faithfulness >= FAITH_PASS
        )

        return CaseEvalResult(
            test_case_id=case.test_case_id,
            passed=passed,
            tool_precision=tool_precision,
            tool_recall=tool_recall,
            tool_f1=tool_f1,
            param_accuracy=param_accuracy,
            faithfulness=faithfulness,
            relevance=relevance,
            professionalism=professionalism,
            failure_reasons=failure_reasons,
        )

    async def run(
        self,
        cases: list[GoldenCase],
        *,
        run_id: str | None = None,
        dataset_path: str = "",
    ) -> EvalRunReport:
        started = datetime.now(timezone.utc).isoformat()
        print(f"📦 Cases: {len(cases)} | agent={self.agent_mode} | "
              f"metrics={self.metrics} | offline={self.offline} | "
              f"scenario={self.scenario}")

        await self._emit(
            "status",
            {
                "phase": "tracing",
                "message": f"收集 Trace（agent={self.agent_mode}, cases={len(cases)}）",
                "offline": self.offline,
                "metrics": self.metrics,
            },
        )
        traces = await self.collect_traces(cases)
        by_id = {t.test_case_id: t for t in traces}

        await self._emit(
            "status",
            {
                "phase": "scoring",
                "message": (
                    "LLM Judge 打分中…"
                    if not self.offline
                    else "离线启发式打分中…"
                ),
            },
        )

        sem = asyncio.Semaphore(self.concurrency)
        total = len(cases)

        async def _eval(idx: int, case: GoldenCase) -> CaseEvalResult:
            async with sem:
                await self._emit(
                    "case_start",
                    {
                        "test_case_id": case.test_case_id,
                        "index": idx,
                        "total": total,
                    },
                )
                trace = by_id[case.test_case_id]
                result = await self.evaluate_case(case, trace)
                status = "PASS" if result.passed else "FAIL"
                print(
                    f"   [{status}] {case.test_case_id}  "
                    f"f1={result.tool_f1:.3f}  "
                    f"faith={result.faithfulness if result.faithfulness is not None else '-'}"
                )
                await self._emit(
                    "case_done",
                    {
                        "test_case_id": result.test_case_id,
                        "index": idx,
                        "total": total,
                        "passed": result.passed,
                        "tool_f1": result.tool_f1,
                        "faithfulness": result.faithfulness,
                        "relevance": result.relevance,
                        "professionalism": result.professionalism,
                        "failure_reasons": list(result.failure_reasons),
                    },
                )
                return result

        case_results = list(
            await asyncio.gather(*[_eval(i + 1, c) for i, c in enumerate(cases)])
        )

        aggregate: dict[str, float] = {
            "tool_f1": _mean([c.tool_f1 or 0.0 for c in case_results]),
            "tool_precision": _mean([c.tool_precision or 0.0 for c in case_results]),
            "tool_recall": _mean([c.tool_recall or 0.0 for c in case_results]),
            "param_accuracy": _mean([c.param_accuracy or 0.0 for c in case_results]),
            "pass_rate": _mean([1.0 if c.passed else 0.0 for c in case_results]),
        }
        faith_vals = [c.faithfulness for c in case_results if c.faithfulness is not None]
        if faith_vals:
            aggregate["faithfulness"] = _mean(faith_vals)
        rel_vals = [c.relevance for c in case_results if c.relevance is not None]
        if rel_vals:
            aggregate["relevance"] = _mean(rel_vals)
        prof_vals = [
            c.professionalism for c in case_results if c.professionalism is not None
        ]
        if prof_vals:
            aggregate["professionalism"] = _mean(prof_vals)

        report = EvalRunReport(
            run_id=run_id
            or f"day105-{self.agent_mode}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
            git_sha=_git_sha(),
            judge_model=os.getenv("MINIMAX_MODEL") or ("offline" if self.offline else None),
            dataset_version="v1",
            dataset_path=dataset_path,
            started_at=started,
            finished_at=datetime.now(timezone.utc).isoformat(),
            aggregate=aggregate,
            thresholds=dict(ThresholdGate.DEFAULT_THRESHOLDS),
            cases=case_results,
        )
        return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Week 15 Day 105 Eval Pipeline")
    p.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    p.add_argument("--agent", choices=["live", "mock"], default="mock")
    p.add_argument("--limit", type=int, default=0, help="0 = 全量")
    p.add_argument("--concurrency", type=int, default=4)
    p.add_argument("--baseline", type=Path, default=None)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p.add_argument("--diff-out", type=Path, default=DEFAULT_DIFF)
    p.add_argument("--enforce-gate", action="store_true")
    p.add_argument("--scenario", choices=["default", "demo_fail"], default="default")
    p.add_argument(
        "--metrics",
        choices=["gate", "full", "tool"],
        default="gate",
        help="gate=tool+faithfulness; full=+relevance+g-eval; tool=仅 Tool F1",
    )
    p.add_argument(
        "--offline",
        action="store_true",
        help="不调用 LLM Judge，用启发式分数（单元测试 / 无 Key 本地）",
    )
    p.add_argument("--geval-samples", type=int, default=1)
    p.add_argument(
        "--fail-case-id",
        action="append",
        dest="fail_case_ids",
        default=None,
        help="可重复指定；默认污染 research_002/005/008/011",
    )
    p.add_argument("--run-id", default=None)
    p.add_argument(
        "--save-as-baseline",
        action="store_true",
        help="将本次报告另存为 reports/eval_baseline.json",
    )
    return p.parse_args(argv)


async def async_main(args: argparse.Namespace) -> int:
    dataset_path = Path(args.dataset)
    if not dataset_path.exists():
        print(f"❌ Dataset not found: {dataset_path}")
        return 2

    cases = load_golden_dataset(dataset_path)
    if args.limit and args.limit > 0:
        cases = cases[: args.limit]

    pipeline = EvalPipeline(
        agent_mode=args.agent,
        scenario=args.scenario,
        metrics=args.metrics,
        concurrency=args.concurrency,
        offline=args.offline,
        geval_samples=args.geval_samples,
        fail_case_ids=args.fail_case_ids,
    )

    report = await pipeline.run(
        cases,
        run_id=args.run_id,
        dataset_path=str(dataset_path),
    )

    out_path = Path(args.out)
    report.save_json(out_path)
    print(f"\n💾 EvalRunReport → {out_path}")
    print(f"   aggregate: {report.aggregate}")

    if args.save_as_baseline:
        baseline_path = DEFAULT_BASELINE
        report.save_json(baseline_path)
        print(f"💾 baseline → {baseline_path}")

    baseline_path = Path(args.baseline) if args.baseline else None
    if baseline_path and baseline_path.exists():
        baseline = EvalRunReport.load_json(baseline_path)
        pipeline.reporter.compare_and_report(
            baseline,
            report,
            markdown_path=Path(args.diff_out),
        )
    elif args.baseline:
        print(f"⚠️  baseline 不存在，跳过 Diff: {args.baseline}")

    if args.enforce_gate:
        mode = "pr" if (args.limit and args.limit < 50) else "full"
        try:
            pipeline.gate.enforce(report, mode=mode)
        except SystemExit as exc:
            return int(exc.code) if isinstance(exc.code, int) else 1

    return 0


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    code = asyncio.run(async_main(args))
    raise SystemExit(code)


if __name__ == "__main__":
    main()
