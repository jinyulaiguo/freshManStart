"""
OpsChat CLI - 动态高可用降级控制器 (fallback_controller.py)

=========================================
设计方案说明
=========================================
1. 设计意图：
   高可用多模型调度机制。在云服务不可靠（偶发宕机、限流、网络延迟）的约束下，
   首选高性能/低成本模型（如 MiniMax），并配置 500ms 的首字延迟 (TTFT) 监控墙。
   若首选客户端超时无响应、断网或返回 50x 服务端错误，自动且静默地切换到备用大模型（如 DeepSeek/OpenAI），
   以保证 SRE 终端用户的高可用无缝交互体验。

2. 类与函数结构：
   - FallbackController:
     - __init__(clients: List[StreamingLLMClient], timeout: float = 0.5):
       传入具有优先级顺序的客户端适配器列表。
     - stream(messages, temperature, max_tokens, **kwargs) -> AsyncGenerator[StreamChunk, None]:
       核心生成方法，内部通过 asyncio.wait_for 监测首字响应。
     - last_active_model: str, 记录本次请求最终成功响应的模型名称。
     - last_is_fallback: bool, 记录本次请求是否触发了降级。
     - last_metrics: StreamMetrics, 最终响应模型的度量统计。

3. 关键数据流流向：
   `调用 stream` -> `遍历 clients 队列`
   -> `调用当前 client.stream_generate` -> `asyncio.wait_for(..., timeout=0.5) 等待首个 chunk`
   -> `正常接收首字: 标识 active_model，yield 首字并循环 yield 剩余 chunks` -> `结束`
   -> `超时或捕获到网络异常/50x 异常` -> `打印 Warning 日志`
   -> `静默切换至 clients 中的下一个适配器重新尝试`
   -> `全败: 抛出 LLMError("All clients failed")`
=========================================
"""

import asyncio
from typing import List, Dict, Any, Optional, AsyncGenerator
import time

from weekly.w03_llm_and_api.project.models import StreamChunk, StreamMetrics
from weekly.w03_llm_and_api.project.exceptions import LLMError, LLMAPIError, LLMConnectionError
from weekly.w03_llm_and_api.project.protocols import StreamingLLMClient


class FallbackController:
    """
    高可用大模型流式调度降级控制器。
    """
    def __init__(self, clients: List[StreamingLLMClient], timeout: float = 0.5):
        if not clients:
            raise ValueError("FallbackController requires at least one client.")
        self.clients: List[StreamingLLMClient] = clients
        self.timeout: float = timeout
        self.last_active_model: Optional[str] = None
        self.last_is_fallback: bool = False
        self.last_metrics: Optional[StreamMetrics] = None

    async def stream(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        **kwargs: Any
    ) -> AsyncGenerator[StreamChunk, None]:
        """
        高可用流式生成。按顺序尝试客户端列表。
        当遇到首字超时（500ms）、网络异常或 50x 服务错误时，自动静默降级切换到下一个客户端。
        """
        self.last_active_model = None
        self.last_is_fallback = False
        self.last_metrics = None
        
        last_error = None

        for index, client in enumerate(self.clients):
            is_primary = (index == 0)
            try:
                # 获取该客户端的流式生成器
                generator = client.stream_generate(
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs
                )

                # 使用 asyncio.wait_for 等待第一个 StreamChunk 的产生，以监控首字延迟 (TTFT)
                # anext() 或者是 generator.__anext__() 用于获取异步生成器的下一项
                try:
                    first_chunk = await asyncio.wait_for(
                        generator.__anext__(),
                        timeout=self.timeout
                    )
                except asyncio.TimeoutError as e:
                    # 捕获首字超时
                    raise LLMConnectionError(
                        f"First token timeout after {self.timeout}s on {client.__class__.__name__}"
                    ) from e

                # 成功在 500ms 内获取到首字！
                self.last_active_model = client.model_name
                self.last_is_fallback = not is_primary
                
                # yield 首个 chunk
                yield first_chunk

                # 接着迭代产生该生成器的剩余所有 chunk
                async for chunk in generator:
                    yield chunk

                # 当生成结束后，从当前 client 读取度量指标并存入控制器状态
                if hasattr(client, "last_metrics"):
                    self.last_metrics = getattr(client, "last_metrics")
                
                # 成功消费完整个流，退出客户端遍历循环
                return

            except (LLMConnectionError, LLMAPIError) as e:
                # 如果是 API 错误，判断是否为 50x 服务错误（4xx 客户端错误不触发降级）
                if isinstance(e, LLMAPIError) and e.status_code < 500:
                    # 4xx 客户端错误（如参数错误、认证失败）直接向上抛出，不进行降级
                    raise e

                last_error = e
                # 记录警告日志并触发降级
                print(f"\n[Warning] Client {client.__class__.__name__} ({client.model_name}) "
                      f"failed/timeout: {e}. Fallbacking to next client...")
                continue
            except Exception as e:
                # 其它未知非 LLMError 异常也作为连接/运行异常处理降级
                last_error = e
                print(f"\n[Warning] Client {client.__class__.__name__} ({client.model_name}) "
                      f"raised unexpected exception: {e}. Fallbacking...")
                continue

        # 链条中所有客户端都尝试过但全部失败
        raise LLMError(f"All registered LLM clients failed. Last error: {last_error}")
