"""
Week 15 Day 101 参考标准答案: 工具调用 Precision / Recall / F1 评测引擎
(tool_execution_impl.py)

===============================================================================
设计方案说明 (Architecture Design Specification)
===============================================================================

1. 设计意图 (Design Intent):
   ReAct Agent 的工具选错、参数漏传无法被 G-Eval 主观指标捕获。本模块实现
   确定性 ToolExecutionEvaluator：将 GoldenCase.expected_tools 与 EvalTrace.tool_calls
   按 Multiset 贪心对齐工具名，再对匹配对做参数归一化键级比对，输出
   Precision / Recall / F1 与 param_accuracy，供 Day 103 CI 门禁 (F1 >= 0.85) 消费。

2. 核心类与数据流结构 (Class & Data Flow):
   - ToolExecutionEvaluator:
     - _normalize_value(): 字符串 / 数值 / 嵌套结构递归归一化
     - _compare_params(): 键级 diff → (matched, errors)
     - _match_by_name(): Multiset 贪心绑定 expected ↔ actual
     - evaluate(): 单 Case → ToolExecutionResult
     - evaluate_batch(): 批量均值 → ToolExecutionBatchResult
     - print_result_table(): 终端表格
   - ToolMatchDetail / ToolExecutionResult: contracts/schemas.py 契约

3. 核心用例设计意图 (Test Case Design Intent):
   使用 W14 Research Agent 典型工具链 (rag_search + retrieve_memory) 构造四类
   Mock Trace，无需 LLM / 网络：
   - 完美匹配: 验证 F1=1.0 且 param_accuracy=1.0
   - 漏调: 验证 Recall 下降、FN=1
   - 多调: 验证 Precision 下降、FP=1
   - 参数错误 (top_k=5 vs 30): 验证 F1=1.0 但 param_accuracy=0.5
===============================================================================
"""

from __future__ import annotations

import os
import re
import sys
from typing import Any

# ── 路径注入 ──────────────────────────────────────────────────────────────
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


# ═══════════════════════════════════════════════════════════════════════════
# ToolExecutionEvaluator 微引擎
# ═══════════════════════════════════════════════════════════════════════════

