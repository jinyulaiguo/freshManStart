"""
Week 15 Day 101 学员练习模版: 工具调用 Precision / Recall / F1 评测引擎 (practice.py)

===============================================================================
练习说明 (Exercise Specification)
===============================================================================
本练习目标是实现确定性的 ToolExecutionEvaluator 微引擎，比对 GoldenCase.expected_tools
与 EvalTrace.tool_calls，计算工具选择的 Precision / Recall / F1 以及参数准确率，
并在终端以表格输出。本评测无需 LLM，可在 CI 中零成本复现。

学员需要补充 ToolExecutionEvaluator 中以下关键方法：
1. `_normalize_value()`: 递归归一化参数值 (字符串 / 数值 / 嵌套结构)。
2. `_compare_params()`: 键级参数比对，返回 (matched, error_messages)。
3. `_match_by_name()`: Multiset 贪心匹配期望与实际工具调用。
4. `evaluate()`: 单条 Case 计算 P/R/F1 + param_accuracy。
5. `evaluate_batch()` / `print_result_table()`: 批量聚合与终端表格。

请根据提示完成 TODO 部分的代码实现！
完成后可对照参考标准答案 `evaluators/tool_execution_impl.py`。
===============================================================================
"""

from __future__ import annotations

import os
import sys
from typing import Any

current_dir = os.path.dirname(os.path.abspath(__file__))
w15_root = os.path.abspath(os.path.join(current_dir, ".."))

if w15_root not in sys.path:
    sys.path.append(w15_root)

from contracts.schemas import (
    ExpectedToolCall,
    EvalTrace,
    ToolCallRecord,
    ToolExecutionBatchResult,
    ToolExecutionResult,
    ToolMatchDetail,
)


class ToolExecutionEvaluator:
    """
    工具调用 Precision / Recall / F1 确定性评测微引擎

    比对 expected_tools 与 Trace.tool_calls，顺序无关 Multiset 匹配。
    """

    def __init__(
        self,
        numeric_tolerance: float = 0.0,
        case_insensitive_strings: bool = True,
    ):
        self.numeric_tolerance = numeric_tolerance
        self.case_insensitive_strings = case_insensitive_strings

    def _normalize_value(self, value: Any) -> Any:
        """
        TODO 1: 递归归一化参数值

        要求：
        1. str → strip + 连续空白折叠；若 case_insensitive_strings 则 lower；
        2. int / float → float（便于容差比较）；
        3. bool / None → 原样返回；
        4. list → 逐元素递归归一化；
        5. dict → key 排序后递归归一化 value。
        """
        # ---------------------------------------------------------------------
        # TODO: 请在此处实现参数值归一化逻辑
        # ---------------------------------------------------------------------
        raise NotImplementedError("TODO 1: 请实现 _normalize_value 参数归一化！")

    def _compare_params(
        self,
        expected_args: dict[str, Any],
        actual_args: dict[str, Any],
    ) -> tuple[bool, list[str]]:
        """
        TODO 2: 键级参数比对

        要求：
        1. 对 expected / actual 的每个 key 做归一化后比较；
        2. 数值用 abs(a-b) <= numeric_tolerance；
        3. 缺键、多键、值不等均写入 error 字符串；
        4. 返回 (全部匹配?, error_messages)。
        """
        # ---------------------------------------------------------------------
        # TODO: 请在此处实现参数键级比对逻辑
        # ---------------------------------------------------------------------
        raise NotImplementedError("TODO 2: 请实现 _compare_params 参数比对！")

    def _match_by_name(
        self,
        expected: list[ExpectedToolCall],
        actual: list[ToolCallRecord],
    ) -> tuple[list[ToolMatchDetail], list[str], list[str]]:
        """
        TODO 3: Multiset 贪心匹配工具名

        要求：
        1. 按期望顺序遍历，从实际调用中找第一个同名且未消费的记录；
        2. 匹配成功则调用 _compare_params，写入 ToolMatchDetail；
        3. 未匹配的期望名进入 unmatched_expected；
        4. 未被消费的实际名进入 unmatched_actual；
        5. 返回 (matched_details, unmatched_actual, unmatched_expected)。
        """
        # ---------------------------------------------------------------------
        # TODO: 请在此处实现 Multiset 工具名匹配逻辑
        # ---------------------------------------------------------------------
        raise NotImplementedError("TODO 3: 请实现 _match_by_name Multiset 匹配！")

    def evaluate(
        self,
        expected_tools: list[ExpectedToolCall],
        trace: EvalTrace,
    ) -> ToolExecutionResult:
        """
        TODO 4: 单条 Case 评测

        要求：
        1. 调用 _match_by_name 得到匹配明细；
        2. TP = name_matched 数量；
           FP = len(unmatched_actual)；
           FN = len(unmatched_expected)；
        3. precision / recall / f1 按标准公式，分母为 0 时记 0.0；
        4. param_accuracy = 参数全对的匹配数 / name 匹配数（无为 0.0）；
        5. 返回 ToolExecutionResult。
        """
        # ---------------------------------------------------------------------
        # TODO: 请在此处实现单条评测逻辑
        # ---------------------------------------------------------------------
        raise NotImplementedError("TODO 4: 请实现 evaluate 单条评测！")

    def evaluate_batch(
        self,
        pairs: list[tuple[list[ExpectedToolCall], EvalTrace]],
    ) -> ToolExecutionBatchResult:
        """
        TODO 5a: 批量评测并聚合均值

        要求：对每对 (expected, trace) 调用 evaluate，计算 mean_precision /
        mean_recall / mean_f1 / mean_param_accuracy。
        """
        # ---------------------------------------------------------------------
        # TODO: 请在此处实现批量聚合逻辑
        # ---------------------------------------------------------------------
        raise NotImplementedError("TODO 5a: 请实现 evaluate_batch 批量聚合！")

    def print_result_table(
        self,
        results: list[ToolExecutionResult],
        title: str = "Tool Execution Eval",
    ) -> None:
        """
        TODO 5b: 终端表格输出

        要求：打印 test_case_id / P / R / F1 / param_acc / TP / FP / FN 列。
        """
        # ---------------------------------------------------------------------
        # TODO: 请在此处实现终端表格输出
        # ---------------------------------------------------------------------
        raise NotImplementedError("TODO 5b: 请实现 print_result_table 表格输出！")


