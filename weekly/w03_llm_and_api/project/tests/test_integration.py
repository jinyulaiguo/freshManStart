"""
OpsChat CLI - 上下文裁剪与 Token 审计联合集成测试 (test_integration.py)

=========================================
设计方案说明
=========================================
1. 设计意图：
   验证系统在多组件协同工作下的联合集成链路。主要关注：
   - 消息在 Session 历史中积累并超出限制时，由 SmartContextCutter 完成的高精度滑动窗口裁剪；
   - 对话完毕后，TokenAuditor 对输入和输出消息进行的精确 Token 统计、计费换算与 CSV 日志落库；
   - 整体 Mock 流水线（Session -> Cutter -> Fallback -> Auditor）的集成连通性。

2. 测试类与方法结构：
   - TestOpsChatIntegration (unittest.IsolatedAsyncioTestCase):
     - setUp: 创建临时的 CSV 话单日志文件以隔离测试副作用，初始化所需的核心类实例。
     - tearDown: 清理生成的临时 CSV 话单日志文件。
     - test_context_cutter_with_session: 模拟向会话追加大量数据，验证 System 人设保留与滑动裁剪。
     - test_audit_csv_output: 验证审计器生成 CSV 的格式与字段正确性。
     - test_full_pipeline_mock: 验证从输入到输出、性能汇总和话单归档的整条主通路。

3. 关键数据流流向：
   `对话输入追加` -> `Session.history` 
   -> `SmartContextCutter.cut` -> `裁剪过长普通消息` 
   -> `FallbackController.stream 消费并聚合生成的 text`
   -> `TokenAuditor.record_audit 写入临时 CSV` 
   -> `解析 CSV 并断言各字段的正确性`
=========================================
"""

import os
import csv
import unittest
import asyncio

from weekly.w03_llm_and_api.project.core.session_manager import SessionManager
from weekly.w03_llm_and_api.project.core.context_cutter import SmartContextCutter
from weekly.w03_llm_and_api.project.core.token_auditor import TokenAuditor
from weekly.w03_llm_and_api.project.core.fallback_controller import FallbackController
from weekly.w03_llm_and_api.project.adapters.minimax_stream_adapter import MiniMaxStreamAdapter
from weekly.w03_llm_and_api.project.adapters.openai_stream_adapter import OpenAIStreamAdapter


