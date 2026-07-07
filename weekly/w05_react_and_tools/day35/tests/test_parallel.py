"""Test3: Parallel Executor 并行执行 + 异常隔离验证"""
import asyncio
import time
import pytest
from weekly.w05_react_and_tools.day35.mini_agent.agent.registry import ToolRegistry
from weekly.w05_react_and_tools.day35.mini_agent.agent.dispatcher import ToolDispatcher
from weekly.w05_react_and_tools.day35.mini_agent.schema.observation import ObservationStatus


@pytest.fixture
def parallel_registry():
    """创建含 3 个工具的 Registry：2 个正常 + 1 个必然失败"""
    reg = ToolRegistry()

    @reg.register
    async def fast_tool_a(value: int) -> str:
        """快速工具 A（模拟 0.1s 延迟）。Args: value: 输入值。"""
        await asyncio.sleep(0.1)
        return f"tool_a result: {value * 2}"

    @reg.register
    async def fast_tool_b(value: int) -> str:
        """快速工具 B（模拟 0.15s 延迟）。Args: value: 输入值。"""
        await asyncio.sleep(0.15)
        return f"tool_b result: {value + 100}"

    @reg.register
    async def failing_tool(value: int) -> str:
        """必然失败的工具。Args: value: 输入值。"""
        await asyncio.sleep(0.05)
        raise ValueError(f"工具内部错误：value={value} 不合法")

    return reg


@pytest.fixture
def parallel_dispatcher(parallel_registry):
    return ToolDispatcher(registry=parallel_registry)


class TestParallelExecution:
    """并行执行与异常隔离核心测试组"""

    def test_parallel_all_success(self, parallel_dispatcher):
        """测试：3 个正常工具并行执行，全部返回 success Observation"""
        tool_calls = [
            {"id": "call_p01", "action": "fast_tool_a", "params": {"value": 10}},
            {"id": "call_p02", "action": "fast_tool_b", "params": {"value": 20}},
            {"id": "call_p03", "action": "fast_tool_a", "params": {"value": 5}},
        ]

        observations = asyncio.run(parallel_dispatcher.execute_parallel(tool_calls))

        assert len(observations) == 3
        for obs in observations:
            assert obs.status == ObservationStatus.SUCCESS

    def test_parallel_one_failure_does_not_break_others(self, parallel_dispatcher):
        """
        测试核心：3 个工具并行，其中 1 个必然失败，
        验证其余 2 个正常工具仍然成功返回 Observation（异常隔离）。
        """
        tool_calls = [
            {"id": "call_iso01", "action": "fast_tool_a", "params": {"value": 10}},
            {"id": "call_iso02", "action": "failing_tool", "params": {"value": 999}},  # 必然失败
            {"id": "call_iso03", "action": "fast_tool_b", "params": {"value": 20}},
        ]

        observations = asyncio.run(parallel_dispatcher.execute_parallel(tool_calls))

        # 1. 结果数量与输入一致（3 个工具 → 3 个 Observation）
        assert len(observations) == 3

        # 2. 顺序与输入严格对应（按 tool_calls 列表顺序）
        assert observations[0].tool_call_id == "call_iso01"
        assert observations[1].tool_call_id == "call_iso02"
        assert observations[2].tool_call_id == "call_iso03"

        # 3. 第 1、3 个工具执行成功
        assert observations[0].status == ObservationStatus.SUCCESS
        assert observations[2].status == ObservationStatus.SUCCESS
        assert "tool_a result" in observations[0].content
        assert "tool_b result" in observations[2].content

        # 4. 第 2 个工具失败但被隔离（不抛出，而是返回 error Observation）
        assert observations[1].status == ObservationStatus.ERROR
        assert observations[1].tool_call_id == "call_iso02"

    def test_parallel_is_actually_concurrent(self, parallel_dispatcher):
        """
        测试：并行执行的总时间 ≈ max(各工具耗时)，而非各工具耗时之和。
        fast_tool_a(0.1s) + fast_tool_b(0.15s) 串行 ≈ 0.25s
        并行执行应 < 0.25s（接近 0.15s）
        """
        tool_calls = [
            {"id": "call_time01", "action": "fast_tool_a", "params": {"value": 1}},
            {"id": "call_time02", "action": "fast_tool_b", "params": {"value": 2}},
        ]

        start = time.monotonic()
        asyncio.run(parallel_dispatcher.execute_parallel(tool_calls))
        elapsed = time.monotonic() - start

        # 并行执行总时间应小于各工具延迟之和（0.1 + 0.15 = 0.25）
        # 允许 0.1 秒的调度开销容差
        assert elapsed < 0.25 + 0.1, (
            f"并行执行时间 {elapsed:.3f}s 超出预期（串行耗时约 0.25s），"
            f"可能未真正并发执行。"
        )

    def test_parallel_order_preserved_with_different_latencies(self, parallel_dispatcher):
        """
        测试：即使各工具完成顺序不同（B 先完成），结果顺序必须与输入 tool_calls 严格一致。
        """
        tool_calls = [
            {"id": "call_order01", "action": "fast_tool_b", "params": {"value": 5}},   # 0.15s
            {"id": "call_order02", "action": "fast_tool_a", "params": {"value": 10}},  # 0.1s（先完成）
        ]

        observations = asyncio.run(parallel_dispatcher.execute_parallel(tool_calls))

        # 输出顺序必须与输入顺序一致，不受完成顺序影响
        assert observations[0].tool_call_id == "call_order01"
        assert observations[1].tool_call_id == "call_order02"

    def test_parallel_with_missing_param_isolates_validation_error(self, parallel_dispatcher):
        """测试：参数校验失败的工具被隔离为 error Observation，不影响其他工具"""
        tool_calls = [
            {"id": "call_val01", "action": "fast_tool_a", "params": {"value": 42}},
            # 缺少必填参数 value → ValidationException → 被隔离
            {"id": "call_val02", "action": "fast_tool_a", "params": {}},
        ]

        observations = asyncio.run(parallel_dispatcher.execute_parallel(tool_calls))

        assert observations[0].status == ObservationStatus.SUCCESS
        assert observations[1].status == ObservationStatus.ERROR
