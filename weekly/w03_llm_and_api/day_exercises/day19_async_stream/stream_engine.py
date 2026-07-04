"""
Day 19: 异步非阻塞 API 并发调用与流式分块解析引擎 - 参考标准答案

=========================================
设计方案说明
=========================================
1. 设计意图：
   高并发场景下，同步阻塞的 LLM 调用会导致排队时延，流式响应能显著降低首字延迟（TTFT）。
   本模块通过实现一个基于非阻塞 I/O 的 `AsyncStreamEngine`，使用 `httpx.AsyncClient`
   向 Minimax 大模型 API 发送流式请求，逐行解析标准 HTTP SSE (Server-Sent Events) 数据流，
   实时通过异步迭代器（AsyncGenerator）向外推送文本块（StreamChunk），并统计吞吐性能指标（StreamMetrics）。

2. 类与函数结构：
   - `StreamChunk` (dataclass): 代表流式返回的单个文本块实体。
   - `StreamMetrics` (dataclass): 统计每次流式生成的性能指标（TTFT, TPS, 耗时, 数量）。
   - `AsyncStreamEngine` (类): 异步流式生成核心引擎。
     - `__init__`: 加载环境变量与初始化客户端。
     - `send_stream_request`: 异步生成器方法，网络流式请求并进行 SSE 解析。
     - `get_last_metrics`: 获取最近一次调用的统计指标。
   - `StreamEngineError` / `StreamEngineAPIError` / `StreamEngineConnectionError`: 统一适配异常。

3. 关键数据流流向：
   `调用 send_stream_request` -> `发起 httpx.stream("POST", ...)`
   -> `异步读取字节流或文本流 aiter_lines()`
   -> `检查 SSE 标志 "data: "` -> `解析 JSON 提取 delta 文本`
   -> `首次接收有效文本：计算并记录 TTFT`
   -> `yield StreamChunk` -> `流结束 "[DONE]" 或 HTTP 断连`
   -> `计算总耗时与平均 Token 吞吐率并存入 last_metrics`
=========================================
"""

import os
import time
import json
import asyncio
from typing import AsyncGenerator, List, Dict, Any, Optional
from dataclasses import dataclass
import httpx
from dotenv import load_dotenv

# 自动从当前目录或上层目录读取 .env 变量
load_dotenv()


# 1. 定义数据结构
@dataclass
class StreamChunk:
    content: str
    model_name: str
    finish_reason: Optional[str] = None


@dataclass
class StreamMetrics:
    ttft_ms: float         # 首字延迟 (Time to First Token)，毫秒级
    total_time_ms: float   # 整体生成耗时，毫秒级
    tokens_per_sec: float  # 平均吞吐率 (Tokens / 秒)
    total_tokens: int      # 累计生成 Token 数量


# 2. 定义标准异常
class StreamEngineError(Exception):
    """异步流式解析引擎标准异常"""
    pass


class StreamEngineAPIError(StreamEngineError):
    """大模型服务端返回非 200 状态码"""
    def __init__(self, status_code: int, message: str):
        super().__init__(f"API Error (Status {status_code}): {message}")
        self.status_code = status_code


class StreamEngineConnectionError(StreamEngineError):
    """网络连接超时或底层网络异常"""
    pass


