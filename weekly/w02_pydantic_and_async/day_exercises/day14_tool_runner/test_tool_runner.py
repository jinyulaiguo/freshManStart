import asyncio
import time
import pytest
from typing import List
from weekly.w02_pydantic_and_async.day_exercises.day14_tool_runner.practice import (
    AsyncToolRunner,
    CalculatorArgs,
    WeatherArgs,
    ToolExecuteError,
    BaseCallback,
    RunnerState
)

# Mock 异步工具函数
async def mock_calculator(args: CalculatorArgs) -> float:
    if args.operator == '+': return args.x + args.y
    elif args.operator == '-': return args.x - args.y
    elif args.operator == '*': return args.x * args.y
    elif args.operator == '/':
        if args.y == 0:
            raise ZeroDivisionError("division by zero")
        return args.x / args.y
    return 0.0

async def mock_weather(args: WeatherArgs) -> str:
    # 模拟网络延迟
    await asyncio.sleep(0.5)
    return f"Weather in {args.city} from {args.start_date} to {args.end_date}: Sunny"


# Mock 回调类记录触发历史
class MockCallback(BaseCallback):
    def __init__(self):
        self.starts = []
        self.successes = []
        self.errors = []

    def on_tool_start(self, tool_name: str, raw_args: str) -> None:
        self.starts.append((tool_name, raw_args))

    def on_tool_success(self, tool_name: str, result: str) -> None:
        self.successes.append((tool_name, result))

    def on_tool_error(self, tool_name: str, error: Exception) -> None:
        self.errors.append((tool_name, error))


# ==========================================
# 1. 测试工具注册与 Schema 导出
# ==========================================
def test_tool_registration_and_schema():
    runner = AsyncToolRunner()
    runner.register_tool("calculator", CalculatorArgs, mock_calculator)
    runner.register_tool("weather", WeatherArgs, mock_weather)
    
    schemas = runner.get_tool_schemas()
    assert "calculator" in schemas
    assert "weather" in schemas
    
    # 验证 Calculator Schema 中字段描述与限制
    calc_schema = schemas["calculator"]
    assert "properties" in calc_schema
    assert "x" in calc_schema["properties"]
    assert "operator" in calc_schema["properties"]


# ==========================================
# 2. 测试参数校验与异常网关
# ==========================================
@pytest.mark.asyncio
async def test_calculator_validation():
    runner = AsyncToolRunner()
    runner.register_tool("calculator", CalculatorArgs, mock_calculator)
    
    # 正常请求
    res = await runner.run_tool("calculator", '{"x": 10, "y": 5, "operator": "/"}')
    assert float(res) == 2.0
    
    # 脏输入校验 (运算符不合规)
    with pytest.raises(ToolExecuteError) as excinfo:
        await runner.run_tool("calculator", '{"x": 10, "y": 5, "operator": "%"}')
    
    # 验证底层原因为 Pydantic ValidationError
    assert excinfo.value.__cause__ is not None
    
    # 验证状态步骤变化
    assert runner.state["steps"] == 2
    assert runner.state["tool_name"] == "calculator"


@pytest.mark.asyncio
async def test_weather_validation():
    runner = AsyncToolRunner()
    runner.register_tool("weather", WeatherArgs, mock_weather)
    
    # 正常日期区间请求
    res = await runner.run_tool("weather", '{"city": "Beijing", "start_date": "2026-06-01", "end_date": "2026-06-03"}')
    assert "Beijing" in res
    
    # 日期逆序校验拦截 (联合模型级校验)
    with pytest.raises(ToolExecuteError) as excinfo:
        await runner.run_tool("weather", '{"city": "Beijing", "start_date": "2026-06-10", "end_date": "2026-06-01"}')
    assert excinfo.value.__cause__ is not None


# ==========================================
# 3. 测试高吞吐异步并发调度
# ==========================================
@pytest.mark.asyncio
async def test_async_concurrent_speed():
    runner = AsyncToolRunner()
    runner.register_tool("weather", WeatherArgs, mock_weather)
    
    requests = [
        {"name": "weather", "args": '{"city": "Beijing", "start_date": "2026-06-01", "end_date": "2026-06-02"}'},
        {"name": "weather", "args": '{"city": "Shanghai", "start_date": "2026-06-01", "end_date": "2026-06-02"}'},
        {"name": "weather", "args": '{"city": "Guangzhou", "start_date": "2026-06-01", "end_date": "2026-06-02"}'}
    ]
    
    start_time = time.time()
    # 并发派发 3 个有 0.5s 网络延迟的工具
    results = await runner.run_concurrent_tools(requests)
    end_time = time.time()
    
    # 并发耗时应在 0.5 ~ 0.8s 之间（小于串行的 1.5s）
    duration = end_time - start_time
    assert duration < 1.0, f"并发执行太慢，耗时: {duration:.2f}s"
    assert len(results) == 3
    assert "Beijing" in results[0]
    assert "Shanghai" in results[1]


# ==========================================
# 4. 测试生命周期回调与异常链
# ==========================================
@pytest.mark.asyncio
async def test_callbacks_and_error_chaining():
    callback = MockCallback()
    runner = AsyncToolRunner(callback=callback)
    runner.register_tool("calculator", CalculatorArgs, mock_calculator)
    
    # 成功执行
    await runner.run_tool("calculator", '{"x": 2, "y": 3, "operator": "*"}')
    assert len(callback.starts) == 1
    assert callback.starts[0][0] == "calculator"
    assert len(callback.successes) == 1
    assert callback.successes[0][0] == "calculator"
    assert callback.successes[0][1] == "6.0"
    
    # 失败执行 (被除数为0引发底层运行时崩溃)
    with pytest.raises(ToolExecuteError) as excinfo:
        await runner.run_tool("calculator", '{"x": 10, "y": 0, "operator": "/"}')
    
    # 确认异常链因果
    assert isinstance(excinfo.value.__cause__, ZeroDivisionError)
    
    # 确认触发错误回调
    assert len(callback.errors) == 1
    assert callback.errors[0][0] == "calculator"
    assert isinstance(callback.errors[0][1], ToolExecuteError)