class ToolExecutionEvaluator:
    """
    工具调用 Precision / Recall / F1 确定性评测微引擎

    Parameters
    ----------
    numeric_tolerance:
        数值参数绝对容差，默认 0（top_k 等必须精确）。
    case_insensitive_strings:
        字符串比较是否忽略大小写，默认 True。
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
        递归归一化参数值，消除无关表面差异导致的假阴性。

        Returns
        -------
        Any
            归一化后的可比较值。
        """
        # 步骤 1：字符串 — strip + 空白折叠 + 可选 lower
        if isinstance(value, str):
            collapsed = re.sub(r"\s+", " ", value.strip())
            if self.case_insensitive_strings:
                return collapsed.lower()
            return collapsed

        # 步骤 2：布尔 / None — 原样（bool 必须在 int 之前判断）
        if isinstance(value, bool) or value is None:
            return value

        # 步骤 3：数值 — 统一为 float 便于容差比较
        if isinstance(value, (int, float)):
            return float(value)

        # 步骤 4：列表 — 逐元素递归
        if isinstance(value, list):
            return [self._normalize_value(item) for item in value]

        # 步骤 5：字典 — key 排序后递归 value，保证键序无关
        if isinstance(value, dict):
            return {
                str(k): self._normalize_value(v)
                for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))
            }

        # 步骤 6：其余类型 — 转为字符串兜底
        return str(value)

    def _values_equal(self, expected: Any, actual: Any) -> bool:
        """比较两个已归一化的值，数值走容差。"""
        if isinstance(expected, float) and isinstance(actual, float):
            return abs(expected - actual) <= self.numeric_tolerance
        return expected == actual

    def _compare_params(
        self,
        expected_args: dict[str, Any],
        actual_args: dict[str, Any],
    ) -> tuple[bool, list[str]]:
        """
        键级参数比对。

        Returns
        -------
        tuple[bool, list[str]]
            (是否全部匹配, 误差描述列表)
        """
        errors: list[str] = []
        expected_keys = set(expected_args.keys())
        actual_keys = set(actual_args.keys())

        # 步骤 1：缺键 / 多键
        for key in sorted(expected_keys - actual_keys):
            errors.append(f"{key}: missing in actual (expected={expected_args[key]!r})")
        for key in sorted(actual_keys - expected_keys):
            errors.append(f"{key}: unexpected in actual (actual={actual_args[key]!r})")

        # 步骤 2：共有键值比对
        for key in sorted(expected_keys & actual_keys):
            norm_exp = self._normalize_value(expected_args[key])
            norm_act = self._normalize_value(actual_args[key])
            if not self._values_equal(norm_exp, norm_act):
                errors.append(
                    f"{key}: expected={expected_args[key]!r} actual={actual_args[key]!r}"
                )

        return (len(errors) == 0, errors)

    def _match_by_name(
        self,
        expected: list[ExpectedToolCall],
        actual: list[ToolCallRecord],
    ) -> tuple[list[ToolMatchDetail], list[str], list[str]]:
        """
        Multiset 贪心匹配：按期望顺序消费第一个同名且未使用的实际调用。

        Returns
        -------
        tuple[list[ToolMatchDetail], list[str], list[str]]
            (匹配明细, 未消费的实际工具名, 未匹配的期望工具名)
        """
        # 步骤 1：标记实际调用是否已被消费
        used = [False] * len(actual)
        details: list[ToolMatchDetail] = []
        unmatched_expected: list[str] = []

        # 步骤 2：遍历期望，贪心绑定同名实际调用
        for exp in expected:
            matched_idx: int | None = None
            for idx, act in enumerate(actual):
                if not used[idx] and act.name == exp.name:
                    matched_idx = idx
                    break

            if matched_idx is None:
                # 期望未被消费 → FN
                unmatched_expected.append(exp.name)
                details.append(
                    ToolMatchDetail(
                        expected_name=exp.name,
                        actual_name=None,
                        name_matched=False,
                        param_matched=False,
                        param_errors=["tool not called"],
                    )
                )
                continue

            # 步骤 3：消费并比对参数
            used[matched_idx] = True
            act = actual[matched_idx]
            param_ok, param_errors = self._compare_params(exp.args, act.args)
            details.append(
                ToolMatchDetail(
                    expected_name=exp.name,
                    actual_name=act.name,
                    name_matched=True,
                    param_matched=param_ok,
                    param_errors=param_errors,
                )
            )

        # 步骤 4：未被消费的实际调用 → FP
        unmatched_actual = [
            act.name for idx, act in enumerate(actual) if not used[idx]
        ]
        return details, unmatched_actual, unmatched_expected

    @staticmethod
    def _safe_div(numerator: float, denominator: float) -> float:
        """分母为 0 时返回 0.0，避免 ZeroDivisionError。"""
        if denominator == 0:
            return 0.0
        return numerator / denominator

    def evaluate(
        self,
        expected_tools: list[ExpectedToolCall],
        trace: EvalTrace,
    ) -> ToolExecutionResult:
        """
        单条 Golden Case 工具调用评测。

        Parameters
        ----------
        expected_tools:
            Golden Case 中的期望工具调用列表。
        trace:
            Agent 实际运行轨迹。

        Returns
        -------
        ToolExecutionResult
            含 P/R/F1、param_accuracy 与匹配明细。
        """
        # 步骤 1：Multiset 匹配
        details, unmatched_actual, unmatched_expected = self._match_by_name(
            expected_tools, trace.tool_calls
        )

        # 步骤 2：混淆矩阵
        tp = sum(1 for d in details if d.name_matched)
        fp = len(unmatched_actual)
        fn = len(unmatched_expected)

        # 步骤 3：P / R / F1
        precision = self._safe_div(tp, tp + fp)
        recall = self._safe_div(tp, tp + fn)
        f1 = self._safe_div(2 * precision * recall, precision + recall)

        # 步骤 4：参数准确率（仅统计 name 已匹配的对）
        name_matched = [d for d in details if d.name_matched]
        if name_matched:
            param_accuracy = sum(1 for d in name_matched if d.param_matched) / len(
                name_matched
            )
        else:
            param_accuracy = 0.0

        return ToolExecutionResult(
            test_case_id=trace.test_case_id,
            precision=round(precision, 4),
            recall=round(recall, 4),
            f1=round(f1, 4),
            param_accuracy=round(param_accuracy, 4),
            true_positives=tp,
            false_positives=fp,
            false_negatives=fn,
            matched_details=details,
            unmatched_actual=unmatched_actual,
            unmatched_expected=unmatched_expected,
        )

    def evaluate_batch(
        self,
        pairs: list[tuple[list[ExpectedToolCall], EvalTrace]],
    ) -> ToolExecutionBatchResult:
        """
        批量评测并计算均值指标。

        Parameters
        ----------
        pairs:
            (expected_tools, trace) 列表。

        Returns
        -------
        ToolExecutionBatchResult
            含各 Case 明细与均值。
        """
        if not pairs:
            return ToolExecutionBatchResult(
                case_count=0,
                mean_precision=0.0,
                mean_recall=0.0,
                mean_f1=0.0,
                mean_param_accuracy=0.0,
                cases=[],
            )

        cases = [self.evaluate(expected, trace) for expected, trace in pairs]
        n = len(cases)
        return ToolExecutionBatchResult(
            case_count=n,
            mean_precision=round(sum(c.precision for c in cases) / n, 4),
            mean_recall=round(sum(c.recall for c in cases) / n, 4),
            mean_f1=round(sum(c.f1 for c in cases) / n, 4),
            mean_param_accuracy=round(sum(c.param_accuracy for c in cases) / n, 4),
            cases=cases,
        )

    def print_result_table(
        self,
        results: list[ToolExecutionResult],
        title: str = "Tool Execution Eval",
    ) -> None:
        """终端表格输出单 Case 与汇总指标。"""
        print("\n" + "─" * 88)
        print(f" {title}")
        print("─" * 88)
        print(
            f"{'Case ID':<16} {'P':>6} {'R':>6} {'F1':>6} "
            f"{'Param':>6} {'TP':>4} {'FP':>4} {'FN':>4}  Errors"
        )
        print("─" * 88)
        for r in results:
            # 汇总本 Case 的首条参数误差（便于快速定位）
            err_preview = ""
            for d in r.matched_details:
                if d.param_errors and d.param_errors != ["tool not called"]:
                    err_preview = d.param_errors[0][:28]
                    break
            if not err_preview and r.unmatched_expected:
                err_preview = f"missing:{r.unmatched_expected[0]}"
            elif not err_preview and r.unmatched_actual:
                err_preview = f"extra:{r.unmatched_actual[0]}"

            print(
                f"{r.test_case_id:<16} {r.precision:>6.2f} {r.recall:>6.2f} "
                f"{r.f1:>6.2f} {r.param_accuracy:>6.2f} "
                f"{r.true_positives:>4} {r.false_positives:>4} {r.false_negatives:>4}  "
                f"{err_preview}"
            )
        print("─" * 88)


