"""
设计方案：
- 设计意图：全面测试 `AsyncToolRunner` 的调度控制流，验证工具调用、强校验拦截、生命周期事件触发、双层 Reducer 状态变更、异常链因果关联以及并发多任务批处理引擎的正确性。
- 类与函数结构：
  - `MockCallback` 辅助类：记录回调事件的历史，用于生命周期测试。
  - `test_runner_calculator_success` 异步函数：测试计算器正常流程。
  - `test_runner_validation_error_chaining` 异步函数：测试校验失败并验证异常因果链。
  - `test_runner_zero_division_exception` 异步函数：测试运行时除零并验证异常因果链。
  - `test_runner_unregistered_tool` 异步函数：测试未注册工具错误。
  - `test_runner_callback_trigger` 异步函数：测试生命周期回调通知触发。
  - `test_runner_state_reduction` 异步函数：测试全局状态 Reducer 增量更新。
  - `test_runner_batch_concurrency` 异步函数：测试批量异步并发调度。
- 关键数据流向：
  - 调用 `runner.run_tool` -> 更新 RunnerState 状态契约 -> 依次流经 validation -> execution -> callback -> 返回结果或上抛包装好的分层异常。
"""

import asyncio
import pytest
from pydantic import ValidationError
from weekly.w02_pydantic_and_async.project.core.runner import AsyncToolRunner
from weekly.w02_pydantic_and_async.project.exceptions.base import (
    ToolValidationError,
    ToolExecutionError,
    ToolRegistrationError,
)

class MockCallback:
    """生命周期回调模拟器，用于事件钩子断言验证"""
    def __init__(self):
        self.starts = []
        self.successes = []
        self.errors = []

    def on_tool_start(self, trace_id: str, tool_name: str, raw_args: str) -> None:
        self.starts.append((trace_id, tool_name, raw_args))

    def on_tool_success(self, trace_id: str, tool_name: str, result: str, duration: float) -> None:
        self.successes.append((trace_id, tool_name, result, duration))

    def on_tool_error(self, trace_id: str, tool_name: str, error: Exception, duration: float) -> None:
        self.errors.append((trace_id, tool_name, error, duration))

@pytest.mark.asyncio
async def test_runner_calculator_success(test_runner):
    # 测试常规四则运算
    res = await test_runner.run_tool("calculator", '{"x": 12, "y": 4, "operator": "/"}')
    assert float(res) == 3.0
    
    # 验证魔法可调用接口
    res_magic = await test_runner("calculator", '{"x": 10, "y": 5, "operator": "*"}')
    assert float(res_magic) == 50.0

@pytest.mark.asyncio
async def test_runner_validation_error_chaining(test_runner):
    # 测试脏输入引发的拦截，并断言异常链
    with pytest.raises(ToolValidationError) as exc_info:
        await test_runner.run_tool("calculator", '{"x": 12, "y": 4, "operator": "invalid"}')
    
    # 验证底层原因为 Pydantic ValidationError
    assert isinstance(exc_info.value.__cause__, ValidationError)
    assert exc_info.value.error_code == 40003
    assert exc_info.value.trace_id is not None

@pytest.mark.asyncio
async def test_runner_zero_division_exception(test_runner):
    # 测试除以零引发的运行时异常包装与因果链 raise from
    with pytest.raises(ToolExecutionError) as exc_info:
        await test_runner.run_tool("calculator", '{"x": 10, "y": 0, "operator": "/"}')
    
    # 验证底层原因为 ZeroDivisionError
    assert isinstance(exc_info.value.__cause__, ZeroDivisionError)
    assert exc_info.value.error_code == 50001
    assert "除数不能为零" in exc_info.value.message

@pytest.mark.asyncio
async def test_runner_unregistered_tool(test_runner):
    # 测试未注册工具
    with pytest.raises(ToolRegistrationError) as exc_info:
        await test_runner.run_tool("missing_tool", '{"param": 1}')
    assert exc_info.value.error_code == 40002

@pytest.mark.asyncio
async def test_runner_callback_trigger(test_settings, test_registry):
    # 注入 MockCallback
    cb = MockCallback()
    runner = AsyncToolRunner(test_settings, test_registry, callback=cb)
    
    # 成功流测试
    await runner.run_tool("calculator", '{"x": 3, "y": 4, "operator": "+"}')
    assert len(cb.starts) == 1
    assert len(cb.successes) == 1
    assert len(cb.errors) == 0
    assert cb.starts[0][1] == "calculator"
    assert cb.successes[0][2] == "7.0"
    
    # 失败流测试
    with pytest.raises(ToolValidationError):
        await runner.run_tool("calculator", '{"x": 3, "y": 4, "operator": "%"}')
    assert len(cb.starts) == 2
    assert len(cb.successes) == 1
    assert len(cb.errors) == 1
    assert cb.errors[0][1] == "calculator"
    assert isinstance(cb.errors[0][2], ToolValidationError)

@pytest.mark.asyncio
async def test_runner_state_reduction(test_runner):
    # 测试全局状态的增量归约更新 (Reducer)
    await test_runner.run_tool("calculator", '{"x": 5, "y": 5, "operator": "*"}')
    state1 = test_runner.state
    assert state1["total_steps"] == 1
    assert state1["success_count"] == 1
    assert state1["current_tool"] == "calculator"
    assert len(state1["messages"]) > 1  # 初始化消息 + 成功消息
    assert "calculator_step_1" in state1["tool_results"]
    assert state1["tool_results"]["calculator_step_1"] == "25.0"

    # 执行第二次，发生错误
    with pytest.raises(ToolValidationError):
        await test_runner.run_tool("calculator", '{"x": 5, "y": 5, "operator": "bad"}')
    
    state2 = test_runner.state
    assert state2["total_steps"] == 2
    assert state2["success_count"] == 1
    assert state2["error_count"] == 1
    assert state2["current_tool"] == "calculator"
    # 历史结果仍然存在于状态中
    assert state2["tool_results"]["calculator_step_1"] == "25.0"

@pytest.mark.asyncio
async def test_runner_batch_concurrency(test_runner):
    # 构造批量请求
    requests = [
        {"name": "calculator", "args": '{"x": 10, "y": 2, "operator": "+"}'},
        {"name": "calculator", "args": '{"x": 10, "y": 2, "operator": "-"}'},
        {"name": "calculator", "args": '{"x": 10, "y": 2, "operator": "*"}'},
        {"name": "calculator", "args": '{"x": 10, "y": 2, "operator": "/"}'},
        {"name": "calculator", "args": '{"x": 10, "y": 0, "operator": "/"}'}  # 会抛出异常
    ]
    
    # 批量并发调度
    results = await test_runner.run_batch(requests)
    
    # 验证 results
    assert len(results) == 5
    assert results[0] == "12.0"
    assert results[1] == "8.0"
    assert results[2] == "20.0"
    assert results[3] == "5.0"
    # 第五个应该返回异常实例，证明并发隔离，单工具失败不连累整个批处理
    assert isinstance(results[4], ToolExecutionError)
