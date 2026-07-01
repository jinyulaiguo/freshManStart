"""
Day 12 异步进阶与网络 API 调用 - 练习模板

设计方案：
1. 本模板定义了一个 `AsyncWeatherStreamClient` 类，用于通过异步 HTTP 流式接口获取气象警报数据。
2. 内部依赖 `httpx.AsyncClient` 管理网络连接生命周期。
3. 利用 `async for` 异步迭代 `httpx` 响应体的字节流，并利用 `async yield` 将处理后的文本行（逐行）推送给调用方。
4. 本文件为学员练习专用，核心逻辑包含 TODO 占位与 `raise NotImplementedError`。
5. 包含一个可直接运行且有友好错误拦截调试的主入口，方便学员验证。
"""

import asyncio
from typing import AsyncGenerator
import httpx

class AsyncWeatherStreamClient:
    """异步流式天气气象数据获取客户端"""
    
    def __init__(self, base_url: str = "https://httpbin.org", timeout_seconds: float = 10.0):
        self.base_url = base_url
        self.timeout = httpx.Timeout(timeout_seconds)

    async def get_live_alerts(self, count: int = 5) -> AsyncGenerator[str, None]:
        """
        以异步生成器模式，请求指定的 Mock 流式接口并逐行产出数据。
        
        参数:
            count: 模拟生成的流式数据行数
            
        异常:
            NotImplementedError: 等待学员实现核心逻辑
            httpx.HTTPStatusError: HTTP 状态码非 2xx 异常
            httpx.TimeoutException: 请求超时异常
        """
        url = f"{self.base_url}/stream/{count}"
        # TODO: 1. 使用异步上下文管理器 `async with` 初始化 httpx.AsyncClient，传入超时参数 self.timeout
        # TODO: 2. 使用 client.stream("GET", ...) 异步发起流式请求，请求目标地址为 f"{self.base_url}/stream/{count}"
        # TODO: 3. 在流式响应上下文中，调用 response.raise_for_status() 检查 HTTP 状态码
        # TODO: 4. 使用 `async for` 遍历 response.aiter_lines() 异步按行迭代数据
        # TODO: 5. 使用 `async yield` 逐行抛出解码后的文本（并去除首尾空白字符）
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                async with client.stream("GET", url) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        line_strip = line.strip()
                        if line_strip:
                            yield line_strip
            except httpx.TimeoutException as e:
                raise httpx.TimeoutException
            except httpx.HTTPStatusError as e:
                raise httpx.HTTPStatusError
            except httpx.RequestError as e:
                raise httpx.RequestError

async def test_run():
    print("=== [Day 12] 异步流式客户端调试主入口 ===")
    client = AsyncWeatherStreamClient()
    
    try:
        print("开始向 Mock API 请求 5 条天气警报数据流...")
        async for alert_line in client.get_live_alerts(count=5):
            print(f"🎉 成功接收警报行: {alert_line}")
    except NotImplementedError as e:
        print(f"\n❌ 拦截到未实现提示: {e}")
        print("请在 practice.py 中补全 TODO 的核心实现后重新运行。")
    except Exception as e:
        print(f"\n💥 运行过程中遭遇异常: {e}")

if __name__ == "__main__":
    asyncio.run(test_run())
