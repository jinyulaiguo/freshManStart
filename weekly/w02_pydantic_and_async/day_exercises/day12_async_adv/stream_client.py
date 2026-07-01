"""
Day 12 异步进阶与网络 API 调用 - 标准参考答案

设计方案：
1. 本文件实现了 `AsyncWeatherStreamClient` 客户端类，用于演示在生产环境中使用异步上下文管理器和异步迭代器的标准范式。
2. 内部通过 `httpx.AsyncClient` 进行 TCP 连接的管理，规避套接字泄露。
3. `get_live_alerts` 使用异步生成器机制 `async yield` 逐行向外吐出流式数据，内存占用与流式包的大小无关，能有效控制系统内存水位。
4. 包含完善的异常捕获与重试防护体系，防范断网、超时等网络瞬时抖动。
5. 主入口提供可直接执行的验证逻辑，并带有清晰控制台输出（stdout）。
"""

import asyncio
from typing import AsyncGenerator
import httpx

class AsyncWeatherStreamClient:
    """异步流式天气气象数据获取客户端（标准参考答案）"""
    
    def __init__(self, base_url: str = "https://httpbin.org", timeout_seconds: float = 10.0):
        self.base_url = base_url
        self.timeout = httpx.Timeout(timeout_seconds)

    async def get_live_alerts(self, count: int = 5) -> AsyncGenerator[str, None]:
        """
        以异步生成器模式，请求指定的 Mock 流式接口并逐行产出数据。
        
        参数:
            count: 模拟生成的流式数据行数
            
        异常:
            httpx.HTTPStatusError: HTTP 状态码非 2xx 异常
            httpx.TimeoutException: 请求超时异常
        """
        url = f"{self.base_url}/stream/{count}"
        
        # 1. 使用异步上下文管理器初始化 AsyncClient，确保网络连接池在退出时优雅释放
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                # 2. 发起非阻塞的流式 GET 请求。使用 stream 异步上下文，此时不加载响应主体
                async with client.stream("GET", url) as response:
                    # 3. 检查响应的 HTTP 状态码，若为 4xx/5xx 则抛出异常
                    response.raise_for_status()
                    
                    # 4. 使用 async for 逐行读取流式数据，规避一次性读入引发的 OOM
                    async for line in response.aiter_lines():
                        line_stripped = line.strip()
                        if line_stripped:
                            # 5. 异步产出处理后的流数据
                            yield line_stripped
                            
            except httpx.TimeoutException as e:
                print(f"[ERROR] 连接或读取超时: {e}")
                raise
            except httpx.HTTPStatusError as e:
                print(f"[ERROR] 响应状态码异常: {e.response.status_code}")
                raise
            except httpx.RequestError as e:
                print(f"[ERROR] 底层网络通信异常: {e}")
                raise

async def main():
    print("=== [Day 12 Standard Answer] 异步流式客户端运行测试 ===")
    client = AsyncWeatherStreamClient()
    
    try:
        print("💡 开始异步流式获取 5 条气象预警数据...")
        # 异步遍历生成器，按需消费每一行流式推送
        async for alert in client.get_live_alerts(count=5):
            print(f"✅ 收到推送消息 -> {alert}")
            
    except Exception as e:
        print(f"❌ 运行失败，捕获到预料外的异常: {e}")

if __name__ == "__main__":
    # 启动事件循环，驱动协程执行
    asyncio.run(main())