# 3. 编写参考答案实现
class AsyncStreamEngine:
    """
    非阻塞异步流式大模型请求引擎
    """
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None
    ):
        """
        初始化引擎配置。优先使用参数传入，否则从环境变量读取：
        - API_KEY: 对应 MINIMAX_API_KEY
        - BASE_URL: 对应 MINIMAX_BASE_URL (默认: https://api.minimax.chat/v1)
        - MODEL: 对应 MINIMAX_MODEL (默认: abab6.5-chat)
        """
        self.api_key = api_key if api_key is not None else os.getenv("MINIMAX_API_KEY")
        self.base_url = base_url if base_url is not None else (os.getenv("MINIMAX_BASE_URL") or "https://api.minimax.chat/v1")
        self.model = model if model is not None else (os.getenv("MINIMAX_MODEL") or "abab6.5-chat")
        
        # 判断是否进入 Mock 模式。如果未配置有效的 API Key 或者是默认占位符，进入 Mock 模式。
        self.is_mock = not self.api_key or self.api_key in ("your_minimax_api_key_here", "")
        
        if not self.is_mock:
            # 真实运行模式，初始化时校验 api_key
            pass
        self._last_metrics: Optional[StreamMetrics] = None

    async def send_stream_request(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        **kwargs: Any
    ) -> AsyncGenerator[StreamChunk, None]:
        """
        异步非阻塞流式请求大模型。通过 async for 产出 StreamChunk，
        并在流生成结束后计算并更新 self._last_metrics 指标。
        """
        self._last_metrics = None
        start_time = time.perf_counter()
        
        # 1. 模拟模式实现（用于测试或无 API 密钥的情况）
        if self.is_mock:
            async for chunk in self._mock_stream_generator(start_time, messages):
                yield chunk
            return

        # 2. 真实网络调用实现 (Minimax / OpenAI 协议)
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
            **kwargs
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        ttft_time: Optional[float] = None
        token_count = 0
        
        # 显式配置超时策略，避免长连接发生无感知挂死
        timeout_policy = httpx.Timeout(timeout=30.0, read=10.0, connect=5.0)

        try:
            async with httpx.AsyncClient(timeout=timeout_policy) as client:
                async with client.stream("POST", f"{self.base_url}/chat/completions", headers=headers, json=payload) as response:
                    # 检查 HTTP 状态码
                    if response.status_code != 200:
                        # 尝试读取错误体
                        error_body = await response.aread()
                        raise StreamEngineAPIError(
                            status_code=response.status_code,
                            message=error_body.decode("utf-8", errors="ignore")
                        )

                    async for line in response.aiter_lines():
                        line = line.strip()
                        if not line:
                            continue
                        
                        # 解析 SSE 行
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
                                
                                # 仅对有实际内容或有结束标识的 chunk 进行 yield
                                if content or finish_reason:
                                    if content:
                                        token_count += 1
                                        if ttft_time is None:
                                            # 精确计算首字延迟 (TTFT)
                                            ttft_time = (time.perf_counter() - start_time) * 1000
                                            
                                    yield StreamChunk(
                                        content=content,
                                        model_name=data_json.get("model", self.model),
                                        finish_reason=finish_reason
                                    )
                            except json.JSONDecodeError:
                                # 健壮性设计：丢弃损坏的数据分块而不中断流式状态机
                                continue
                                
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as e:
            raise StreamEngineConnectionError(f"Network error or timeout during stream connection: {str(e)}") from e
        except StreamEngineError:
            raise
        except Exception as e:
            raise StreamEngineError(f"Unexpected error inside stream engine: {str(e)}") from e

        # 计算并更新度量指标
        end_time = time.perf_counter()
        total_time_ms = (end_time - start_time) * 1000
        
        # 吞吐量公式：token 数量除以 Decode 阶段时长 (秒)。若首字未接收成功，则总时长即为运行长时长
        effective_ttft = ttft_time if ttft_time is not None else total_time_ms
        decode_duration_sec = (total_time_ms - effective_ttft) / 1000.0
        
        # 避免除以 0 保护
        tokens_per_sec = token_count / decode_duration_sec if decode_duration_sec > 0.001 else 0.0
        
        self._last_metrics = StreamMetrics(
            ttft_ms=effective_ttft,
            total_time_ms=total_time_ms,
            tokens_per_sec=tokens_per_sec,
            total_tokens=token_count
        )

    async def _mock_stream_generator(self, start_time: float, messages: List[Dict[str, str]]) -> AsyncGenerator[StreamChunk, None]:
        """
        Mock 流式生成器，提供稳定的模拟数据与固定的网络延迟以利于无凭证或离线状态下的单元测试。
        """
        # 模拟网络握手/Prefill 延迟 150 毫秒
        await asyncio.sleep(0.15)
        ttft_time = (time.perf_counter() - start_time) * 1000
        
        simulated_text = f"[Mock Stream Response for model: {self.model}] Hello! You asked: '{messages[-1]['content'] if messages else ''}'."
        # 按空格或字分割模拟 tokens
        chunks = [simulated_text[i:i+4] for i in range(0, len(simulated_text), 4)]
        
        token_count = 0
        for i, chunk_text in enumerate(chunks):
            # 模拟单 token 产出延迟（50 毫秒 / Token）
            await asyncio.sleep(0.05)
            token_count += 1
            is_last = i == len(chunks) - 1
            yield StreamChunk(
                content=chunk_text,
                model_name=self.model,
                finish_reason="stop" if is_last else None
            )

        end_time = time.perf_counter()
        total_time_ms = (end_time - start_time) * 1000
        decode_duration_sec = (total_time_ms - ttft_time) / 1000.0
        
        self._last_metrics = StreamMetrics(
            ttft_ms=ttft_time,
            total_time_ms=total_time_ms,
            tokens_per_sec=token_count / decode_duration_sec if decode_duration_sec > 0.001 else 0.0,
            total_tokens=token_count
        )

    def get_last_metrics(self) -> Optional[StreamMetrics]:
        """
        获取最近一次请求的性能统计指标。如果从未请求过，返回 None。
        """
        return self._last_metrics


# --- 演示运行入口 ---
if __name__ == "__main__":
    async def main():
        print("==================================================")
        print("    Day 19 异步非阻塞 API 流式分块解析引擎演示    ")
        print("==================================================")
        
        # 1. 实例化引擎
        engine = AsyncStreamEngine()
        
        # 判断运行模式
        if engine.is_mock:
            print("[INFO] 当前未配置有效 MINIMAX_API_KEY，自动进入 MOCK 模式。")
        else:
            print(f"[INFO] 正在以真实模式调用 Minimax API. Base URL: {engine.base_url}")
            
        test_messages = [
            {"role": "user", "content": "请用一句话说明为什么在异步大模型编程中需要流式解析？"}
        ]
        
        print("\n--- [正在请求大模型流式输出...] ---")
        try:
            async for chunk in engine.send_stream_request(messages=test_messages, temperature=0.7):
                # 打字机式输出
                print(chunk.content, end="", flush=True)
                
            print("\n-----------------------------")
            metrics = engine.get_last_metrics()
            if metrics:
                print("\n=== [性能观测指标 (可观测性)] ===")
                print(f"首字延迟 (TTFT): {metrics.ttft_ms:.2f} 毫秒")
                print(f"总耗时: {metrics.total_time_ms:.2f} 毫秒")
                print(f"生成字符 Token 数 (估计值): {metrics.total_tokens}")
                print(f"平均吞吐率 (TPS): {metrics.tokens_per_sec:.2f} Tokens/秒")
                
        except StreamEngineError as e:
            print(f"\n[错误] 引擎捕获到异常: {e}")
        except Exception as e:
            print(f"\n[意外错误] {e}")

    asyncio.run(main())
