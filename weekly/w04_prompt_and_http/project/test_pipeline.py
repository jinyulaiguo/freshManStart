"""
Week 4 Day 28 综合实战 — 单元测试套件 (Test Pipeline)

设计方案：
1. 设计意图：
   对流水线各微引擎进行隔离单元测试，核心逻辑测试使用 Mock 以确保稳定性，
   集成测试（main.py）使用真实 API 验证端到端行为。

2. 测试覆盖矩阵：
   - TestResumeSchema: Pydantic 模型正常实例化、字段越界拦截、邮箱格式校验、嵌套技能校验
   - TestSelfCorrection: 正常 JSON 解析校验、脏 JSON 修复后校验、字段越界错误捕获
   - TestCircuitBreaker: 正常透传、连续失败触发 Open、冷却期 Fail-Fast 拦截、Half-Open 自愈
   - TestPipelineReport: 统计报告聚合计算、成功率与自愈率计算
"""

import sys
import os
import json
import asyncio
import time
import unittest

# =====================================================================
# 防御性 sys.path 补丁逻辑
# =====================================================================
current_dir = os.path.dirname(os.path.realpath(__file__))
root_dir = os.path.abspath(os.path.join(current_dir, "../../.."))

if os.getcwd() not in sys.path:
    sys.path.insert(0, os.getcwd())
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from pydantic import ValidationError

from weekly.w04_prompt_and_http.project.resume_schema import (
    ResumeInfo, SkillDetail, WorkExperience, ExtractionResult, format_validation_error
)
from weekly.w04_prompt_and_http.project.circuit_breaker import (
    circuit_breaker, CircuitBreakerOpenException
)
from weekly.w04_prompt_and_http.project.self_correction import SelfCorrectionEngine
from weekly.w04_prompt_and_http.project.pipeline import PipelineReport


# =====================================================================
# 测试 1: 简历数据契约层 (ResumeSchema)
# =====================================================================

class TestResumeSchema(unittest.TestCase):
    """测试 Pydantic 简历数据模型的校验行为"""

    def test_valid_resume_instantiation(self):
        """正常数据应成功实例化"""
        data = {
            "name": "测试用户",
            "email": "test@example.com",
            "phone": "13800138000",
            "skills": {
                "Python": {"level": 90, "years_of_experience": 5.0},
                "Go": {"level": 70, "years_of_experience": 2.0}
            },
            "work_experience": [
                {"company": "测试公司", "position": "工程师", "years": 3.0}
            ]
        }
        resume = ResumeInfo.model_validate(data)
        self.assertEqual(resume.name, "测试用户")
        self.assertEqual(resume.email, "test@example.com")
        self.assertEqual(len(resume.skills), 2)
        self.assertEqual(len(resume.work_experience), 1)

    def test_skill_level_out_of_range(self):
        """技能熟练度越界（>100）应触发 ValidationError"""
        data = {
            "name": "测试",
            "email": "test@example.com",
            "skills": {
                "Python": {"level": 150, "years_of_experience": 3.0}
            },
            "work_experience": [
                {"company": "公司", "position": "开发", "years": 1.0}
            ]
        }
        with self.assertRaises(ValidationError) as ctx:
            ResumeInfo.model_validate(data)
        # 确认错误路径包含 skills -> Python -> level
        errors = ctx.exception.errors()
        self.assertTrue(any("level" in str(e.get("loc", [])) for e in errors))

    def test_skill_level_zero(self):
        """技能熟练度为 0 应触发 ValidationError（合法范围 1-100）"""
        data = {
            "name": "测试",
            "email": "test@example.com",
            "skills": {
                "Python": {"level": 0, "years_of_experience": 1.0}
            },
            "work_experience": [
                {"company": "公司", "position": "开发", "years": 1.0}
            ]
        }
        with self.assertRaises(ValidationError):
            ResumeInfo.model_validate(data)

    def test_negative_years_of_experience(self):
        """使用年限为负数应触发 ValidationError"""
        data = {
            "name": "测试",
            "email": "test@example.com",
            "skills": {
                "Python": {"level": 80, "years_of_experience": -1.0}
            },
            "work_experience": [
                {"company": "公司", "position": "开发", "years": 1.0}
            ]
        }
        with self.assertRaises(ValidationError):
            ResumeInfo.model_validate(data)

    def test_invalid_email_format(self):
        """非法邮箱格式应触发 ValidationError"""
        data = {
            "name": "测试",
            "email": "bad_email_no_at",
            "skills": {
                "Python": {"level": 80, "years_of_experience": 3.0}
            },
            "work_experience": [
                {"company": "公司", "position": "开发", "years": 1.0}
            ]
        }
        with self.assertRaises(ValidationError):
            ResumeInfo.model_validate(data)

    def test_negative_work_years(self):
        """工作年限为负数/零应触发 ValidationError"""
        data = {
            "name": "测试",
            "email": "test@example.com",
            "skills": {
                "Python": {"level": 80, "years_of_experience": 3.0}
            },
            "work_experience": [
                {"company": "公司", "position": "开发", "years": 0}
            ]
        }
        with self.assertRaises(ValidationError):
            ResumeInfo.model_validate(data)

    def test_optional_phone_field(self):
        """手机号为 None 应正常通过校验"""
        data = {
            "name": "测试",
            "email": "test@example.com",
            "phone": None,
            "skills": {
                "Python": {"level": 80, "years_of_experience": 3.0}
            },
            "work_experience": [
                {"company": "公司", "position": "开发", "years": 1.0}
            ]
        }
        resume = ResumeInfo.model_validate(data)
        self.assertIsNone(resume.phone)

    def test_format_validation_error(self):
        """ValidationError 格式化输出应包含字段路径和报错原因"""
        data = {
            "name": "测试",
            "email": "bad",
            "skills": {
                "Python": {"level": 200, "years_of_experience": -1.0}
            },
            "work_experience": [
                {"company": "公司", "position": "开发", "years": -1.0}
            ]
        }
        try:
            ResumeInfo.model_validate(data)
        except ValidationError as ve:
            formatted = format_validation_error(ve)
            self.assertIn("字段路径", formatted)
            self.assertIn("报错原因", formatted)
            self.assertIn("错误 #", formatted)

    def test_json_schema_export(self):
        """JSON Schema 导出应包含必要的 properties"""
        schema = ResumeInfo.model_json_schema()
        self.assertIn("properties", schema)
        props = schema["properties"]
        self.assertIn("name", props)
        self.assertIn("email", props)
        self.assertIn("skills", props)
        self.assertIn("work_experience", props)