class TestOpsChatIntegration(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # 临时 CSV 文件路径，用于隔离测试
        self.test_csv_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "test_audit_temp.csv"
        )
        # 清理可能残留的临时文件
        if os.path.exists(self.test_csv_path):
            os.remove(self.test_csv_path)

        # 初始化组件
        self.session_manager = SessionManager(max_sessions=3)
        self.cutter = SmartContextCutter(max_tokens=70)  # 小空间便于触发裁剪测试
        self.auditor = TokenAuditor(csv_filepath=self.test_csv_path)
        
        self.primary = MiniMaxStreamAdapter(api_key="mock", model_name="MiniMax-M3")
        self.backup = OpenAIStreamAdapter(api_key="mock", model_name="deepseek-chat")
        self.controller = FallbackController(clients=[self.primary, self.backup], timeout=0.5)

    def tearDown(self):
        # 物理清理测试生成的 CSV 文件
        if os.path.exists(self.test_csv_path):
            os.remove(self.test_csv_path)

    async def test_context_cutter_with_session(self):
        """
        验证上下文裁剪与 Session 协同工作时，能够正确保留 System 指令并滑动裁剪普通消息。
        """
        session_id = "test_user_session"
        session = await self.session_manager.get_session(session_id, create_if_missing=True)

        # 追加多条消息，使其长度总和显著超出 150 Tokens 限制
        # 每条消息约占 20-30 Tokens
        await session.append_message({"role": "user", "content": "Hello. I need help with Kubernetes."})
        await session.append_message({"role": "assistant", "content": "Sure, what Kubernetes issues are you facing?"})
        await session.append_message({"role": "user", "content": "My pods are stuck in ImagePullBackOff status."})
        await session.append_message({"role": "assistant", "content": "Check your container image path and private registry credentials."})
        await session.append_message({"role": "user", "content": "I double checked them, they seem correct. Could it be a network issue?"})
        await session.append_message({"role": "assistant", "content": "Yes, it could be DNS or MTU size config."})
        await session.append_message({"role": "user", "content": "Show me the commands to inspect CoreDNS logs."})

        # 联合 System prompt 进行裁剪
        system_prompt = "You are OpsChat AI. SRE expert."
        full_messages = [{"role": "system", "content": system_prompt}] + session.history
        
        cut_messages = self.cutter.cut(full_messages)

        # 验证 System Prompt 依旧在首位 (必须无条件保留 System)
        self.assertEqual(cut_messages[0]["role"], "system")
        self.assertEqual(cut_messages[0]["content"], system_prompt)

        # 验证普通对话已经被截断丢弃了最老的部分，最新的消息被保留在末尾
        self.assertEqual(cut_messages[-1]["role"], "user")
        self.assertEqual(cut_messages[-1]["content"], "Show me the commands to inspect CoreDNS logs.")
        
        # 消息条数应该小于原有的 8 条
        self.assertTrue(len(cut_messages) < 8)

    async def test_audit_csv_output(self):
        """
        验证审计计费模块正常计算并将记录输出为 CSV 结构化文件。
        """
        input_messages = [
            {"role": "system", "content": "You are a Kubernetes SRE."},
            {"role": "user", "content": "CoreDNS is failing."}
        ]
        response_text = "Check Kube-DNS service endpoints and Pod status using kubectl."

        # 模拟审计一条记录
        record = self.auditor.record_audit(
            session_id="session_test",
            model_name="MiniMax-M3",
            input_messages=input_messages,
            response_text=response_text,
            ttft_ms=120.5,
            is_fallback=False
        )

        # 验证返回实体的有效性
        self.assertEqual(record.session_id, "session_test")
        self.assertEqual(record.model_name, "MiniMax-M3")
        self.assertFalse(record.is_fallback)
        self.assertEqual(record.ttft_ms, 120.5)
        self.assertTrue(record.cost_usd > 0)

        # 读取并校验生成的 CSV 文件内容
        self.assertTrue(os.path.exists(self.test_csv_path))
        with open(self.test_csv_path, mode="r", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)
            
            # 第一行应为表头
            self.assertEqual(rows[0][0], "timestamp")
            self.assertEqual(rows[0][1], "session_id")
            self.assertEqual(rows[0][4], "output_tokens")
            self.assertEqual(rows[0][6], "cost_usd")
            
            # 第二行应为刚才写入的数据
            self.assertEqual(rows[1][1], "session_test")
            self.assertEqual(rows[1][2], "MiniMax-M3")
            self.assertEqual(rows[1][8], "False")

    async def test_full_pipeline_mock(self):
        """
        测试从输入、会话、裁剪、降级运行到话单审计的完整集成流水线 (Mock 模式)。
        """
        session_id = "pipeline_test"
        session = await self.session_manager.get_session(session_id, create_if_missing=True)

        user_input = "K8s Deployment is crashlooping."
        await session.append_message({"role": "user", "content": user_input})

        # 裁剪
        full_messages = [{"role": "system", "content": "SRE bot"}] + session.history
        cut_messages = self.cutter.cut(full_messages)

        # 降级流式生成
        response_chunks = []
        async for chunk in self.controller.stream(cut_messages, temperature=0.1):
            response_chunks.append(chunk)

        response_text = "".join(c.content for c in response_chunks)
        self.assertTrue(len(response_chunks) > 0)
        self.assertIn("logs", response_text) # 包含 mock 数据中的 logs 字眼

        # 记录审计话单
        model_used = self.controller.last_active_model
        is_fallback = self.controller.last_is_fallback
        metrics = self.controller.last_metrics

        self.assertEqual(model_used, "MiniMax-M3")
        self.assertFalse(is_fallback)
        self.assertIsNotNone(metrics)

        record = self.auditor.record_audit(
            session_id=session_id,
            model_name=model_used,
            input_messages=cut_messages,
            response_text=response_text,
            ttft_ms=metrics.ttft_ms,
            is_fallback=is_fallback
        )

        # 验证计费正常
        summary = self.auditor.get_summary()
        self.assertEqual(summary["total_requests"], 1)
        self.assertEqual(summary["fallback_count"], 0)
        self.assertEqual(summary["total_cost_usd"], record.cost_usd)


if __name__ == "__main__":
    unittest.main()
