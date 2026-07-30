"""
Week 15 Day 103 参考标准答案: CI ThresholdGate + 真实评测门禁
(threshold_gate_impl.py)

===============================================================================
设计方案说明 (Architecture Design Specification)
===============================================================================

1. 设计意图 (Design Intent):
   Agent 质量指标若只停留在本机手工跑，PR 合入无法强制拦截回归。本模块实现
   ThresholdGate（确定性阈值裁决）与 RealCiEvalHarness（真实调用 Day 101 Tool F1
   + Day 102 Faithfulness），将聚合指标写入 EvalRunReport 后执行 exit 0/1 契约。
   严禁用假 JSON 凑过关；负样本必须通过真实漏调 + 幻觉回复触发拦截。

2. 核心类与数据流结构 (Class & Data Flow):
   - ThresholdGate.check / enforce: aggregate vs thresholds → GateVerdict / SystemExit
   - RealCiEvalHarness.build_report: 真实 Evaluator → EvalRunReport
   - RealCiEvalHarness.run_scenario: demo_pass | demo_fail | pr | full
   - GateVerdict / GateCheckItem: contracts/schemas.py

3. 核心用例设计意图 (Test Case Design Intent):
   - demo_pass: 工具完全匹配 + 忠实复述 Context → tool_f1/faithfulness 过线 → exit 0
   - demo_fail: 漏调 retrieve_memory + 数字幻觉 → 不过线 → exit 1
   - --mode=pr / full: CI 跑正样本子集并 enforce（需 secrets 中的真实 API Key）
===============================================================================
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone

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
    CaseEvalResult,
    EvalRunReport,
    EvalTrace,
    ExpectedToolCall,
    GateCheckItem,
    GateVerdict,
    ToolCallRecord,
)
from tool_execution_impl import ToolExecutionEvaluator
from faithfulness_impl import FaithfulnessEvaluator


# ═══════════════════════════════════════════════════════════════════════════
# ThresholdGate
# ═══════════════════════════════════════════════════════════════════════════

class ThresholdGate:
    """
    CI 阈值门禁微引擎。

    比对 EvalRunReport.aggregate 与阈值；不通过时以非 0 退出码拦截。
    Gate 本身不调用 LLM —— aggregate 必须由真实评测写入。
    """

    DEFAULT_THRESHOLDS: dict[str, float] = {
        "tool_f1": 0.85,
        "faithfulness": 0.90,
    }

    def __init__(self, thresholds: dict[str, float] | None = None):
        self.thresholds = dict(thresholds or self.DEFAULT_THRESHOLDS)

    def check(self, report: EvalRunReport, mode: str = "pr") -> GateVerdict:
        """
        对报告聚合指标执行阈值比对。

        Parameters
        ----------
        report:
            真实评测产出的 EvalRunReport。
        mode:
            运行模式标签，写入 GateVerdict。

        Returns
        -------
        GateVerdict
            含逐项 GateCheckItem 与 exit_code 语义。
        """
        checks: list[GateCheckItem] = []
        failed: list[str] = []

        # 步骤 1：逐指标比对 aggregate vs threshold
        for metric_name, threshold in self.thresholds.items():
            actual = float(report.aggregate.get(metric_name, 0.0))
            ok = actual >= threshold
            checks.append(
                GateCheckItem(
                    metric_name=metric_name,
                    actual=round(actual, 4),
                    threshold=threshold,
                    passed=ok,
                    delta=round(actual - threshold, 4),
                )
            )
            if not ok:
                failed.append(metric_name)

        # 步骤 2：汇总裁决文案
        passed = len(failed) == 0
        if passed:
            message = f"门禁通过 (mode={mode})：全部指标达到阈值"
        else:
            detail = ", ".join(
                f"{c.metric_name}={c.actual:.4f}<{c.threshold}"
                for c in checks
                if not c.passed
            )
            message = f"门禁拦截 (mode={mode})：{detail}"

        return GateVerdict(
            passed=passed,
            mode=mode,
            checks=checks,
            failed_metrics=failed,
            message=message,
        )

    def enforce(self, report: EvalRunReport, mode: str = "pr") -> GateVerdict:
        """
        执行门禁；失败时 raise SystemExit(1) 供 CI 捕获。

        Returns
        -------
        GateVerdict
            仅在通过时正常返回。
        """
        verdict = self.check(report, mode=mode)
        print_verdict(verdict)
        if not verdict.passed:
            print(f"\n🚫 {verdict.message}")
            raise SystemExit(1)
        print(f"\n✅ {verdict.message}")
        return verdict


# ═══════════════════════════════════════════════════════════════════════════
# 真实评测样本 (W14 Research Agent 场景)
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


def _build_trace(
    test_case_id: str,
    tool_calls: list[ToolCallRecord],
    answer: str,
) -> EvalTrace:
    """构造单条 EvalTrace 快照。"""
    return EvalTrace(
        test_case_id=test_case_id,
        query="请对比 ESM-2 与 ProteinBERT 的定量指标差异。",
        tool_calls=tool_calls,
        retrieved_contexts=list(DEMO_CONTEXTS),
        final_answer=answer,
    )


def _scenario_inputs(scenario: str) -> tuple[str, EvalTrace, str]:
    """
    按场景返回 (mode, trace, answer)。

    demo_pass / pr / full → 正样本；demo_fail → 负样本。
    """
    if scenario in ("demo_pass", "pr", "full"):
        trace = _build_trace(
            "research_ci_pass",
            [
                ToolCallRecord(
                    name="rag_search",
                    args={"query": "ESM-2 ProteinBERT", "top_k": 30},
                ),
                ToolCallRecord(
                    name="retrieve_memory",
                    args={"user_id": "researcher_001"},
                ),
            ],
            FAITHFUL_ANSWER,
        )
        return scenario, trace, FAITHFUL_ANSWER

    if scenario == "demo_fail":
        # 漏调 retrieve_memory + 幻觉回复 → 双指标跌破阈值
        trace = _build_trace(
            "research_ci_fail",
            [
                ToolCallRecord(
                    name="rag_search",
                    args={"query": "ESM-2 ProteinBERT", "top_k": 30},
                ),
            ],
            HALLUCINATED_ANSWER,
        )
        return "demo_fail", trace, HALLUCINATED_ANSWER

    raise ValueError(f"未知 scenario: {scenario}")


# ═══════════════════════════════════════════════════════════════════════════
# RealCiEvalHarness
# ═══════════════════════════════════════════════════════════════════════════

class RealCiEvalHarness:
    """
    真实评测编排器：调用已实现的 Tool / Faithfulness 微引擎，禁止假 JSON。
    """

    def __init__(self) -> None:
        self.tool_eval = ToolExecutionEvaluator()
        self.faith_eval = FaithfulnessEvaluator(temperature=0.1)
        self.gate = ThresholdGate()

    async def build_report(
        self,
        *,
        run_id: str,
        mode: str,
        expected_tools: list[ExpectedToolCall],
        trace: EvalTrace,
        answer: str,
        contexts: list[str],
    ) -> EvalRunReport:
        """
        真实评测单条样本并组装 EvalRunReport。

        Returns
        -------
        EvalRunReport
            aggregate 含 tool_f1 与 faithfulness。
        """
        # 步骤 1：确定性 Tool F1
        tool_result = self.tool_eval.evaluate(expected_tools, trace)
        print(
            f"   🔧 Tool F1={tool_result.f1:.4f} "
            f"(P={tool_result.precision:.4f} R={tool_result.recall:.4f})"
        )

        # 步骤 2：真实 LLM Faithfulness
        print("   🧠 调用 FaithfulnessEvaluator (真实 API)...")
        faith_result = await self.faith_eval.evaluate(
            trace.test_case_id,
            answer,
            contexts,
        )
        print(
            f"   🧠 Faithfulness={faith_result.score:.4f} "
            f"unsupported={len(faith_result.unsupported_claims)}"
        )

        # 步骤 3：写入 Case + 聚合报告
        case = CaseEvalResult(
            test_case_id=trace.test_case_id,
            passed=(
                tool_result.f1 >= self.gate.thresholds["tool_f1"]
                and faith_result.score >= self.gate.thresholds["faithfulness"]
            ),
            tool_precision=tool_result.precision,
            tool_recall=tool_result.recall,
            tool_f1=tool_result.f1,
            param_accuracy=tool_result.param_accuracy,
            faithfulness=faith_result.score,
            failure_reasons=(
                list(faith_result.unsupported_claims[:3])
                + list(tool_result.unmatched_expected)
                + list(tool_result.unmatched_actual)
            ),
        )

        now = datetime.now(timezone.utc).isoformat()
        return EvalRunReport(
            run_id=run_id,
            dataset_version="v1-ci-subset",
            dataset_path="day103/real_ci_samples",
            started_at=now,
            finished_at=now,
            aggregate={
                "tool_f1": float(tool_result.f1),
                "faithfulness": float(faith_result.score),
            },
            thresholds=dict(self.gate.thresholds),
            cases=[case],
        )

    async def run_scenario(self, scenario: str) -> tuple[EvalRunReport, GateVerdict]:
        """
        执行正/负样本真实评测并返回门禁裁决（不在此处 SystemExit）。

        Parameters
        ----------
        scenario:
            demo_pass | demo_fail | pr | full
        """
        mode, trace, answer = _scenario_inputs(scenario)
        print(f"\n🎯 场景: {scenario}")
        report = await self.build_report(
            run_id=f"day103-{scenario}-{datetime.now(timezone.utc).strftime('%H%M%S')}",
            mode=mode,
            expected_tools=DEMO_EXPECTED,
            trace=trace,
            answer=answer,
            contexts=DEMO_CONTEXTS,
        )
        verdict = self.gate.check(report, mode=mode)
        return report, verdict


def print_verdict(verdict: GateVerdict) -> None:
    """终端表格输出门禁明细。"""
    print("\n" + "─" * 72)
    print(f" ThresholdGate 裁决  mode={verdict.mode}  exit_code={verdict.exit_code}")
    print("─" * 72)
    print(f"{'Metric':<16} {'Actual':>8} {'Threshold':>10} {'Δ':>8} {'Pass':>6}")
    print("─" * 72)
    for c in verdict.checks:
        print(
            f"{c.metric_name:<16} {c.actual:>8.4f} {c.threshold:>10.2f} "
            f"{c.delta:>8.4f} {'✅' if c.passed else '❌':>6}"
        )
    print("─" * 72)
    print(verdict.message)


# ═══════════════════════════════════════════════════════════════════════════
# CLI / 调试主入口
# ═══════════════════════════════════════════════════════════════════════════

async def _run_local_verification() -> int:
    """
    本地过关：真实 API 验证正样本 exit 0、负样本 exit 1。

    Returns
    -------
    int
        0 表示两种退出码契约均符合预期；1 表示验证失败。
    """
    print("=" * 70)
    print("🔬 Day 103 标准答案: ThresholdGate + 真实评测 CI 门禁")
    print("=" * 70)

    harness = RealCiEvalHarness()
    all_ok = True

    # 正样本：应放行
    _, pass_verdict = await harness.run_scenario("demo_pass")
    print_verdict(pass_verdict)
    if pass_verdict.exit_code != 0:
        print("❌ 期望 demo_pass exit_code=0")
        all_ok = False
    else:
        print("✅ demo_pass 退出码契约正确 (0)")

    # 负样本：应拦截（复用同一份 report 验证 enforce，避免重复烧 API）
    fail_report, fail_verdict = await harness.run_scenario("demo_fail")
    print_verdict(fail_verdict)
    if fail_verdict.exit_code != 1:
        print("❌ 期望 demo_fail exit_code=1")
        all_ok = False
    else:
        print("✅ demo_fail 退出码契约正确 (1)")

    print("\n🔁 验证 enforce() 对负样本抛出 SystemExit(1)...")
    try:
        harness.gate.enforce(fail_report, mode="demo_fail")
        print("❌ enforce 未抛出 SystemExit")
        all_ok = False
    except SystemExit as exc:
        if exc.code == 1:
            print("✅ enforce SystemExit(1) 捕获成功")
        else:
            print(f"❌ enforce exit code={exc.code}，期望 1")
            all_ok = False

    print(
        f"\n📊 过关验证: "
        f"{'✅ 真实评测门禁退出码契约全部通过' if all_ok else '❌ 存在契约失败'}"
    )
    return 0 if all_ok else 1


async def _run_ci_mode(mode: str) -> None:
    """CI 模式：跑子集真实评测并 enforce（失败即非 0 退出）。"""
    print("=" * 70)
    print(f"🚀 Day 103 CI 模式: mode={mode}")
    print("=" * 70)
    harness = RealCiEvalHarness()
    report, _ = await harness.run_scenario(mode)
    harness.gate.enforce(report, mode=mode)


def main() -> None:
    parser = argparse.ArgumentParser(description="Day 103 ThresholdGate CI 门禁")
    parser.add_argument(
        "--mode",
        choices=["local", "pr", "full"],
        default="local",
        help="local=正负样本契约验证；pr/full=CI enforce",
    )
    args = parser.parse_args()

    if args.mode == "local":
        raise SystemExit(asyncio.run(_run_local_verification()))
    asyncio.run(_run_ci_mode(args.mode))


if __name__ == "__main__":
    main()
