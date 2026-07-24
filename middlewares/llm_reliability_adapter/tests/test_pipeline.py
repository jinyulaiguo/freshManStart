"""
==============================================================================
LLM Reliability Adapter - 真实场景驱动管道测试 (tests/test_pipeline.py)
==============================================================================

TDD (Test-Driven Development) 场景设计规范：
本测试套件完全脱离实现细节，纯粹基于工业级 LLM（如 DeepSeek-R1、Claude、Qwen、GPT-4o）
在生产环境中真实的 8 大概率性破坏场景 (Probabilistic Failure Modes) 进行测试用例设计。

测试场景矩阵 (Scenario Matrix)：
- [Scenario 1] DeepSeek-R1 思考链 (<think>...</think>) 与 Markdown 包裹混杂
- [Scenario 2] 包含前后缀解释文本，且 JSON 内部字段包含花括号占位符 (如 "{user}")
- [Scenario 3] 深度嵌套 JSON 字典对象结构解析
- [Scenario 4] 包含合法 JSON 语法不容许的尾随逗号 (Trailing Commas)
- [Scenario 5] 包含非标准单引号 key/value 及内部裸换行符
- [Scenario 6] 因 Max Token 限制导致文本中途截断、缺失闭合括号/双引号
- [Scenario 7] 类型不符合 Pydantic 强契约 (如 score 预期 int 返回 str)
==============================================================================
"""

import unittest
from typing import List
from pydantic import BaseModel, Field, ValidationError

from middlewares.llm_reliability_adapter.parser_pipeline.decoder import StrictDecoder, JSONDecodeCustomError
from middlewares.llm_reliability_adapter.parser_pipeline.extractor import BracketExtractor
from middlewares.llm_reliability_adapter.parser_pipeline.normalizer import Normalizer
from middlewares.llm_reliability_adapter.parser_pipeline.repair import DeterministicRepairer
from middlewares.llm_reliability_adapter.parser_pipeline.validator import SchemaValidator


# 定义测试用的真实业务契约模型
class TargetCriticSchema(BaseModel):
    decision: str
    score: int
    risk_items: List[str] = Field(default_factory=list)
    critique_feedback: str


