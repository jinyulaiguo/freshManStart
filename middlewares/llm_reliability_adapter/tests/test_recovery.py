"""
==============================================================================
LLM Reliability Adapter - 恢复机制集成测试 (tests/test_recovery.py)
==============================================================================

设计方案说明与核心用例设计意图：
1. Mock 一个可按序列返回响应的 MockLLMDriver。
2. 验证 Level 1 本地确定性修补成功时的恢复轨迹。
3. 验证 Level 2 LLM Re-prompt 在第二次回应合法 JSON 时的修复轨迹。
4. 验证 Level 3 Circuit Breaker 熔断降级工厂触发有效性。
==============================================================================
"""

import unittest
from typing import List, Optional
from pydantic import BaseModel

from middlewares.llm_reliability_adapter.adapter import UniversalAdapter
from middlewares.llm_reliability_adapter.config import ReliabilityConfig
from middlewares.llm_reliability_adapter.contracts.input_output import AdapterInput
from middlewares.llm_reliability_adapter.drivers.base import BaseLLMDriver


class TargetSchema(BaseModel):
    decision: str
    score: int
    reason: str


class MockSequenceDriver(BaseLLMDriver):
    """用于单元测试的响应序列 Mock 驱动"""
    def __init__(self, responses: List[str]):
        self.responses = responses
        self.call_count = 0
        self.prompts_received = []

    def generate(self, prompt: str, system_instruction: Optional[str] = None, context: Optional[dict] = None) -> str:
        self.prompts_received.append(prompt)
        resp = self.responses[min(self.call_count, len(self.responses) - 1)]
        self.call_count += 1
        return resp


class TestRecoveryEngine(unittest.TestCase):
    """
    恢复机制集成测试
    """

    def test_01_direct_pass(self):
        """测试直接解析通过情况"""
        driver = MockSequenceDriver(['{"decision": "PASS", "score": 90, "reason": "Good"}'])
        adapter = UniversalAdapter(driver)
        
        inp = AdapterInput(prompt="Check code", response_model=TargetSchema)
        out = adapter.process(inp)
        
        self.assertTrue(out.success)
        self.assertEqual(out.data.decision, "PASS")
        self.assertEqual(out.attempts, 1)

    def test_02_level1_local_repair(self):
        """测试 Level 1 本地确定性修补 (带尾随逗号与缺失闭合括号)"""
        driver = MockSequenceDriver(['{"decision": "REJECT", "score": 60, "reason": "Bad style",}'])
        adapter = UniversalAdapter(driver)
        
        inp = AdapterInput(prompt="Check code", response_model=TargetSchema)
        out = adapter.process(inp)
        
        self.assertTrue(out.success)
        self.assertEqual(out.data.decision, "REJECT")
        self.assertIn("LOCAL_REPAIR_SUCCESS", [step.action for step in out.recovery_path])

    def test_03_level2_llm_reprompt_recovery(self):
        """测试 Level 2 LLM Re-prompt 纠错恢复 (首轮彻底非法，第二轮纠正)"""
        responses = [
            "Sorry, I cannot produce JSON directly...",  # 首轮纯字符串，无法本地修补
            '{"decision": "PASS", "score": 85, "reason": "Fixed on retry"}'  # 第二轮纠正
        ]
        driver = MockSequenceDriver(responses)
        adapter = UniversalAdapter(driver)
        
        inp = AdapterInput(
            prompt="Check contract",
            response_model=TargetSchema,
            config=ReliabilityConfig(max_retries=3)
        )
        out = adapter.process(inp)
        
        self.assertTrue(out.success)
        self.assertEqual(out.data.reason, "Fixed on retry")
        self.assertEqual(out.attempts, 2)

    def test_04_level3_circuit_breaker_fallback(self):
        """测试 Level 3 熔断降级兜底"""
        driver = MockSequenceDriver(["Invalid output continuously"])
        adapter = UniversalAdapter(driver)
        
        fallback_data = TargetSchema(decision="REJECT", score=0, reason="Parse failed fallback")
        inp = AdapterInput(
            prompt="Check contract",
            response_model=TargetSchema,
            config=ReliabilityConfig(max_retries=2, enable_circuit_breaker=True),
            fallback_factory=lambda: fallback_data
        )
        out = adapter.process(inp)
        
        self.assertTrue(out.success)
        self.assertEqual(out.data.reason, "Parse failed fallback")
        self.assertIn("LEVEL3_FALLBACK_TRIGGERED", [step.action for step in out.recovery_path])


if __name__ == "__main__":
    unittest.main()