# ===============================================================================
# 调试主入口 (Debug Main Entrypoint)
# ===============================================================================

def _demo_pairs() -> list[tuple[str, list[ExpectedToolCall], EvalTrace]]:
    """四类 Mock 场景：完美 / 漏调 / 多调 / 参数错误"""
    expected = [
        ExpectedToolCall(name="rag_search", args={"query": "ESM-2 ProteinBERT", "top_k": 30}),
        ExpectedToolCall(name="retrieve_memory", args={"user_id": "researcher_001"}),
    ]

    perfect = EvalTrace(
        test_case_id="research_001",
        query="对比 ESM-2 与 ProteinBERT",
        tool_calls=[
            ToolCallRecord(name="rag_search", args={"query": "ESM-2 ProteinBERT", "top_k": 30}),
            ToolCallRecord(name="retrieve_memory", args={"user_id": "researcher_001"}),
        ],
        final_answer="placeholder answer for demo",
    )
    missing = EvalTrace(
        test_case_id="research_002",
        query="对比 ESM-2 与 ProteinBERT",
        tool_calls=[
            ToolCallRecord(name="rag_search", args={"query": "ESM-2 ProteinBERT", "top_k": 30}),
        ],
        final_answer="placeholder answer for demo",
    )
    extra = EvalTrace(
        test_case_id="research_003",
        query="对比 ESM-2 与 ProteinBERT",
        tool_calls=[
            ToolCallRecord(name="rag_search", args={"query": "ESM-2 ProteinBERT", "top_k": 30}),
            ToolCallRecord(name="retrieve_memory", args={"user_id": "researcher_001"}),
            ToolCallRecord(name="model_router", args={"prefer": "fast"}),
        ],
        final_answer="placeholder answer for demo",
    )
    bad_param = EvalTrace(
        test_case_id="research_004",
        query="对比 ESM-2 与 ProteinBERT",
        tool_calls=[
            ToolCallRecord(name="rag_search", args={"query": "ESM-2 ProteinBERT", "top_k": 5}),
            ToolCallRecord(name="retrieve_memory", args={"user_id": "researcher_001"}),
        ],
        final_answer="placeholder answer for demo",
    )
    return [
        ("完美匹配", expected, perfect),
        ("漏调工具", expected, missing),
        ("多余调用", expected, extra),
        ("参数错误", expected, bad_param),
    ]


def main() -> None:
    print("=" * 70)
    print("📝 运行 Day 101 学员练习调试入口 (practice.py)")
    print("   工具调用 Precision / Recall / F1 评测引擎")
    print("=" * 70)

    evaluator = ToolExecutionEvaluator()

    try:
        pairs: list[tuple[list[ExpectedToolCall], EvalTrace]] = []
        for label, expected, trace in _demo_pairs():
            result = evaluator.evaluate(expected, trace)
            print(f"\n[{label}] {trace.test_case_id}: "
                  f"P={result.precision:.2f} R={result.recall:.2f} "
                  f"F1={result.f1:.2f} param={result.param_accuracy:.2f}")
            pairs.append((expected, trace))

        batch = evaluator.evaluate_batch(pairs)
        evaluator.print_result_table(batch.cases)
        print(f"\n📊 批量均值 F1: {batch.mean_f1:.3f}")

    except NotImplementedError as e:
        print(f"\n📌 [TODO 拦截提示]: {e}")
        print("💡 提示: 请打开 `weekly/w15_eval_system/day101/practice.py` 完成 TODO。")
        print("💡 参考: 完成后对照 `evaluators/tool_execution_impl.py`。")


if __name__ == "__main__":
    main()
