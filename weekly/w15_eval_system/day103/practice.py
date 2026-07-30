"""
Week 15 Day 103 学员练习模版: CI ThresholdGate 评测门禁 (practice.py)

===============================================================================
练习说明 (Exercise Specification)
===============================================================================
本练习目标是实现确定性的 ThresholdGate，以及编排真实 Tool F1 + Faithfulness
评测后写入 EvalRunReport 的迷你流水线。门禁输入必须来自真实评测，禁止假 JSON。

学员需要补充：
1. ThresholdGate.check(): 比对 aggregate 与阈值，生成 GateVerdict。
2. ThresholdGate.enforce(): 不通过则 SystemExit(1)。
3. RealCiEvalHarness.build_report(): 真实调用 Tool + Faithfulness 组装报告。
4. RealCiEvalHarness.run_scenario(): demo_pass / demo_fail 场景。
5. print_verdict(): 终端打印门禁明细。

对照标准答案：gate/threshold_gate_impl.py
===============================================================================
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any

current_dir = os.path.dirname(os.path.abspath(__file__))
repo_root = os.path.abspath(os.path.join(current_dir, "../../.."))
w04_path = os.path.abspath(os.path.join(current_dir, "../../w04_prompt_and_http"))
w15_root = os.path.abspath(os.path.join(current_dir, ".."))
evaluators_dir = os.path.join(w15_root, "evaluators")

for p in (repo_root, w04_path, w15_root, evaluators_dir):
    if p not in sys.path:
        sys.path.append(p)

from contracts.schemas import EvalRunReport, GateVerdict


class ThresholdGate:
    """
    CI 阈值门禁：比对 EvalRunReport.aggregate 与预设阈值。
    """

    DEFAULT_THRESHOLDS: dict[str, float] = {
        "tool_f1": 0.85,
        "faithfulness": 0.90,
    }

    def __init__(self, thresholds: dict[str, float] | None = None):
        self.thresholds = dict(thresholds or self.DEFAULT_THRESHOLDS)

    def check(self, report: EvalRunReport, mode: str = "pr") -> GateVerdict:
        """
        TODO 1: 对 report.aggregate 中每个阈值指标做比对

        要求：
        1. 对 self.thresholds 的每个 metric，读取 aggregate.get(metric, 0.0)；
        2. passed_i = actual >= threshold；生成 GateCheckItem (含 delta)；
        3. 汇总 failed_metrics；整体 passed = 无失败项；
        4. 返回 GateVerdict。
        """
        raise NotImplementedError("TODO 1: 请实现 ThresholdGate.check！")

    def enforce(self, report: EvalRunReport, mode: str = "pr") -> GateVerdict:
        """
        TODO 2: 调用 check；若 not passed 则 print 后 raise SystemExit(1)
        """
        raise NotImplementedError("TODO 2: 请实现 ThresholdGate.enforce！")


class RealCiEvalHarness:
    """
    真实评测编排：Tool F1 + Faithfulness → EvalRunReport
    """

    async def build_report(
        self,
        *,
        run_id: str,
        mode: str,
        expected_tools: list[Any],
        trace: Any,
        answer: str,
        contexts: list[str],
    ) -> EvalRunReport:
        """
        TODO 3: 真实调用 ToolExecutionEvaluator + FaithfulnessEvaluator

        要求：
        1. tool_eval.evaluate(expected_tools, trace) → tool_f1；
        2. await faith_eval.evaluate(trace.test_case_id, answer, contexts)；
        3. 组装 EvalRunReport(aggregate={tool_f1, faithfulness}, thresholds=...)。
        """
        raise NotImplementedError("TODO 3: 请实现 RealCiEvalHarness.build_report！")

    async def run_scenario(self, scenario: str) -> tuple[EvalRunReport, GateVerdict]:
        """
        TODO 4: scenario in {demo_pass, demo_fail}

        demo_pass: 完整工具调用 + 忠实复述
        demo_fail: 漏调工具 + 幻觉回复
        返回 (report, gate.check(report))，不要在此处 SystemExit。
        """
        raise NotImplementedError("TODO 4: 请实现 run_scenario！")


def print_verdict(verdict: GateVerdict) -> None:
    """
    TODO 5: 终端打印各指标 actual/threshold/passed 与 exit_code
    """
    raise NotImplementedError("TODO 5: 请实现 print_verdict！")


async def main() -> None:
    print("=" * 70)
    print("📝 运行 Day 103 学员练习调试入口 (practice.py)")
    print("   CI ThresholdGate + 真实评测门禁")
    print("=" * 70)

    harness = RealCiEvalHarness()
    try:
        report, verdict = await harness.run_scenario("demo_pass")
        print_verdict(verdict)
        print(f"demo_pass exit_code={verdict.exit_code}")
    except NotImplementedError as e:
        print(f"\n📌 [TODO 拦截提示]: {e}")
        print("💡 提示: 请打开 `weekly/w15_eval_system/day103/practice.py` 完成 TODO。")
        print("💡 参考: `gate/threshold_gate_impl.py`。")


if __name__ == "__main__":
    asyncio.run(main())