# ═══════════════════════════════════════════════════════════════════════════
# Mock Trace 场景工厂
# ═══════════════════════════════════════════════════════════════════════════

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


def build_demo_scenarios() -> list[tuple[str, list[ExpectedToolCall], EvalTrace, dict[str, float]]]:
    """
    构造四类验证场景及期望断言阈值。

    Returns
    -------
    list
        (场景标签, expected, trace, 期望指标字典)
    """
    perfect = EvalTrace(
        test_case_id="research_001",
        query="对比 ESM-2 与 ProteinBERT 在二级结构预测中的表现",
        tool_calls=[
            ToolCallRecord(
                name="rag_search",
                args={"query": "ESM-2 ProteinBERT", "top_k": 30},
            ),
            ToolCallRecord(
                name="retrieve_memory",
                args={"user_id": "researcher_001"},
            ),
        ],
        final_answer="ESM-2 在 remote homology 上更优，ProteinBERT 在 GO 注释任务更强。",
    )
    missing = EvalTrace(
        test_case_id="research_002",
        query="对比 ESM-2 与 ProteinBERT 在二级结构预测中的表现",
        tool_calls=[
            ToolCallRecord(
                name="rag_search",
                args={"query": "ESM-2 ProteinBERT", "top_k": 30},
            ),
        ],
        final_answer="仅完成检索，未注入 Memory 偏好。",
    )
    extra = EvalTrace(
        test_case_id="research_003",
        query="对比 ESM-2 与 ProteinBERT 在二级结构预测中的表现",
        tool_calls=[
            ToolCallRecord(
                name="rag_search",
                args={"query": "ESM-2 ProteinBERT", "top_k": 30},
            ),
            ToolCallRecord(
                name="retrieve_memory",
                args={"user_id": "researcher_001"},
            ),
            ToolCallRecord(
                name="model_router",
                args={"prefer": "fast"},
            ),
        ],
        final_answer="多余调用了 model_router。",
    )
    bad_param = EvalTrace(
        test_case_id="research_004",
        query="对比 ESM-2 与 ProteinBERT 在二级结构预测中的表现",
        tool_calls=[
            ToolCallRecord(
                name="rag_search",
                args={"query": "ESM-2 ProteinBERT", "top_k": 5},
            ),
            ToolCallRecord(
                name="retrieve_memory",
                args={"user_id": "researcher_001"},
            ),
        ],
        final_answer="top_k 传错导致召回不足。",
    )

    return [
        ("完美匹配", DEMO_EXPECTED, perfect, {
            "precision": 1.0, "recall": 1.0, "f1": 1.0, "param_accuracy": 1.0,
        }),
        ("漏调工具", DEMO_EXPECTED, missing, {
            "precision": 1.0, "recall": 0.5, "f1": 0.6667, "param_accuracy": 1.0,
        }),
        ("多余调用", DEMO_EXPECTED, extra, {
            "precision": 0.6667, "recall": 1.0, "f1": 0.8, "param_accuracy": 1.0,
        }),
        ("参数错误", DEMO_EXPECTED, bad_param, {
            "precision": 1.0, "recall": 1.0, "f1": 1.0, "param_accuracy": 0.5,
        }),
    ]


