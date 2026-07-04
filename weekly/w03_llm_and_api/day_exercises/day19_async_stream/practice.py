"""
Day 19: 异步非阻塞 API 并发调用与流式分块解析引擎 - 练习模版

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

# 自动从根目录读取 .env 变量
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


# 3. 编写异步流式解析引擎（练习模版）
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
        初始化引擎配置。若未传递参数，应尝试从环境变量中读取：
        - API_KEY: 对应 MINIMAX_API_KEY
        - BASE_URL: 对应 MINIMAX_BASE_URL (默认: https://api.minimax.chat/v1)
        - MODEL: 对应 MINIMAX_MODEL (默认: abab6.5-chat)
        """
        # TODO: 从参数或环境变量初始化配置
        raise NotImplementedError("TODO: 请完成 AsyncStreamEngine 的初始化逻辑")

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
        
        Args:
            messages: 符合 OpenAI 格式的消息体列表。
            temperature: 采样温度。
            max_tokens: 最大生成限制。
            **kwargs: 额外参数。
            
        Yields:
            StreamChunk: 包含当前分块文本及状态的实体。
            
        Raises:
            StreamEngineAPIError: 服务端返回错误。
            StreamEngineConnectionError: 连接异常或超时。
        """
        # TODO: 实现 httpx.stream 发送流式请求，逐行读取 SSE 协议，提取 content。
        # TODO: 精准计算 TTFT (首次接收到非空 content 的时刻减去请求开始时刻)。
        # TODO: 在迭代结束后计算总生成耗时和 Tokens per second 吞吐率，并存入 self._last_metrics。
        if False:
            yield StreamChunk("", "")  # 仅做语法占位，让静态检查器知道这是 Generator
        raise NotImplementedError("TODO: 请完成 send_stream_request 的流式解析和性能统计逻辑")

    def get_last_metrics(self) -> Optional[StreamMetrics]:
        """
        获取最近一次请求的性能统计指标。如果从未请求过，返回 None。
        """
        # TODO: 返回最近一次流式请求的 metrics
        raise NotImplementedError("TODO: 请完成 get_last_metrics 逻辑")


# --- 调试运行入口 ---
if __name__ == "__main__":
    async def main():
        print("=== 开始运行 Day 19 练习模版调试 ===")
        
        # 演示用的消息
        test_messages = [
            {"role": "user", "content": "Hello, explain what is SSE in 1 sentence."}
        ]
        
        engine = AsyncStreamEngine()
        
        try:
            print("尝试发起流式调用...")
            async for chunk in engine.send_stream_request(messages=test_messages):
                print(chunk.content, end="", flush=True)
                
            metrics = engine.get_last_metrics()
            if metrics:
                print(f"\n\nMetrics: TTFT={metrics.ttft_ms:.2f}ms, TPS={metrics.tokens_per_sec:.2f}tok/s")
        except NotImplementedError as e:
            print(f"\n[提示] 拦截到未实现错误: {e}")
            print("[操作提示] 请在 `stream_engine.py` 中编写您的完整实现，并将其作为标准答案测试。")
        except Exception as e:
            print(f"\n发生意外错误: {e}")

    asyncio.run(main())
