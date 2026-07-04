"""
OpsChat CLI - OpenAI/DeepSeek 流式大模型适配器 (openai_stream_adapter.py)

=========================================
设计方案说明
=========================================
1. 设计意图：
   实现 StreamingLLMClient 契约，封装 OpenAI AsyncOpenAI SDK，用于流式请求 OpenAI 兼容接口（如 DeepSeek/GPT-4o）。
   当请求发生网络故障、API 异常时统一转换为适配层标准异常。
   追踪并计算首字延迟 (TTFT) 与吞吐速率 (TPS)。

2. 类与函数结构：
   - OpenAIStreamAdapter (StreamingLLMClient):
     - model_name: 绑定的模型名称 (默认: deepseek-chat)。
     - client: openai.AsyncOpenAI 实例 (延迟初始化)。
     - stream_generate: 流式请求接口。

3. 关键数据流流向：
   `调用 stream_generate` -> `判定是否为 Mock 模式`
   -> `是: 调用 _mock_stream`
   -> `否: 调用 AsyncOpenAI.chat.completions.create(stream=True)`
   -> `异步迭代响应流` -> `提取 content 和 finish_reason`
   -> `首字返回时计算 TTFT` -> `yield StreamChunk`
   -> `流结束时生成 StreamMetrics`
=========================================
"""

import os
import time
import asyncio
from typing import List, Dict, Any, Optional, AsyncGenerator
import openai

from weekly.w03_llm_and_api.project.models import StreamChunk, StreamMetrics
from weekly.w03_llm_and_api.project.exceptions import LLMError, LLMAPIError, LLMConnectionError
from weekly.w03_llm_and_api.project.protocols import StreamingLLMClient


class OpenAIStreamAdapter:
    """
    OpenAI 兼容的流式大模型适配器，实现 StreamingLLMClient 接口。
    """
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model_name: Optional[str] = None
    ):
        # 默认优先载入 DEEPSEEK，因为我们有真实工作密钥
        self.api_key: str = (api_key 
                             or os.getenv("DEEPSEEK_API_KEY") 
                             or os.getenv("OPENAI_API_KEY", ""))
        self.base_url: str = (base_url 
                              or os.getenv("DEEPSEEK_BASE_URL") 
                              or "https://api.deepseek.com/v1")
        self.model_name: str = model_name or "deepseek-chat"
        self.last_metrics: Optional[StreamMetrics] = None
        self.mock_error: Optional[str] = None
        self.mock_delay: float = 0.1

        if self.api_key and self.api_key != "mock":
            self.client = openai.AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)
        else:
            self.client = None

    async def stream_generate(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        **kwargs: Any
    ) -> AsyncGenerator[StreamChunk, None]:
        """
        异步流式调用 OpenAI 兼容大模型 API。
        """
        self.last_metrics = None
        start_time = time.perf_counter()

        # 判定是否启用 Mock 模式，利于单元测试
        if self.api_key == "mock" or not self.api_key:
            async for chunk in self._mock_stream(start_time, messages, **kwargs):
                yield chunk
            return

        payload = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
            **kwargs
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        ttft_time: Optional[float] = None
        token_count = 0

        try:
            response = await self.client.chat.completions.create(**payload)
            
            async for chunk in response:
                if not chunk.choices:
                    continue
                
                choice = chunk.choices[0]
                delta = choice.delta
                content = delta.content or ""
                finish_reason = choice.finish_reason

                if content or finish_reason:
                    if content:
                        token_count += 1
                        if ttft_time is None:
                            # 计算首字延迟 (TTFT)
                            ttft_time = (time.perf_counter() - start_time) * 1000

                    yield StreamChunk(
                        content=content,
                        model_name=chunk.model or self.model_name,
                        finish_reason=finish_reason
                    )

        except openai.APIConnectionError as e:
            raise LLMConnectionError(f"OpenAI/DeepSeek connection error: {str(e)}") from e
        except openai.APIStatusError as e:
            raise LLMAPIError(status_code=e.status_code, message=str(e.message)) from e
        except Exception as e:
            raise LLMError(f"Unexpected error in OpenAIStreamAdapter: {str(e)}") from e

        # 计算并更新性能度量指标
        end_time = time.perf_counter()
        total_time_ms = (end_time - start_time) * 1000
        effective_ttft = ttft_time if ttft_time is not None else total_time_ms
        decode_duration_sec = (total_time_ms - effective_ttft) / 1000.0

        tokens_per_sec = token_count / decode_duration_sec if decode_duration_sec > 0.001 else 0.0
        self.last_metrics = StreamMetrics(
            ttft_ms=effective_ttft,
            total_time_ms=total_time_ms,
            tokens_per_sec=tokens_per_sec,
            total_tokens=token_count
        )

    async def _mock_stream(
        self,
        start_time: float,
        messages: List[Dict[str, str]],
        **kwargs: Any
    ) -> AsyncGenerator[StreamChunk, None]:
        """
        用于测试的模拟流生成器。
        支持传入 mock_delay 模拟网络延迟（前导延迟），以及 mock_error 模拟网络或 API 错误。
        """
        mock_delay = kwargs.get("mock_delay", self.mock_delay)
        mock_error = kwargs.get("mock_error", self.mock_error)

        # 模拟前导连接/Prefill 延迟
        await asyncio.sleep(mock_delay)

        if mock_error:
            if mock_error == "connection":
                raise LLMConnectionError("Mocked connection failure")
            elif mock_error == "api_500":
                raise LLMAPIError(status_code=500, message="Mocked internal server error")
            elif mock_error == "api_400":
                raise LLMAPIError(status_code=400, message="Mocked bad request")
            else:
                raise LLMError(f"Mocked unexpected error: {mock_error}")

        ttft_time = (time.perf_counter() - start_time) * 1000
        text = f"[Mock OpenAI/DeepSeek Response] Switched to backup. Primary is dead."
        chunks = [text[i:i+4] for i in range(0, len(text), 4)]

        token_count = 0
        for i, chunk_text in enumerate(chunks):
            await asyncio.sleep(0.02)  # 模拟输出延迟
            token_count += 1
            is_last = i == len(chunks) - 1
            yield StreamChunk(
                content=chunk_text,
                model_name=self.model_name,
                finish_reason="stop" if is_last else None
            )

        end_time = time.perf_counter()
        total_time_ms = (end_time - start_time) * 1000
        decode_duration_sec = (total_time_ms - ttft_time) / 1000.0

        self.last_metrics = StreamMetrics(
            ttft_ms=ttft_time,
            total_time_ms=total_time_ms,
            tokens_per_sec=token_count / decode_duration_sec if decode_duration_sec > 0.001 else 0.0,
            total_tokens=token_count
        )
