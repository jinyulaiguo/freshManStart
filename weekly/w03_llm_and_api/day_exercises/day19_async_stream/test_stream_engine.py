"""
Day 19: 异步非阻塞 API 并发调用与流式分块解析引擎 - 单元测试

=========================================
设计方案说明
=========================================
1. 设计意图：
   通过自动化单元测试验证 `AsyncStreamEngine` 的流式数据解析功能。
   测试覆盖 Mock 仿真引擎、基于 `unittest.mock` 对 `httpx` SSE 传输协议的手动拦截与切片重组测试，
   以及在网络超时、供应商服务端异常（50x）等边缘坏路径下的防错机制与异常包装正确性。

2. 类与函数结构：
   - `TestStreamEngine` (unittest.IsolatedAsyncioTestCase):
     - `test_mock_stream_flow`: 验证 Mock 模式下生成流文本拼接与 StreamMetrics 指标计算的正确性。
     - `test_real_flow_sse_parsing`: 模拟 httpx 网络流，输入标准 SSE 文本，断言其能正确拼装和逐个 yield。
     - `test_http_status_error_handling`: 模拟服务端返回 500 时，引擎能正确抓取并抛出 StreamEngineAPIError。
     - `test_network_connection_timeout`: 模拟 httpx 抛出连接超时，引擎包装为 StreamEngineConnectionError 并向上传递。

3. 关键数据流流向：
   `启动 pytest` -> `加载测试套件` -> `调用 unittest 异步测试用例`
   -> `注入模拟的 httpx.Response 字节流` -> `执行被测方法 send_stream_request`
   -> `逐帧提取 StreamChunk 并拼接文本` -> `验证 metrics 指标范围（TTFT 等）`
   -> `断言边界异常与包装链`
=========================================
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import json

# 引入被测试模块
from weekly.w03_llm_and_api.day_exercises.day19_async_stream.stream_engine import (
    AsyncStreamEngine,
    StreamChunk,
    StreamMetrics,
    StreamEngineError,
    StreamEngineAPIError,
    StreamEngineConnectionError
)


class TestStreamEngine(unittest.IsolatedAsyncioTestCase):
    """
    流式分块解析引擎与性能可观测指标单元测试
    """
    def setUp(self):
        self.test_messages = [
            {"role": "user", "content": "Explain async I/O in 1 sentence."}
        ]

    async def test_mock_stream_flow(self):
        """
        验证引擎在 Mock 模式下的基本生成功能及指标度量的合理性
        """
        # 未传入 API 密钥，引擎自动退化为 Mock 模式
        engine = AsyncStreamEngine(api_key="")
        self.assertTrue(engine.is_mock)
        
        chunks = []
        async for chunk in engine.send_stream_request(messages=self.test_messages):
            self.assertIsInstance(chunk, StreamChunk)
            self.assertIsNotNone(chunk.content)
            chunks.append(chunk.content)
            
        full_text = "".join(chunks)
        self.assertTrue(full_text.startswith("[Mock Stream Response"))
        
        metrics = engine.get_last_metrics()
        self.assertIsNotNone(metrics)
        self.assertIsInstance(metrics, StreamMetrics)
        
        # 验证指标数据的数学合理性
        self.assertGreater(metrics.ttft_ms, 0)
        self.assertGreater(metrics.total_time_ms, metrics.ttft_ms)
        self.assertGreater(metrics.total_tokens, 0)
        self.assertGreater(metrics.tokens_per_sec, 0)

    @patch("httpx.AsyncClient.stream")
    async def test_real_flow_sse_parsing(self, mock_stream):
        """
        模拟真实的 HTTP SSE 分块传输，测试引擎对 data: {...} 的纯文本行流式解析的正确性
        """
        # 1. 模拟 SSE 行列表
        sse_lines = [
            b"data: " + json.dumps({"choices": [{"delta": {"content": "Hello"}}], "model": "abab6.5-chat"}).encode("utf-8"),
            b"",
            b"data: " + json.dumps({"choices": [{"delta": {"content": " world"}}], "model": "abab6.5-chat"}).encode("utf-8"),
            b"data: " + json.dumps({"choices": [{"delta": {}, "finish_reason": "stop"}], "model": "abab6.5-chat"}).encode("utf-8"),
            b"data: [DONE]"
        ]
        
        # 2. 模拟 httpx.Response
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        
        # 模拟 response.aiter_lines() 异步迭代器
        async def mock_aiter_lines():
            for line in sse_lines:
                yield line.decode("utf-8")
                
        mock_response.aiter_lines = mock_aiter_lines
        
        # 3. 模拟 httpx.AsyncClient.stream 上下文管理器
        mock_context = MagicMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_response)
        mock_context.__aexit__ = AsyncMock(return_value=False)
        mock_stream.return_value = mock_context
        
        # 4. 执行被测方法并断言
        engine = AsyncStreamEngine(api_key="real_key_simulated", model="abab6.5-chat")
        self.assertFalse(engine.is_mock)
        
        chunks = []
        async for chunk in engine.send_stream_request(messages=self.test_messages):
            chunks.append(chunk)
            
        # 验证解析出 3 个有效 chunk (Hello +  world + stop)
        self.assertEqual(len(chunks), 3)
        self.assertEqual(chunks[0].content, "Hello")
        self.assertEqual(chunks[1].content, " world")
        self.assertEqual(chunks[2].finish_reason, "stop")
        
        # 验证指标被正确收集
        metrics = engine.get_last_metrics()
        self.assertIsNotNone(metrics)
        self.assertEqual(metrics.total_tokens, 2)  # 2 个有 content 的 chunk

    @patch("httpx.AsyncClient.stream")
    async def test_http_status_error_handling(self, mock_stream):
        """
        验证当服务端返回 500 内部错误时，引擎正确将其识别为 StreamEngineAPIError 并包装抛出
        """
        # 模拟返回非 200 响应
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 500
        mock_response.aread = AsyncMock(return_value=b"Internal Server Error")
        
        mock_context = MagicMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_response)
        mock_context.__aexit__ = AsyncMock(return_value=False)
        mock_stream.return_value = mock_context
        
        engine = AsyncStreamEngine(api_key="real_key_simulated")
        
        with self.assertRaises(StreamEngineAPIError) as context:
            async for _ in engine.send_stream_request(messages=self.test_messages):
                pass
                
        self.assertEqual(context.exception.status_code, 500)
        self.assertIn("Internal Server Error", str(context.exception))

    @patch("httpx.AsyncClient.stream")
    async def test_network_connection_timeout(self, mock_stream):
        """
        验证当 httpx 发生连接或读取超时异常时，引擎能将其安全抓取并转换为统一的 StreamEngineConnectionError
        """
        # 强制抛出 ConnectTimeout 异常
        mock_context = MagicMock()
        mock_context.__aenter__ = AsyncMock(side_effect=httpx.ConnectTimeout("Connect timed out"))
        mock_context.__aexit__ = AsyncMock(return_value=False)
        mock_stream.return_value = mock_context
        
        engine = AsyncStreamEngine(api_key="real_key_simulated")
        
        with self.assertRaises(StreamEngineConnectionError):
            async for _ in engine.send_stream_request(messages=self.test_messages):
                pass


if __name__ == "__main__":
    unittest.main()
