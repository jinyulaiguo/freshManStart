"""
Week 15 Day 105: MockTraceRunner — 按 GoldenCase 注入完美 / 降级 EvalTrace

不调用真实 Agent，供 CI 子集、单元测试与 demo_fail 拦截演示使用。
"""

from __future__ import annotations

import copy
import os
import sys
from typing import Literal

_W15_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _W15_ROOT not in sys.path:
    sys.path.append(_W15_ROOT)

from contracts.schemas import (
    EvalTrace,
    ExpectedToolCall,
    GoldenCase,
    ToolCallRecord,
)

Scenario = Literal["default", "demo_fail"]

HALLUCINATED_SUFFIX = (
    " 另据内部未公开实验，关键指标 F1 高达 0.99，并采用了 Quantum Attention 架构，"
    "GO AUROC 达到 0.999。"
)

# demo_fail 默认污染集合：保证 limit=20 时聚合均值仍可跌破门禁
DEFAULT_FAIL_CASE_IDS = (
    "research_002",
    "research_005",
    "research_008",
    "research_011",
)


class MockTraceRunner:
    """
    根据 GoldenCase 合成 EvalTrace。

    - default: 工具调用完全匹配 expected_tools；answer=ground_truth；
      contexts 含 ground_truth 以支撑 Faithfulness。
    - demo_fail: 对指定 Case 漏调末个工具 + 注入幻觉回答。
    """

    def __init__(
        self,
        scenario: Scenario = "default",
        fail_case_id: str | None = None,
        fail_case_ids: tuple[str, ...] | list[str] | None = None,
    ):
        self.scenario = scenario
        if fail_case_ids is not None:
            self.fail_case_ids = set(fail_case_ids)
        elif fail_case_id is not None:
            self.fail_case_ids = {fail_case_id}
        else:
            self.fail_case_ids = set(DEFAULT_FAIL_CASE_IDS)

    def build_trace(self, case: GoldenCase) -> EvalTrace:
        """为单条 GoldenCase 生成 EvalTrace。"""
        if self.scenario == "demo_fail" and case.test_case_id in self.fail_case_ids:
            return self._build_regressed_trace(case)
        return self._build_perfect_trace(case)

    def build_traces(self, cases: list[GoldenCase]) -> list[EvalTrace]:
        return [self.build_trace(c) for c in cases]

    def _tool_records(
        self,
        expected: list[ExpectedToolCall],
    ) -> list[ToolCallRecord]:
        return [
            ToolCallRecord(
                name=t.name,
                args=copy.deepcopy(t.args),
                result_summary="ok",
                success=True,
            )
            for t in expected
        ]

    def _contexts_for(self, case: GoldenCase) -> list[str]:
        """用 ground_truth 作为可支撑 Context，保证完美 Trace Faithfulness 可过线。"""
        gt = case.ground_truth.strip()
        mid = max(len(gt) // 2, 1)
        return [gt[:mid], gt[mid:] if mid < len(gt) else gt]

    def _build_perfect_trace(self, case: GoldenCase) -> EvalTrace:
        return EvalTrace(
            test_case_id=case.test_case_id,
            query=case.query,
            tool_calls=self._tool_records(case.expected_tools),
            retrieved_contexts=self._contexts_for(case),
            final_answer=case.ground_truth,
            routing_decision="primary",
            token_usage={},
            errors=[],
        )

    def _build_regressed_trace(self, case: GoldenCase) -> EvalTrace:
        """漏调最后一个期望工具 + 幻觉回答 → Tool F1 / Faithfulness 双降。"""
        tools = list(case.expected_tools)
        if len(tools) > 1:
            tools = tools[:-1]
        elif tools:
            # 仅一个工具时改为空调用，制造 FN
            tools = []

        return EvalTrace(
            test_case_id=case.test_case_id,
            query=case.query,
            tool_calls=self._tool_records(tools),
            retrieved_contexts=self._contexts_for(case),
            final_answer=case.ground_truth + HALLUCINATED_SUFFIX,
            routing_decision="primary",
            token_usage={},
            errors=["injected_regression: missing_tool+hallucination"],
        )
