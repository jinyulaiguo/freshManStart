"""
OpsChat CLI - MiniMax 流式大模型适配器 (minimax_stream_adapter.py)

=========================================
设计方案说明
=========================================
1. 设计意图：
   实现 StreamingLLMClient 契约，专用于通过异步非阻塞网络 I/O 访问 MiniMax 流式 API。
   当 API 请求发生网络故障、连接超时或服务端错误时，统一转化为适配层标准异常。
   提供内部度量以记录流生成过程中的首字延迟 (TTFT) 和吞吐速率 (TPS)。

2. 类与函数结构：
   - MiniMaxStreamAdapter (StreamingLLMClient):
     - model_name: 绑定的模型名称 (默认: MiniMax-M3)。
     - stream_generate(messages, temperature, max_tokens, **kwargs): 核心流式生成方法。
     - last_metrics: 记录最近一次流式请求的度量指标 (StreamMetrics)。

3. 关键数据流流向：
   `调用 stream_generate` -> `判定是否为 Mock 模式`
   -> `是: 调用 _mock_stream`
   -> `否: 构造 HTTP headers/payload` -> `使用 httpx.AsyncClient.stream 发起 SSE 请求`
   -> `迭代 aiter_lines() 读取 SSE data` -> `解析 JSON 提取 delta 文本`
   -> `第一个有效字符到达时计算 TTFT` -> `逐个 yield StreamChunk`
   -> `请求结束时计算总耗时、总 Token 数与 TPS，组装为 StreamMetrics`
=========================================
"""

import os
import time
import json
import asyncio
from typing import List, Dict, Any, Optional, AsyncGenerator
import httpx

from weekly.w03_llm_and_api.project.models import StreamChunk, StreamMetrics
from weekly.w03_llm_and_api.project.exceptions import LLMError, LLMAPIError, LLMConnectionError
from weekly.w03_llm_and_api.project.protocols import StreamingLLMClient


class MiniMaxStreamAdapter:
    """
    MiniMax 流式大模型适配器，实现 StreamingLLMClient 接口。
    """
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model_name: Optional[str] = None
    ):
        self.api_key: str = api_key or os.getenv("MINIMAX_API_KEY", "")
        self.base_url: str = base_url or os.getenv("MINIMAX_BASE_URL") or "https://api.minimax.chat/v1"
        self.model_name: str = model_name or os.getenv("MINIMAX_MODEL") or "MiniMax-M3"
        self.last_metrics: Optional[StreamMetrics] = None
        self.mock_error: Optional[str] = None
        self.mock_delay: float = 0.1

    async def stream_generate(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        **kwargs: Any
    ) -> AsyncGenerator[StreamChunk, None]:
        """
        通过异步非阻塞网络 I/O 流式访问 MiniMax 大模型。
        """
        self.last_metrics = None
        start_time = time.perf_counter()

        # 判定是否启用 Mock 模式，利于单元测试
        if self.api_key == "mock" or not self.api_key:
            async for chunk in self._mock_stream(start_time, messages, **kwargs):
                yield chunk
            return

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

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
        timeout_policy = httpx.Timeout(timeout=30.0, read=10.0, connect=5.0)

        try:
            async with httpx.AsyncClient(timeout=timeout_policy) as client:
                async with client.stream("POST", f"{self.base_url}/chat/completions", headers=headers, json=payload) as response:
                    # 检查 HTTP 状态码
                    if response.status_code != 200:
                        error_body = await response.aread()
                        raise LLMAPIError(
                            status_code=response.status_code,
                            message=error_body.decode("utf-8", errors="ignore")
                        )

                    async for line in response.aiter_lines():
                        line = line.strip()
                        if not line:
                            continue

                        if line.startswith("data:"):
                            data_str = line[5:].strip()
                            if data_str == "[DONE]":
                                break

                            try:
                                data_json = json.loads(data_str)
                                choices = data_json.get("choices", [])
                                if not choices:
                                    continue

                                delta = choices[0].get("delta", {})
                                content = delta.get("content", "")
                                finish_reason = choices[0].get("finish_reason")

                                if content or finish_reason:
                                    if content:
                                        token_count += 1
                                        if ttft_time is None:
                                            # 计算首字延迟 (TTFT)
                                            ttft_time = (time.perf_counter() - start_time) * 1000

                                    yield StreamChunk(
                                        content=content,
                                        model_name=data_json.get("model", self.model_name),
                                        finish_reason=finish_reason
                                    )
                            except json.JSONDecodeError:
                                # 丢弃损坏的分块，保持健壮
                                continue

        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as e:
            raise LLMConnectionError(f"Network timeout/connection error: {str(e)}") from e
        except LLMError:
            raise
        except Exception as e:
            raise LLMError(f"Unexpected error in MiniMaxStreamAdapter: {str(e)}") from e

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
        text = f"[Mock MiniMax Response] Found anomalies in logs."
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
