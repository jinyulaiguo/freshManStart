"""
OpsChat CLI - Fallback 降级逻辑单元测试 (test_fallback.py)

=========================================
设计方案说明
=========================================
1. 设计意图：
   对 FallbackController 的高可用降级链路进行多维度测试验证。
   涵盖主客户端正常、主客户端连接异常、主客户端 API 500 异常、主客户端首字超时、
   主客户端 400 客户端错误（不应降级）以及所有客户端全崩的场景。

2. 测试类与方法结构：
   - 使用 unittest.IsolatedAsyncioTestCase 进行异步测试：
     - test_primary_success: 验证首选正常时，直接响应不触发降级。
     - test_fallback_on_connection_error: 验证首选报错 LLMConnectionError 时自动且静默降级。
     - test_fallback_on_api_500: 验证首选报错 500 时降级。
     - test_fallback_on_timeout: 验证首选首字时延超过 500ms（如 600ms）时自动超时降级。
     - test_client_400_no_fallback: 验证 400 客户端错误直接抛出不发生降级。
     - test_all_clients_fail: 验证所有客户端都报错时抛出最终 LLMError。

3. 关键数据流流向：
   `实例化 Mock 客户端` -> `配置故障注入参数 (mock_error / mock_delay)`
   -> `调用 FallbackController.stream` -> `断言捕获的 StreamChunk 序列、降级标志与活跃模型名称`
=========================================
"""

import unittest
import asyncio
from typing import List

from weekly.w03_llm_and_api.project.core.fallback_controller import FallbackController
from weekly.w03_llm_and_api.project.adapters.minimax_stream_adapter import MiniMaxStreamAdapter
from weekly.w03_llm_and_api.project.adapters.openai_stream_adapter import OpenAIStreamAdapter
from weekly.w03_llm_and_api.project.exceptions import LLMError, LLMAPIError, LLMConnectionError


class TestFallbackController(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # 初始化测试所需的适配器实例 (注入 "mock" 启用模拟数据流模式)
        self.primary = MiniMaxStreamAdapter(api_key="mock", model_name="MiniMax-M3")
        self.backup = OpenAIStreamAdapter(api_key="mock", model_name="deepseek-chat")
        # 默认 500ms 超时控制
        self.controller = FallbackController(clients=[self.primary, self.backup], timeout=0.5)

    async def test_primary_success(self):
        """
        验证首选客户端正常工作时，流式响应不触发降级。
        """
        self.primary.mock_delay = 0.1
        self.backup.mock_delay = 0.1
        
        chunks = []
        async for chunk in self.controller.stream([], temperature=0.1):
            chunks.append(chunk)

        self.assertTrue(len(chunks) > 0)
        self.assertEqual(self.controller.last_active_model, "MiniMax-M3")
        self.assertFalse(self.controller.last_is_fallback)
        self.assertIsNotNone(self.controller.last_metrics)
        self.assertEqual(self.controller.last_metrics.total_tokens, len(chunks))

    async def test_fallback_on_connection_error(self):
        """
        验证首选客户端抛出 LLMConnectionError 时，自动降级切换至备用。
        """
        self.primary.mock_error = "connection"
        self.primary.mock_delay = 0.1
        self.backup.mock_delay = 0.1
        
        chunks = []
        async for chunk in self.controller.stream([], temperature=0.1):
            chunks.append(chunk)

        self.assertTrue(len(chunks) > 0)
        self.assertIn("Switched to backup", "".join(c.content for c in chunks))
        self.assertEqual(self.controller.last_active_model, "deepseek-chat")
        self.assertTrue(self.controller.last_is_fallback)

    async def test_fallback_on_api_500(self):
        """
        验证首选客户端返回 500 服务端错误时，自动降级切换至备用。
        """
        self.primary.mock_error = "api_500"
        self.primary.mock_delay = 0.1
        self.backup.mock_delay = 0.1
        
        chunks = []
        async for chunk in self.controller.stream([], temperature=0.1):
            chunks.append(chunk)

        self.assertTrue(len(chunks) > 0)
        self.assertEqual(self.controller.last_active_model, "deepseek-chat")
        self.assertTrue(self.controller.last_is_fallback)

    async def test_fallback_on_timeout(self):
        """
        验证首选客户端首字响应超时 (超过 500ms) 时，自动断开并降级切换。
        """
        self.primary.mock_delay = 0.6  # 超过 0.5s 超时限制
        self.backup.mock_delay = 0.1
        
        chunks = []
        async for chunk in self.controller.stream([], temperature=0.1):
            chunks.append(chunk)

        self.assertTrue(len(chunks) > 0)
        self.assertEqual(self.controller.last_active_model, "deepseek-chat")
        self.assertTrue(self.controller.last_is_fallback)

    async def test_client_400_no_fallback(self):
        """
        验证首选客户端返回 400 客户端错误（非法参数等）时，直接抛出异常，不发生降级。
        """
        self.primary.mock_error = "api_400"
        self.primary.mock_delay = 0.1
        
        with self.assertRaises(LLMAPIError) as ctx:
            async for _ in self.controller.stream([], temperature=0.1):
                pass
        
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertFalse(self.controller.last_is_fallback)

    async def test_all_clients_fail(self):
        """
        验证所有客户端均不可用时，系统向上抛出统一的 LLMError 异常。
        """
        self.primary.mock_error = "connection"
        self.primary.mock_delay = 0.1
        
        bad_backup = OpenAIStreamAdapter(api_key="mock", model_name="bad-deepseek")
        bad_backup.mock_error = "connection"
        bad_backup.mock_delay = 0.1
        
        controller = FallbackController(clients=[self.primary, bad_backup], timeout=0.5)

        with self.assertRaises(LLMError):
            async for _ in controller.stream([], temperature=0.1):
                pass


if __name__ == "__main__":
    unittest.main()
