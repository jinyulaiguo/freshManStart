"""
Day 18: 统一 API 适配器单元测试

=========================================
设计方案说明
=========================================
1. 设计意图：
   通过自动化单元测试，验证 OpenAIClientAdapter 和 DeepSeekClientAdapter
   是否严格遵循统一的 BaseLLMClient 契约，并检验在 Mock 环境下的正常生成流程与异常转换传递机制。

2. 类与函数结构：
   - `TestAPIAdapter` (unittest.IsolatedAsyncioTestCase):
     - `test_protocol_compliance`: 验证适配器是否满足 BaseLLMClient Protocol。
     - `test_openai_generate_mock`: 验证 OpenAI 适配器在 Mock 模式下的成功流。
     - `test_deepseek_generate_mock`: 验证 DeepSeek 适配器在 Mock 模式下的成功流。
     - `test_exception_wrapping`: 验证底层的异常类型是否能被适配层包装为标准的 LLMError 体系异常。

3. 关键数据流流向：
   `运行单元测试` -> `调用 unittest 异步测试套件` -> `断言实例契约契合性`
   -> `Mock 数据交互验证` -> `触发模拟错误流` -> `捕获标准异常断言`
=========================================
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import openai

# 引入被测模块
from weekly.w03_llm_and_api.day_exercises.day18_api_adapter.api_adapter import (
    BaseLLMClient,
    OpenAIClientAdapter,
    DeepSeekClientAdapter,
    LLMRouter,
    LLMResponse,
    LLMError,
    LLMAPIError,
    LLMConnectionError
)


class TestAPIAdapter(unittest.IsolatedAsyncioTestCase):
    """
    统一适配器与角色语义契约单元测试
    """
    def setUp(self):
        self.test_messages = [
            {"role": "system", "content": "You are a professional software architect."},
            {"role": "user", "content": "Explain OOP in one sentence."}
        ]

    def test_protocol_compliance(self):
        """
        验证两个适配器类以及路由器是否实现了 BaseLLMClient 协议契约（使用 @runtime_checkable 校验）
        """
        openai_adapter = OpenAIClientAdapter(api_key="mock_key")
        deepseek_adapter = DeepSeekClientAdapter(api_key="mock_key")
        router = LLMRouter(clients=[openai_adapter])
        
        # 验证是否符合 Protocol 契约
        self.assertTrue(isinstance(openai_adapter, BaseLLMClient))
        self.assertTrue(isinstance(deepseek_adapter, BaseLLMClient))
        self.assertTrue(isinstance(router, BaseLLMClient))

    async def test_openai_generate_mock(self):
        """
        验证 OpenAIClientAdapter 在 Mock 模式下的生成行为
        """
        adapter = OpenAIClientAdapter(api_key="mock_key", model="gpt-4o")
        response = await adapter.generate(messages=self.test_messages, temperature=0.0)
        
        self.assertIsInstance(response, LLMResponse)
        self.assertTrue(response.content.startswith("[Mock OpenAI Completion"))
        self.assertEqual(response.model_name, "gpt-4o")
        self.assertEqual(response.finish_reason, "stop")

    async def test_deepseek_generate_mock(self):
        """
        验证 DeepSeekClientAdapter 在 Mock 模式下的生成行为
        """
        adapter = DeepSeekClientAdapter(api_key="mock_key", model="deepseek-chat")
        response = await adapter.generate(messages=self.test_messages, temperature=0.3)
        
        self.assertIsInstance(response, LLMResponse)
        self.assertTrue(response.content.startswith("[Mock DeepSeek Completion"))
        self.assertEqual(response.model_name, "deepseek-chat")
        self.assertEqual(response.finish_reason, "stop")

    @patch("openai.resources.chat.completions.AsyncCompletions.create")
    async def test_exception_wrapping_connection_error(self, mock_create):
        """
        验证当底层 SDK 抛出连接异常时，适配器将其包装为统一的 LLMConnectionError
        """
        # 强制底层 SDK 抛出 APIConnectionError
        mock_create.side_effect = openai.APIConnectionError(
            message="Connection timed out",
            request=MagicMock()
        )
        
        # 必须传入非 mock_key 从而启用真实的客户端流（以便让 patch 生效）
        adapter = OpenAIClientAdapter(api_key="real_key_simulated")
        
        with self.assertRaises(LLMConnectionError):
            await adapter.generate(messages=self.test_messages)

    @patch("openai.resources.chat.completions.AsyncCompletions.create")
    async def test_exception_wrapping_status_error(self, mock_create):
        """
        验证当底层 SDK 抛出状态错误时，适配器将其包装为统一的 LLMAPIError
        """
        # 强制底层 SDK 抛出 APIStatusError
        mock_create.side_effect = openai.APIStatusError(
            message="Rate Limit Exceeded",
            response=MagicMock(status_code=429),
            body=None
        )
        
        adapter = OpenAIClientAdapter(api_key="real_key_simulated")
        
        with self.assertRaises(LLMAPIError) as context:
            await adapter.generate(messages=self.test_messages)
            
        self.assertEqual(context.exception.status_code, 429)

    async def test_router_fallback_success(self):
        """
        验证 LLMRouter 在主客户端崩溃时能自动、静默地降级到备份客户端
        """
        # 定义一个必崩客户端
        class FaultyClient:
            async def generate(self, messages, **kwargs):
                raise LLMConnectionError("Failed to connect to DeepSeek API cluster.")

        backup_adapter = OpenAIClientAdapter(api_key="mock_key", model="gpt-4o")
        router = LLMRouter(clients=[FaultyClient(), backup_adapter])

        # 执行路由调用，应当静默捕获 FaultyClient 故障并无缝返回 backup_adapter 的响应
        response = await router.generate(messages=self.test_messages)
        
        self.assertIsInstance(response, LLMResponse)
        self.assertTrue(response.content.startswith("[Mock OpenAI Completion"))
        self.assertEqual(response.model_name, "gpt-4o")

    async def test_router_all_failed(self):
        """
        验证当全部客户端均崩溃时，LLMRouter 抛出包含最终错误状态的 LLMError
        """
        class FaultyClient1:
            async def generate(self, messages, **kwargs):
                raise LLMConnectionError("Faulty 1 down")

        class FaultyClient2:
            async def generate(self, messages, **kwargs):
                raise LLMAPIError(status_code=502, message="Bad Gateway")

        router = LLMRouter(clients=[FaultyClient1(), FaultyClient2()])

        with self.assertRaises(LLMError) as context:
            await router.generate(messages=self.test_messages)
            
        self.assertIn("All registered LLM clients failed. Last error: LLM API Error (Status 502): Bad Gateway", str(context.exception))


if __name__ == "__main__":
    unittest.main()

