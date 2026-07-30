"""
Week 15 Day 104 参考标准答案: EvalReporter 回归差异报告
(eval_reporter_impl.py)

===============================================================================
设计方案说明 (Architecture Design Specification)
===============================================================================

1. 设计意图 (Design Intent):
   ThresholdGate 只能回答「过不过」。排障需要知道相对上一版哪些指标掉了、
   哪些 test_case_id 从 PASS 变为 FAIL。本模块实现 EvalReporter：对两份
   EvalRunReport 做聚合 Δ 与 Case 级 Diff，渲染 Markdown 并终端输出。
   演示用的 baseline/current 必须由真实 Tool F1 + Faithfulness 评测生成。

2. 核心类与数据流结构 (Class & Data Flow):
   - EvalReporter.diff_aggregates / diff_cases / compare
   - EvalReporter.render_markdown / print_console / compare_and_report
   - RegressionDemoHarness: 真实评测生成 baseline（全过）与 current（含回归）
   - MetricDelta / CaseDelta / RegressionReport: contracts/schemas.py

3. 核心用例设计意图 (Test Case Design Intent):
   - research_001: 两侧均忠实+工具完整 → unchanged
   - research_002: baseline 正常；current 漏调+幻觉 → regressed
   验证：aggregate Δ 为负、regressed_ids 含 research_002、Markdown 可读
===============================================================================
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── 路径注入 ──────────────────────────────────────────────────────────────
current_dir = os.path.dirname(os.path.abspath(__file__))
repo_root = os.path.abspath(os.path.join(current_dir, "../../.."))
w04_path = os.path.abspath(os.path.join(current_dir, "../../w04_prompt_and_http"))
w15_root = os.path.abspath(os.path.join(current_dir, ".."))
evaluators_dir = os.path.join(w15_root, "evaluators")

for p in (repo_root, w04_path, w15_root, evaluators_dir):
    if p not in sys.path:
        sys.path.append(p)

from contracts.schemas import (
    CaseDelta,
    CaseEvalResult,
    EvalRunReport,
    EvalTrace,
    ExpectedToolCall,
    MetricDelta,
    RegressionReport,
    ToolCallRecord,
)
from tool_execution_impl import ToolExecutionEvaluator
from faithfulness_impl import FaithfulnessEvaluator


# ═══════════════════════════════════════════════════════════════════════════
# EvalReporter
# ═══════════════════════════════════════════════════════════════════════════

class EvalReporter:
    """
    回归差异报告微引擎：比对两次 EvalRunReport。

    Parameters
    ----------
    epsilon:
        |Δ| ≤ epsilon 视为 unchanged，默认 1e-4。
    """

    METRIC_KEYS = (
        "tool_f1",
        "faithfulness",
        "relevance",
        "professionalism",
        "tool_precision",
        "tool_recall",
        "param_accuracy",
    )

    CASE_METRIC_ATTRS = (
        "tool_f1",
        "faithfulness",
        "relevance",
        "professionalism",
        "tool_precision",
        "tool_recall",
        "param_accuracy",
    )

    def __init__(self, epsilon: float = 1e-4):
        self.epsilon = epsilon

    def _classify_delta(self, delta: float) -> str:
        if delta < -self.epsilon:
            return "regressed"
        if delta > self.epsilon:
            return "improved"
        return "unchanged"

    def diff_aggregates(
        self,
        baseline: EvalRunReport,
        current: EvalRunReport,
    ) -> list[MetricDelta]:
        """计算聚合指标 Δ 列表。"""
        keys = sorted(
            set(baseline.aggregate.keys())
            | set(current.aggregate.keys())
            | {k for k in self.METRIC_KEYS if k in baseline.aggregate or k in current.aggregate}
        )
        # 优先按 METRIC_KEYS 顺序输出已知指标
        ordered = [k for k in self.METRIC_KEYS if k in keys]
        ordered.extend(k for k in keys if k not in ordered)

        results: list[MetricDelta] = []
        for name in ordered:
            base_v = float(baseline.aggregate.get(name, 0.0))
            curr_v = float(current.aggregate.get(name, 0.0))
            # 两侧都缺失则跳过
            if name not in baseline.aggregate and name not in current.aggregate:
                continue
            delta = round(curr_v - base_v, 4)
            results.append(
                MetricDelta(
                    metric_name=name,
                    baseline=round(base_v, 4),
                    current=round(curr_v, 4),
                    delta=delta,
                    status=self._classify_delta(delta),  # type: ignore[arg-type]
                )
            )
        return results

    def _case_metric_deltas(
        self,
        base: CaseEvalResult | None,
        curr: CaseEvalResult | None,
    ) -> dict[str, float]:
        """提取 Case 级指标 Δ。"""
        deltas: dict[str, float] = {}
        for attr in self.CASE_METRIC_ATTRS:
            b = getattr(base, attr, None) if base else None
            c = getattr(curr, attr, None) if curr else None
            if b is None and c is None:
                continue
            deltas[attr] = round(float(c or 0.0) - float(b or 0.0), 4)
        return deltas

    def diff_cases(
        self,
        baseline: EvalRunReport,
        current: EvalRunReport,
    ) -> list[CaseDelta]:
        """按 test_case_id 对齐并判定回归状态。"""
        base_map = {c.test_case_id: c for c in baseline.cases}
        curr_map = {c.test_case_id: c for c in current.cases}
        ids = sorted(set(base_map.keys()) | set(curr_map.keys()))

        deltas: list[CaseDelta] = []
        for tid in ids:
            b = base_map.get(tid)
            c = curr_map.get(tid)

            if b is None and c is not None:
                status = "added"
            elif b is not None and c is None:
                status = "removed"
            elif b is not None and c is not None:
                if b.passed and not c.passed:
                    status = "regressed"
                elif (not b.passed) and c.passed:
                    status = "improved"
                else:
                    status = "unchanged"
            else:
                continue

            deltas.append(
                CaseDelta(
                    test_case_id=tid,
                    baseline_passed=None if b is None else b.passed,
                    current_passed=None if c is None else c.passed,
                    status=status,  # type: ignore[arg-type]
                    metric_deltas=self._case_metric_deltas(b, c),
                    failure_reasons=list(c.failure_reasons) if c else [],
                )
            )
        return deltas

    def compare(
        self,
        baseline: EvalRunReport,
        current: EvalRunReport,
    ) -> RegressionReport:
        """组装完整 RegressionReport。"""
        case_deltas = self.diff_cases(baseline, current)
        return RegressionReport(
            baseline_run_id=baseline.run_id,
            current_run_id=current.run_id,
            baseline_git_sha=baseline.git_sha,
            current_git_sha=current.git_sha,
            aggregate_deltas=self.diff_aggregates(baseline, current),
            case_deltas=case_deltas,
            regressed_ids=[d.test_case_id for d in case_deltas if d.status == "regressed"],
            improved_ids=[d.test_case_id for d in case_deltas if d.status == "improved"],
        )

    def render_markdown(self, report: RegressionReport) -> str:
        """渲染 Markdown 差异报告。"""
        lines: list[str] = [
            "## Eval Regression Report — current vs baseline",
            "",
            f"- **baseline**: `{report.baseline_run_id}`"
            + (f" (`{report.baseline_git_sha}`)" if report.baseline_git_sha else ""),
            f"- **current**: `{report.current_run_id}`"
            + (f" (`{report.current_git_sha}`)" if report.current_git_sha else ""),
            f"- **regressed**: {len(report.regressed_ids)}",
            f"- **improved**: {len(report.improved_ids)}",
            "",
            "| Metric | Baseline | Current | Δ | Status |",
            "|--------|----------|---------|---|--------|",
        ]
        for m in report.aggregate_deltas:
            sign = "+" if m.delta > 0 else ""
            lines.append(
                f"| {m.metric_name} | {m.baseline:.4f} | {m.current:.4f} | "
                f"{sign}{m.delta:.4f} | {m.status} |"
            )

        lines.extend(["", "### Regressed Cases", ""])
        if not report.regressed_ids:
            lines.append("_无降级 Case_")
        else:
            for d in report.case_deltas:
                if d.status != "regressed":
                    continue
                md = ", ".join(
                    f"Δ{k}={v:+.4f}" for k, v in d.metric_deltas.items()
                ) or "n/a"
                reason = (
                    f" — {d.failure_reasons[0][:60]}"
                    if d.failure_reasons
                    else ""
                )
                lines.append(
                    f"- `{d.test_case_id}`: passed "
                    f"{d.baseline_passed}→{d.current_passed}, {md}{reason}"
                )

        lines.extend(["", "### Improved Cases", ""])
        if not report.improved_ids:
            lines.append("_无改进 Case_")
        else:
            for tid in report.improved_ids:
                lines.append(f"- `{tid}`")

        return "\n".join(lines) + "\n"

    def print_console(self, report: RegressionReport) -> None:
        """终端表格输出。"""
        print("\n" + "─" * 78)
        print(
            f" EvalReporter  baseline={report.baseline_run_id}  "
            f"current={report.current_run_id}"
        )
        print("─" * 78)
        print(f"{'Metric':<16} {'Base':>8} {'Curr':>8} {'Δ':>9} {'Status':<12}")
        print("─" * 78)
        for m in report.aggregate_deltas:
            print(
                f"{m.metric_name:<16} {m.baseline:>8.4f} {m.current:>8.4f} "
                f"{m.delta:>+9.4f} {m.status:<12}"
            )
        print("─" * 78)
        print(f"regressed_ids: {report.regressed_ids or '[]'}")
        print(f"improved_ids:  {report.improved_ids or '[]'}")
        print("─" * 78)

    def compare_and_report(
        self,
        baseline: EvalRunReport,
        current: EvalRunReport,
        markdown_path: Path | None = None,
    ) -> RegressionReport:
        """一键 Diff + 终端输出 + 可选落盘 Markdown。"""
        report = self.compare(baseline, current)
        self.print_console(report)
        md = self.render_markdown(report)
        print("\n📄 Markdown Preview:\n")
        print(md)
        if markdown_path is not None:
            markdown_path.parent.mkdir(parents=True, exist_ok=True)
            markdown_path.write_text(md, encoding="utf-8")
            print(f"💾 已写入: {markdown_path}")
        return report


# ═══════════════════════════════════════════════════════════════════════════
# 真实评测双报告生成
# ═══════════════════════════════════════════════════════════════════════════

DEMO_CONTEXTS = [
    (
        "ESM-2 采用 Masked Language Modeling (MLM) 在 UniRef50 上预训练，"
        "contact prediction F1 达到 0.89，在 remote homology 判别任务上表现更优。"
    ),
    (
        "ProteinBERT 采用双头架构 (MLM + GO 注释预测头)，"
        "在 GO term prediction 中 AUROC=0.92，显式利用功能注释监督信号。"
    ),
]

DEMO_EXPECTED = [
    ExpectedToolCall(
        name="rag_search",
        args={"query": "ESM-2 ProteinBERT", "top_k": 30},
    ),
    ExpectedToolCall(
        name="retrieve_memory",
        args={"user_id": "researcher_001"},
    ),
]

FAITHFUL_ANSWER = (
    "ESM-2 使用 MLM 在 UniRef50 预训练，contact prediction F1 为 0.89。"
    "ProteinBERT 双头架构在 GO term prediction 上 AUROC=0.92。"
)

HALLUCINATED_ANSWER = (
    "ESM-2 的 contact prediction F1 高达 0.99，远超所有已知文献。"
    "ProteinBERT 使用了 Quantum Attention，GO AUROC 达到 0.999。"
)

PASS_THRESHOLDS = {"tool_f1": 0.85, "faithfulness": 0.90}


class RegressionDemoHarness:
    """用真实 Evaluator 生成 baseline（全过）与 current（含回归）报告。"""

    def __init__(self) -> None:
        self.tool_eval = ToolExecutionEvaluator()
        self.faith_eval = FaithfulnessEvaluator(temperature=0.1)

    async def _eval_case(
        self,
        test_case_id: str,
        tool_calls: list[ToolCallRecord],
        answer: str,
    ) -> CaseEvalResult:
        """真实评测单条 Case。"""
        trace = EvalTrace(
            test_case_id=test_case_id,
            query="请对比 ESM-2 与 ProteinBERT 的定量指标差异。",
            tool_calls=tool_calls,
            retrieved_contexts=list(DEMO_CONTEXTS),
            final_answer=answer,
        )
        tool = self.tool_eval.evaluate(DEMO_EXPECTED, trace)
        print(f"   🔧 [{test_case_id}] Tool F1={tool.f1:.4f}")
        print(f"   🧠 [{test_case_id}] Faithfulness 真实 API...")
        faith = await self.faith_eval.evaluate(test_case_id, answer, DEMO_CONTEXTS)
        print(f"   🧠 [{test_case_id}] Faithfulness={faith.score:.4f}")

        passed = (
            tool.f1 >= PASS_THRESHOLDS["tool_f1"]
            and faith.score >= PASS_THRESHOLDS["faithfulness"]
        )
        return CaseEvalResult(
            test_case_id=test_case_id,
            passed=passed,
            tool_precision=tool.precision,
            tool_recall=tool.recall,
            tool_f1=tool.f1,
            param_accuracy=tool.param_accuracy,
            faithfulness=faith.score,
            failure_reasons=(
                list(faith.unsupported_claims[:3])
                + list(tool.unmatched_expected)
                + list(tool.unmatched_actual)
            ),
        )

    @staticmethod
    def _aggregate(cases: list[CaseEvalResult]) -> dict[str, float]:
        n = len(cases) or 1
        return {
            "tool_f1": round(sum(c.tool_f1 or 0.0 for c in cases) / n, 4),
            "faithfulness": round(sum(c.faithfulness or 0.0 for c in cases) / n, 4),
        }

    def _to_report(self, run_id: str, cases: list[CaseEvalResult]) -> EvalRunReport:
        now = datetime.now(timezone.utc).isoformat()
        return EvalRunReport(
            run_id=run_id,
            dataset_version="v1-regression-demo",
            dataset_path="day104/real_regression_samples",
            started_at=now,
            finished_at=now,
            aggregate=self._aggregate(cases),
            thresholds=dict(PASS_THRESHOLDS),
            cases=cases,
        )

    @staticmethod
    def _full_tools() -> list[ToolCallRecord]:
        return [
            ToolCallRecord(
                name="rag_search",
                args={"query": "ESM-2 ProteinBERT", "top_k": 30},
            ),
            ToolCallRecord(
                name="retrieve_memory",
                args={"user_id": "researcher_001"},
            ),
        ]

    @staticmethod
    def _partial_tools() -> list[ToolCallRecord]:
        return [
            ToolCallRecord(
                name="rag_search",
                args={"query": "ESM-2 ProteinBERT", "top_k": 30},
            ),
        ]

    async def build_baseline(self) -> EvalRunReport:
        """两条均正常 → 全 PASS。"""
        print("\n📦 生成 baseline（真实评测，期望全过）...")
        c1 = await self._eval_case("research_001", self._full_tools(), FAITHFUL_ANSWER)
        c2 = await self._eval_case("research_002", self._full_tools(), FAITHFUL_ANSWER)
        return self._to_report("baseline-day104", [c1, c2])

    async def build_current(self) -> EvalRunReport:
        """research_001 正常；research_002 漏调+幻觉 → 回归。"""
        print("\n📦 生成 current（真实评测，research_002 故意回归）...")
        c1 = await self._eval_case("research_001", self._full_tools(), FAITHFUL_ANSWER)
        c2 = await self._eval_case(
            "research_002",
            self._partial_tools(),
            HALLUCINATED_ANSWER,
        )
        return self._to_report("current-day104", [c1, c2])


# ═══════════════════════════════════════════════════════════════════════════
# 标准答案调试主入口
# ═══════════════════════════════════════════════════════════════════════════

async def main() -> None:
    print("=" * 70)
    print("🔬 Day 104 标准答案: EvalReporter 回归差异报告")
    print("=" * 70)

    harness = RegressionDemoHarness()
    baseline = await harness.build_baseline()
    current = await harness.build_current()

    out_dir = Path(w15_root) / "reports"
    baseline.save_json(out_dir / "eval_baseline.json")
    current.save_json(out_dir / "eval_current.json")
    print(f"\n💾 已保存: {out_dir / 'eval_baseline.json'}")
    print(f"💾 已保存: {out_dir / 'eval_current.json'}")

    reporter = EvalReporter()
    report = reporter.compare_and_report(
        baseline,
        current,
        markdown_path=out_dir / "regression_diff.md",
    )

    ok = (
        "research_002" in report.regressed_ids
        and any(
            m.metric_name in ("tool_f1", "faithfulness") and m.status == "regressed"
            for m in report.aggregate_deltas
        )
    )
    print(
        f"\n📊 过关验证: "
        f"{'✅ 定位到 research_002 回归且聚合 Δ 为负' if ok else '❌ 未正确检出回归'}"
    )
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