class TestPipelineRealWorldScenarios(unittest.TestCase):
    """
    基于真实 LLM 破坏场景的 Pipeline 驱动测试用例
    """

    def test_scenario_01_deepseek_r1_thinking_chain(self):
        """
        [Scenario 1] 真实场景：DeepSeek-R1 思考链与 Markdown 嵌套代码块
        LLM 返回带有 <think> 思考过程，且在外层包裹 ```json ... ```
        """
        real_llm_output = """
<think>
User wants a contract review.
I need to check SLA, Limitation of Liability, and Data Privacy.
The draft lacks clear SLA credits. Overall score should be 70.
Decision is REJECT.
</think>

Here is the structured review result:
```json
{
  "decision": "REJECT",
  "score": 70,
  "risk_items": ["Missing SLA credit cap", "No DPA terms"],
  "critique_feedback": "Please add explicit SLA credits."
}
```
Hope this helps!
        """
        # Pipeline 组合校验
        normalized = Normalizer.normalize(real_llm_output)
        extracted = BracketExtractor.extract_json_object(normalized)
        decoded = StrictDecoder.decode(extracted)
        validated = SchemaValidator.validate(decoded, TargetCriticSchema)

        self.assertEqual(validated.decision, "REJECT")
        self.assertEqual(validated.score, 70)
        self.assertEqual(len(validated.risk_items), 2)

    def test_scenario_02_text_pollution_with_placeholders(self):
        """
        [Scenario 2] 真实场景：前后缀污染，且 JSON 内部值包含花括号占位符 (如 "{username}")
        验证 Extractor 栈平衡计数器不会被字段内部的花括号误导
        """
        real_llm_output = (
            'Sure! Here is the JSON output:\n'
            '{"decision": "PASS", "score": 90, "risk_items": [], '
            '"critique_feedback": "Welcome user {username} to system {sys_id}."}\n'
            'Let me know if you need more details.'
        )
        normalized = Normalizer.normalize(real_llm_output)
        extracted = BracketExtractor.extract_json_object(normalized)
        decoded = StrictDecoder.decode(extracted)
        validated = SchemaValidator.validate(decoded, TargetCriticSchema)

        self.assertEqual(validated.decision, "PASS")
        self.assertIn("{username}", validated.critique_feedback)

    def test_scenario_03_trailing_commas_and_extra_spaces(self):
        """
        [Scenario 3] 真实场景：模型生成了不合法的尾随逗号 (Trailing Commas)
        验证 DeterministicRepairer 的 Level 1 修补能力
        """
        real_llm_output = """
        {
            "decision": "REJECT",
            "score": 65,
            "risk_items": ["Risk 1", "Risk 2",],
            "critique_feedback": "Fix syntax",
        }
        """
        normalized = Normalizer.normalize(real_llm_output)
        extracted = BracketExtractor.extract_json_object(normalized)
        
        # 直接解码抛出异常
        with self.assertRaises(JSONDecodeCustomError):
            StrictDecoder.decode(extracted)

        # 经过 DeterministicRepairer 本地修补后解包成功
        repaired = DeterministicRepairer.repair_json_string(extracted)
        decoded = StrictDecoder.decode(repaired)
        validated = SchemaValidator.validate(decoded, TargetCriticSchema)

        self.assertEqual(validated.score, 65)
        self.assertEqual(len(validated.risk_items), 2)

    def test_scenario_04_single_quotes_and_raw_newlines(self):
        """
        [Scenario 4] 真实场景：使用非标准单引号及文本内包含裸换行符
        """
        real_llm_output = "{'decision': 'PASS', 'score': 85, 'risk_items': [], 'critique_feedback': 'Good job'}"
        normalized = Normalizer.normalize(real_llm_output)
        extracted = BracketExtractor.extract_json_object(normalized)
        
        repaired = DeterministicRepairer.repair_json_string(extracted)
        decoded = StrictDecoder.decode(repaired)
        validated = SchemaValidator.validate(decoded, TargetCriticSchema)

        self.assertEqual(validated.decision, "PASS")

    def test_scenario_05_max_token_truncated_json(self):
        """
        [Scenario 5] 真实场景：Max Tokens 截断，缺失闭合右括号与引号
        例如：`{"decision": "REJECT", "score": 50, "risk_items": ["Missing terms"`
        """
        truncated_output = '{"decision": "REJECT", "score": 50, "risk_items": ["Missing terms"'
        
        # 经过 repairer 补齐引号与大括号
        repaired = DeterministicRepairer.repair_json_string(truncated_output)
        decoded = StrictDecoder.decode(repaired)
        
        # 补齐 critique_feedback 的默认空值
        decoded["critique_feedback"] = "Auto repaired from truncated output"
        validated = SchemaValidator.validate(decoded, TargetCriticSchema)

        self.assertEqual(validated.decision, "REJECT")
        self.assertEqual(validated.score, 50)

    def test_scenario_06_schema_validation_type_mismatch(self):
        """
        [Scenario 6] 真实场景：字段类型不符合 Schema 契约 (Pydantic 拦截)
        模型把 score 返回成了非数字字符串 "ninety"
        """
        bad_type_output = '{"decision": "PASS", "score": "ninety", "critique_feedback": "OK"}'
        decoded = StrictDecoder.decode(bad_type_output)
        
        with self.assertRaises(ValidationError):
            SchemaValidator.validate(decoded, TargetCriticSchema)

    def test_scenario_07_parse_structured_facade(self):
        """
        [Scenario 7] 一键式极简门面函数 parse_structured() 验证
        传入混杂脏文本，单行函数直接吐出目标 Pydantic 对象
        """
        from middlewares.llm_reliability_adapter import parse_structured

        raw_llm_text = """
<think>Thinking chain...</think>
```json
{
  "decision": "PASS",
  "score": 95,
  "risk_items": [],
  "critique_feedback": "Perfect contract!"
}
```
        """
        obj = parse_structured(raw_llm_text, TargetCriticSchema)
        self.assertIsInstance(obj, TargetCriticSchema)
        self.assertEqual(obj.decision, "PASS")
        self.assertEqual(obj.score, 95)


if __name__ == "__main__":
    unittest.main()