# =====================================================================
# 测试 2: 反思自愈纠错引擎 (SelfCorrection)
# =====================================================================

class TestSelfCorrection(unittest.TestCase):
    """测试 SelfCorrectionEngine 的本地解析与校验逻辑"""

    def setUp(self):
        """创建不需要 LLM 客户端的引擎实例（仅测试本地方法）"""
        self.engine = SelfCorrectionEngine(llm_client=None, max_correction_rounds=2)

    def test_valid_json_parse_and_validate(self):
        """正常 JSON 应解析并校验成功"""
        valid_json = json.dumps({
            "name": "测试",
            "email": "test@example.com",
            "skills": {"Python": {"level": 80, "years_of_experience": 3.0}},
            "work_experience": [{"company": "公司", "position": "开发", "years": 1.0}]
        }, ensure_ascii=False)
        result, error = self.engine._try_parse_and_validate(valid_json)
        self.assertIsNotNone(result)
        self.assertIsNone(error)
        self.assertEqual(result.name, "测试")

    def test_dirty_json_with_markdown_wrapping(self):
        """带 Markdown 包裹的脏 JSON 应通过 Day 24 修复器修复后校验成功"""
        dirty_json = """```json
{"name": "脏数据测试", "email": "test@example.com", "skills": {"Go": {"level": 70, "years_of_experience": 2.0}}, "work_experience": [{"company": "测试公司", "position": "开发", "years": 1.0}]}
```"""
        result, error = self.engine._try_parse_and_validate(dirty_json)
        self.assertIsNotNone(result)
        self.assertIsNone(error)

    def test_dirty_json_with_single_quotes(self):
        """含单引号的脏 JSON 应修复后校验成功"""
        dirty_json = "{'name': '单引号', 'email': 'test@example.com', 'skills': {'Rust': {'level': 85, 'years_of_experience': 3.0}}, 'work_experience': [{'company': '公司', 'position': '开发', 'years': 2.0}]}"
        result, error = self.engine._try_parse_and_validate(dirty_json)
        self.assertIsNotNone(result)
        self.assertIsNone(error)

    def test_invalid_fields_return_error(self):
        """字段越界的 JSON 应返回 None 和错误描述"""
        bad_json = json.dumps({
            "name": "测试",
            "email": "bad_email",
            "skills": {"Python": {"level": 200, "years_of_experience": -1.0}},
            "work_experience": [{"company": "公司", "position": "开发", "years": -1.0}]
        }, ensure_ascii=False)
        result, error = self.engine._try_parse_and_validate(bad_json)
        self.assertIsNone(result)
        self.assertIsNotNone(error)
        self.assertIn("字段路径", error)

    def test_correction_prompt_assembly(self):
        """纠错 Prompt 组装应包含原始输出和错误详情"""
        messages = self.engine._build_correction_prompt(
            original_output='{"name": "test"}',
            error_detail="错误 #1: 邮箱字段缺失",
            resume_text="原始简历文本"
        )
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[1]["role"], "user")
        self.assertIn("纠错", messages[0]["content"])
        self.assertIn("原始简历文本", messages[1]["content"])
        self.assertIn("错误 #1", messages[1]["content"])

    def test_think_tag_stripping(self):
        """<think> 标签应被正确剥离"""
        text_with_think = '<think>这是思考过程</think>{"name": "test"}'
        stripped = self.engine._strip_thinking_tags(text_with_think)
        self.assertNotIn("<think>", stripped)
        self.assertTrue(stripped.startswith("{"))


