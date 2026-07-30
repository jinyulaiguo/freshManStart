"""
Week 15 Day 104 学员练习模版: EvalReporter 回归差异报告 (practice.py)

===============================================================================
练习说明 (Exercise Specification)
===============================================================================
本练习目标是实现 EvalReporter：比对两次真实评测产出的 EvalRunReport，
计算聚合指标 Δ 与 Case 级 PASS→FAIL 清单，并渲染 Markdown / 终端输出。

学员需要补充：
1. diff_aggregates(): 聚合指标 Δ 与 status。
2. diff_cases(): 按 test_case_id 对齐，判定 regressed/improved/...。
3. compare(): 组装 RegressionReport。
4. render_markdown() / print_console(): 报告渲染。
5. compare_and_report(): 一键编排。

对照标准答案：reporter/eval_reporter_impl.py
===============================================================================
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

current_dir = os.path.dirname(os.path.abspath(__file__))
w15_root = os.path.abspath(os.path.join(current_dir, ".."))

if w15_root not in sys.path:
    sys.path.append(w15_root)

from contracts.schemas import (
    EvalRunReport,
    MetricDelta,
    CaseDelta,
    RegressionReport,
)


class EvalReporter:
    """
    回归差异报告微引擎：baseline vs current EvalRunReport。
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

    def __init__(self, epsilon: float = 1e-4):
        self.epsilon = epsilon

    def diff_aggregates(
        self,
        baseline: EvalRunReport,
        current: EvalRunReport,
    ) -> list[MetricDelta]:
        """
        TODO 1: 对共享聚合指标计算 Δ = current - baseline

        status: delta < -eps → regressed；> eps → improved；否则 unchanged。
        仅输出两侧 aggregate 都出现（或可默认 0）的指标。
        """
        raise NotImplementedError("TODO 1: 请实现 diff_aggregates！")

    def diff_cases(
        self,
        baseline: EvalRunReport,
        current: EvalRunReport,
    ) -> list[CaseDelta]:
        """
        TODO 2: 按 test_case_id 对齐 Case

        regressed: base PASS → curr FAIL
        improved: base FAIL → curr PASS
        unchanged / added / removed 按是否存在判定。
        metric_deltas 至少包含 tool_f1 / faithfulness（若有值）。
        """
        raise NotImplementedError("TODO 2: 请实现 diff_cases！")

    def compare(
        self,
        baseline: EvalRunReport,
        current: EvalRunReport,
    ) -> RegressionReport:
        """
        TODO 3: 组装 RegressionReport（含 regressed_ids / improved_ids）
        """
        raise NotImplementedError("TODO 3: 请实现 compare！")

    def render_markdown(self, report: RegressionReport) -> str:
        """
        TODO 4a: 渲染 Markdown 差异报告（聚合表 + Regressed Cases 列表）
        """
        raise NotImplementedError("TODO 4a: 请实现 render_markdown！")

    def print_console(self, report: RegressionReport) -> None:
        """
        TODO 4b: 终端漂亮输出 Δ 表与降级 Case ID
        """
        raise NotImplementedError("TODO 4b: 请实现 print_console！")

    def compare_and_report(
        self,
        baseline: EvalRunReport,
        current: EvalRunReport,
        markdown_path: Path | None = None,
    ) -> RegressionReport:
        """
        TODO 5: compare → print_console → 可选写入 markdown_path
        """
        raise NotImplementedError("TODO 5: 请实现 compare_and_report！")


def main() -> None:
    print("=" * 70)
    print("📝 运行 Day 104 学员练习调试入口 (practice.py)")
    print("   EvalReporter 回归差异报告")
    print("=" * 70)
    print("💡 完整演示请运行: python weekly/w15_eval_system/reporter/eval_reporter_impl.py")
    try:
        EvalReporter().diff_aggregates(
            EvalRunReport(run_id="b", aggregate={"tool_f1": 1.0}),
            EvalRunReport(run_id="c", aggregate={"tool_f1": 0.7}),
        )
    except NotImplementedError as e:
        print(f"\n📌 [TODO 拦截提示]: {e}")
        print("💡 提示: 请打开 `weekly/w15_eval_system/day104/practice.py` 完成 TODO。")


if __name__ == "__main__":
    main()
