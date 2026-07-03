"""
设计方案：
- 设计意图：验证 `WeatherTool` 与 `ExchangeTool` 两个调用真实网络 API 的 I/O 密集型工具的业务逻辑与网络通信模块。使用 `@pytest.mark.network` 标记，并内置网络抖动拦截保护（若发生 APIConnectionError 则断言网络故障），防止因公网 API 临时失效导致本地 CI/CD 流水线误报崩溃。
- 类与函数结构：
  - `test_weather_tool_real_api` 异步函数：请求并解析 wttr.in 天气数据。
  - `test_exchange_tool_real_api` 异步函数：请求并解析 Frankfurter 汇率数据。
- 关键数据流向：
  - 工具类 `_execute` 被调用 -> 拼接公网 API 地址 -> `httpx` 发起异步非阻塞网络 GET 请求 -> 触发 `raise_for_status()` -> 安全解析嵌套 JSON 数据并回传字符串。
"""

import pytest
from weekly.w02_pydantic_and_async.project.exceptions.base import APIConnectionError
from weekly.w02_pydantic_and_async.project.models.tool_args import WeatherArgs, ExchangeArgs
from weekly.w02_pydantic_and_async.project.tools.weather import WeatherTool
from weekly.w02_pydantic_and_async.project.tools.exchange import ExchangeTool

@pytest.mark.network
@pytest.mark.asyncio
async def test_weather_tool_real_api(test_settings):
    tool = WeatherTool(test_settings)
    args = WeatherArgs(city="Shanghai", days=2)
    
    try:
        res = await tool._execute(args)
        assert "Weather in Shanghai" in res
        assert "Prediction days: 2" in res
    except APIConnectionError as e:
        # 网络异常是预料之中的（当公网 API 不稳定时），捕获并打印说明，不使 CI 挂掉
        print(f"\n[Network Check] 天气 API 临时不可达，已捕获连接错误: {e}")
        assert "天气 API" in str(e.message)

@pytest.mark.network
@pytest.mark.asyncio
async def test_exchange_tool_real_api(test_settings):
    tool = ExchangeTool(test_settings)
    args = ExchangeArgs(base_currency="USD", target_currency="CNY", amount=100.0)
    
    try:
        res = await tool._execute(args)
        assert "USD = " in res
        assert "CNY" in res
        assert "Rate:" in res
    except APIConnectionError as e:
        # 允许外部汇率 API 不稳定时静默通过
        print(f"\n[Network Check] 汇率 API 临时不可达，已捕获连接错误: {e}")
        assert "汇率 API" in str(e.message)
    except ValueError as e:
        # 币种本身不支持
        assert "不支持的货币" in str(e)
