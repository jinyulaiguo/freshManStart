"""
路由函数单元测试：验证 R1/R2/R3 三组路由的所有分支覆盖

测试策略：
- 纯函数测试，无需模拟 LLM 或图执行
- 边界值覆盖：每个路由函数的所有可能返回值均需有对应测试
- 特别验证 R3 的环路控制逻辑（patch_retry_count 阈值）
"""

import pytest
from cve_pipeline.state import make_initial_state
from cve_pipeline.routers.safety_router import route_after_sanitizer
from cve_pipeline.routers.triage_router import route_after_triage
from cve_pipeline.routers.validation_router import route_after_validation, MAX_PATCH_RETRIES


def _base_state(**overrides) -> dict:
    state = make_initial_state(
        raw_input="测试漏洞",
        tenant_id="test_tenant",
        request_trace_id="test-trace",
    )
    state.update(overrides)
    return state


# =============================================================================
# R1: 安全过滤路由测试
# =============================================================================

class TestSafetyRouter:
    """route_after_sanitizer 路由函数测试套件。"""

    def test_safe_input_routes_to_triage(self):
        """安全输入应路由到 severity_triage。"""
        state = _base_state(is_input_safe=True)
        assert route_after_sanitizer(state) == "severity_triage"

    def test_unsafe_input_routes_to_block(self):
        """不安全输入应路由到 block_response。"""
        state = _base_state(is_input_safe=False)
        assert route_after_sanitizer(state) == "block_response"

    def test_default_safe_when_missing(self):
        """未设置 is_input_safe 时应默认安全（路由到 triage）。"""
        state = _base_state()
        # make_initial_state 默认 is_input_safe=True
        assert route_after_sanitizer(state) == "severity_triage"


# =============================================================================
# R2: 严重性分诊路由测试
# =============================================================================

class TestTriageRouter:
    """route_after_triage 路由函数测试套件。"""

    def test_critical_routes_to_escalation(self):
        """CRITICAL 应直接路由到 human_escalation。"""
        state = _base_state(severity="CRITICAL")
        assert route_after_triage(state) == "human_escalation"

    def test_high_routes_to_retriever(self):
        """HIGH 应路由到 cve_knowledge_retriever。"""
        state = _base_state(severity="HIGH")
        assert route_after_triage(state) == "cve_knowledge_retriever"

    def test_medium_routes_to_retriever(self):
        """MEDIUM 应路由到 cve_knowledge_retriever。"""
        state = _base_state(severity="MEDIUM")
        assert route_after_triage(state) == "cve_knowledge_retriever"

    def test_low_routes_to_reporter(self):
        """LOW 应直接路由到 compliance_reporter（跳过自动修复）。"""
        state = _base_state(severity="LOW")
        assert route_after_triage(state) == "compliance_reporter"

    def test_unknown_severity_routes_to_retriever(self):
        """未知严重性应保守路由到 cve_knowledge_retriever。"""
        state = _base_state(severity="UNKNOWN")
        assert route_after_triage(state) == "cve_knowledge_retriever"

    def test_case_insensitive_handling(self):
        """严重性值应不区分大小写（节点可能返回小写）。"""
        state = _base_state(severity="critical")
        # 路由函数内部做了 .upper() 处理
        assert route_after_triage(state) == "human_escalation"


# =============================================================================
# R3: 验证结果路由测试（含环路控制）
# =============================================================================

class TestValidationRouter:
    """route_after_validation 路由函数测试套件（含反馈环路控制）。"""

    def test_pass_routes_to_reporter(self):
        """验证通过应路由到 compliance_reporter。"""
        state = _base_state(validation_verdict="PASS", patch_retry_count=1)
        assert route_after_validation(state) == "compliance_reporter"

    def test_fail_first_retry_routes_to_patch(self):
        """首次 FAIL（retry_count=1 < 2）应回流到 code_patch_generator。"""
        state = _base_state(validation_verdict="FAIL", patch_retry_count=1)
        assert route_after_validation(state) == "code_patch_generator"

    def test_fail_second_retry_routes_to_patch(self):
        """第二次 FAIL（retry_count=1 时 MAX=2，仍可重试）应回流。"""
        # patch_retry_count=1 时，1 < MAX_PATCH_RETRIES(2)，仍可重试
        state = _base_state(validation_verdict="FAIL", patch_retry_count=1)
        assert route_after_validation(state) == "code_patch_generator"

    def test_fail_retries_exhausted_routes_to_escalation(self):
        """重试次数达到上限（retry_count >= MAX）应路由到 human_escalation。"""
        state = _base_state(validation_verdict="FAIL", patch_retry_count=MAX_PATCH_RETRIES)
        assert route_after_validation(state) == "human_escalation"

    def test_fail_over_limit_routes_to_escalation(self):
        """超过上限的重试次数也应路由到 human_escalation。"""
        state = _base_state(validation_verdict="FAIL", patch_retry_count=MAX_PATCH_RETRIES + 1)
        assert route_after_validation(state) == "human_escalation"

    def test_pass_ignores_retry_count(self):
        """验证通过时，无论 retry_count 是多少都应路由到 reporter。"""
        for retry_count in [0, 1, 5, 100]:
            state = _base_state(validation_verdict="PASS", patch_retry_count=retry_count)
            assert route_after_validation(state) == "compliance_reporter", \
                f"retry_count={retry_count} 时 PASS 应路由到 reporter"

    def test_max_retries_constant_is_2(self):
        """MAX_PATCH_RETRIES 常量应为 2（与计划设计一致）。"""
        assert MAX_PATCH_RETRIES == 2