def _assert_close(actual: float, expected: float, tol: float = 1e-3) -> bool:
    return abs(actual - expected) <= tol


# ═══════════════════════════════════════════════════════════════════════════
# 标准答案调试主入口
# ═══════════════════════════════════════════════════════════════════════════

def main() -> None:
    print("=" * 70)
    print("🔬 Day 101 标准答案: ToolExecutionEvaluator 工具调用评测引擎")
    print("=" * 70)

    evaluator = ToolExecutionEvaluator()
    scenarios = build_demo_scenarios()

    pairs: list[tuple[list[ExpectedToolCall], EvalTrace]] = []
    all_pass = True

    for label, expected, trace, thresholds in scenarios:
        result = evaluator.evaluate(expected, trace)
        pairs.append((expected, trace))

        checks = {
            "P": _assert_close(result.precision, thresholds["precision"]),
            "R": _assert_close(result.recall, thresholds["recall"]),
            "F1": _assert_close(result.f1, thresholds["f1"]),
            "Param": _assert_close(result.param_accuracy, thresholds["param_accuracy"]),
        }
        status = "✅" if all(checks.values()) else "❌"
        if not all(checks.values()):
            all_pass = False

        print(
            f"\n{status} [{label}] {trace.test_case_id}  "
            f"P={result.precision:.4f} R={result.recall:.4f} "
            f"F1={result.f1:.4f} param={result.param_accuracy:.4f}  "
            f"TP={result.true_positives} FP={result.false_positives} FN={result.false_negatives}"
        )
        for d in result.matched_details:
            if d.param_errors:
                print(f"     · {d.expected_name}: {'; '.join(d.param_errors)}")
        if result.unmatched_actual:
            print(f"     · unmatched_actual: {result.unmatched_actual}")
        if result.unmatched_expected:
            print(f"     · unmatched_expected: {result.unmatched_expected}")

    batch = evaluator.evaluate_batch(pairs)
    evaluator.print_result_table(batch.cases, title="Day 101 Tool Execution Batch Results")

    print(
        f"\n📊 批量均值: P={batch.mean_precision:.4f}  R={batch.mean_recall:.4f}  "
        f"F1={batch.mean_f1:.4f}  Param={batch.mean_param_accuracy:.4f}"
    )
    print(
        f"\n📊 过关验证: "
        f"{'✅ 四类场景指标全部符合预期' if all_pass else '❌ 存在场景断言失败，请检查匹配逻辑'}"
    )


if __name__ == "__main__":
    main()
