"""
Week 15 Day 105 学员练习模版: 评测流水线拼装 (practice.py)

===============================================================================
练习说明
===============================================================================
对照标准答案 weekly/w15_eval_system/run_eval.py，补齐：
1. 加载 Golden Dataset 并按 limit 切片
2. mock / live 收集 EvalTrace
3. 调用 ToolExecutionEvaluator + Faithfulness（可 offline）
4. 组装 EvalRunReport.aggregate
5. ThresholdGate.enforce + EvalReporter.compare_and_report
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

from contracts.schemas import EvalRunReport, GoldenCase, load_golden_dataset


async def run_practice(
    dataset: Path,
    *,
    limit: int = 5,
    scenario: str = "default",
    enforce_gate: bool = True,
) -> EvalRunReport:
    """
    TODO: 实现最小评测流水线。

    提示：
    - MockTraceRunner(scenario=...).build_traces(cases)
    - ToolExecutionEvaluator().evaluate(expected, trace)
    - 离线 faithfulness：答案含 Quantum Attention → 低分
    - ThresholdGate().enforce(report)
    """
    cases: list[GoldenCase] = load_golden_dataset(dataset)[:limit]
    _ = cases
    _ = scenario
    _ = enforce_gate
    raise NotImplementedError("TODO: 请实现 Day 105 评测流水线拼装")


if __name__ == "__main__":
    print("请实现 run_practice，或直接运行 ../run_eval.py")