# =====================================================================
# 测试 3: 熔断器异步装饰器 (CircuitBreaker)
# =====================================================================

class TestCircuitBreaker(unittest.TestCase):
    """测试 @circuit_breaker 装饰器的状态机行为"""

    def test_normal_pass_through(self):
        """正常调用应直接透传返回值"""
        @circuit_breaker(failure_threshold=3, cooldown_seconds=1.0)
        async def good_func():
            return "ok"

        result = asyncio.run(good_func())
        self.assertEqual(result, "ok")
        self.assertEqual(good_func.breaker_state.state, "CLOSED")

    def test_failure_triggers_open(self):
        """连续失败达阈值应触发 Open 状态"""
        @circuit_breaker(failure_threshold=3, cooldown_seconds=10.0)
        async def bad_func():
            raise ConnectionError("boom")

        async def run():
            for _ in range(3):
                try:
                    await bad_func()
                except ConnectionError:
                    pass
            return bad_func.breaker_state.state

        state = asyncio.run(run())
        self.assertEqual(state, "OPEN")

    def test_open_state_fast_fail(self):
        """Open 状态应抛出 CircuitBreakerOpenException"""
        @circuit_breaker(failure_threshold=2, cooldown_seconds=10.0)
        async def bad_func():
            raise ConnectionError("boom")

        async def run():
            # 触发熔断
            for _ in range(2):
                try:
                    await bad_func()
                except ConnectionError:
                    pass

            # 验证快速失败
            with self.assertRaises(CircuitBreakerOpenException):
                await bad_func()

        asyncio.run(run())

    def test_half_open_recovery(self):
        """冷却期过后应切为 Half-Open，成功请求后恢复为 Closed"""
        @circuit_breaker(failure_threshold=2, cooldown_seconds=0.5)
        async def toggle_func(should_fail=False):
            if should_fail:
                raise ConnectionError("boom")
            return "ok"

        async def run():
            # 触发熔断
            for _ in range(2):
                try:
                    await toggle_func(should_fail=True)
                except ConnectionError:
                    pass
            self.assertEqual(toggle_func.breaker_state.state, "OPEN")

            # 等待冷却期
            await asyncio.sleep(0.6)

            # 自愈探路
            result = await toggle_func(should_fail=False)
            self.assertEqual(result, "ok")
            self.assertEqual(toggle_func.breaker_state.state, "CLOSED")
            self.assertEqual(toggle_func.breaker_state.failures, 0)

        asyncio.run(run())


# =====================================================================
# 测试 4: 流水线报告统计 (PipelineReport)
# =====================================================================

class TestPipelineReport(unittest.TestCase):
    """测试 PipelineReport 的统计计算"""

    def test_success_rate_calculation(self):
        """成功率计算应正确"""
        report = PipelineReport(
            total_count=10,
            success_count=8,
            self_corrected_count=2,
            breaker_tripped_count=1,
            failed_count=2,
            total_time_seconds=5.0
        )
        self.assertAlmostEqual(report.success_rate, 80.0)
        self.assertAlmostEqual(report.self_correction_rate, 25.0)

    def test_zero_total_count(self):
        """总数为 0 时成功率应为 0"""
        report = PipelineReport(
            total_count=0,
            total_time_seconds=0.0
        )
        self.assertAlmostEqual(report.success_rate, 0.0)

    def test_all_success_no_correction(self):
        """全部成功且无自愈时，自愈率应为 0"""
        report = PipelineReport(
            total_count=5,
            success_count=5,
            self_corrected_count=0,
            total_time_seconds=3.0
        )
        self.assertAlmostEqual(report.success_rate, 100.0)
        self.assertAlmostEqual(report.self_correction_rate, 0.0)

    def test_extraction_result_model(self):
        """ExtractionResult 模型应正确实例化"""
        result = ExtractionResult(
            resume_index=0,
            original_text="测试简历...",
            success=True,
            self_corrected=True,
            correction_rounds=1
        )
        self.assertTrue(result.success)
        self.assertTrue(result.self_corrected)
        self.assertEqual(result.correction_rounds, 1)
        self.assertFalse(result.breaker_tripped)


# =====================================================================
# 测试入口
# =====================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
