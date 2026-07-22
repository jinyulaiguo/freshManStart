"""
熔断引擎单元测试：验证 MultiDimensionalCircuitBreaker 四维熔断策略

测试策略：
- 使用 unittest.mock 模拟 CompiledGraph 的 invoke 行为，避免真实 LLM 调用
- 分别触发四个熔断维度，验证 degradation_payload 结构完整性
- 验证正常执行路径不触发熔断
"""

import pytest
from unittest.mock import MagicMock, patch
from langgraph.errors import GraphRecursionError
from langchain_core.messages import HumanMessage

from cve_pipeline.state import make_initial_state
from engines.circuit_breaker import MultiDimensionalCircuitBreaker, DEFAULT_RECURSION_LIMIT


def _make_mock_graph(return_state: dict = None, raise_error: Exception = None):
    """构建模拟的 CompiledGraph 对象。"""
    mock_graph = MagicMock()
    if raise_error:
        mock_graph.invoke.side_effect = raise_error
    else:
        mock_graph.invoke.return_value = return_state or {}
    return mock_graph


def _base_initial_state(**overrides) -> dict:
    state = make_initial_state(
        raw_input="测试漏洞描述",
        tenant_id="test_tenant",
        request_trace_id="test-trace-cb",
    )
    state.update(overrides)
    return state


# =============================================================================
# 维度 1: 超步限额熔断测试
# =============================================================================

class TestRecursionLimitBreaker:
    """GraphRecursionError 捕获与降级测试。"""

    def test_recursion_error_triggers_circuit_break(self):
        """GraphRecursionError 应触发熔断并生成降级 Payload。"""
        mock_graph = _make_mock_graph(raise_error=GraphRecursionError("recursion limit"))
        breaker = MultiDimensionalCircuitBreaker(mock_graph, recursion_limit=5)
        initial = _base_initial_state()

        result = breaker.execute(initial)

        assert result["is_circuit_broken"] is True
        payload = result["degradation_payload"]
        assert "RECURSION_LIMIT_EXCEEDED" in payload["trip_reason"]
        assert payload["circuit_breaker_tripped"] is True

    def test_recursion_limit_passed_to_config(self):
        """recursion_limit 值应通过 config 正确透传给 CompiledGraph.invoke。"""
        mock_state = _base_initial_state()
        mock_state["total_llm_tokens"] = 100
        mock_state["node_latency_log"] = []
        mock_graph = _make_mock_graph(return_state=mock_state)
        breaker = MultiDimensionalCircuitBreaker(mock_graph, recursion_limit=8)
        breaker.execute(_base_initial_state())

        # 验证 invoke 被调用了，并且调用参数中包含 recursion_limit=8
        assert mock_graph.invoke.called, "CompiledGraph.invoke 应被调用"
        call_args_str = str(mock_graph.invoke.call_args)
        assert "8" in call_args_str, f"recursion_limit=8 应出现在调用参数中，实际: {call_args_str}"


# =============================================================================
# 维度 2: Token 预算超限熔断测试
# =============================================================================

class TestTokenBudgetBreaker:
    """Token 消耗超出预算时的熔断测试。"""

    def test_token_budget_exceeded_triggers_break(self):
        """total_llm_tokens 超出 max_token_budget 应触发熔断。"""
        high_token_state = _base_initial_state()
        high_token_state["total_llm_tokens"] = 9000  # > budget=8000
        high_token_state["node_latency_log"] = []
        mock_graph = _make_mock_graph(return_state=high_token_state)
        breaker = MultiDimensionalCircuitBreaker(mock_graph, max_token_budget=8000)

        result = breaker.execute(_base_initial_state())

        assert result["is_circuit_broken"] is True
        assert "TOKEN_BUDGET_EXCEEDED" in result["degradation_payload"]["trip_reason"]

    def test_normal_token_usage_no_break(self):
        """正常 Token 消耗不应触发熔断。"""
        normal_state = _base_initial_state()
        normal_state["total_llm_tokens"] = 500
        normal_state["node_latency_log"] = []
        mock_graph = _make_mock_graph(return_state=normal_state)
        breaker = MultiDimensionalCircuitBreaker(mock_graph, max_token_budget=8000)

        result = breaker.execute(_base_initial_state())
        assert result.get("is_circuit_broken", False) is False


# =============================================================================
# 维度 3: 状态指纹震荡熔断测试
# =============================================================================

class TestFingerprintStagnationBreaker:
    """连续相同补丁指纹触发震荡熔断的测试。"""

    def _state_with_repeated_fingerprints(self, fingerprint: str, rounds: int) -> dict:
        state = _base_initial_state()
        state["total_llm_tokens"] = 500
        state["node_latency_log"] = [
            {"node": "code_patch_generator", "latency_ms": 100, "tokens_used": 100,
             "patch_fingerprint": fingerprint}
            for _ in range(rounds)
        ]
        return state

    def test_repeated_fingerprint_triggers_break(self):
        """连续 3 轮相同指纹应触发震荡熔断。"""
        stagnant_state = self._state_with_repeated_fingerprints("abcd1234", rounds=3)
        mock_graph = _make_mock_graph(return_state=stagnant_state)
        breaker = MultiDimensionalCircuitBreaker(
            mock_graph, fingerprint_stagnation_rounds=3
        )

        result = breaker.execute(_base_initial_state())

        assert result["is_circuit_broken"] is True
        assert "FINGERPRINT_STAGNATION" in result["degradation_payload"]["trip_reason"]

    def test_different_fingerprints_no_break(self):
        """每轮指纹不同时不应触发震荡熔断。"""
        state = _base_initial_state()
        state["total_llm_tokens"] = 500
        state["node_latency_log"] = [
            {"node": "code_patch_generator", "latency_ms": 100, "tokens_used": 100,
             "patch_fingerprint": f"fp{i}"}
            for i in range(3)
        ]
        mock_graph = _make_mock_graph(return_state=state)
        breaker = MultiDimensionalCircuitBreaker(mock_graph)

        result = breaker.execute(_base_initial_state())
        assert result.get("is_circuit_broken", False) is False


# =============================================================================
# 降级 Payload 结构完整性测试
# =============================================================================

class TestDegradationPayloadStructure:
    """降级 Payload 必须包含完整的四维诊断数据。"""

    def test_degradation_payload_has_required_fields(self):
        """降级 Payload 应包含所有必要的诊断字段。"""
        mock_graph = _make_mock_graph(raise_error=GraphRecursionError("test"))
        breaker = MultiDimensionalCircuitBreaker(mock_graph)
        result = breaker.execute(_base_initial_state())

        payload = result["degradation_payload"]
        required_fields = [
            "circuit_breaker_tripped", "trip_reason", "elapsed_ms",
            "total_supersteps_executed", "total_llm_tokens_consumed",
            "patch_iteration_count", "patch_fingerprint_history",
            "last_validation_verdict", "severity", "tenant_id",
            "request_trace_id", "recommended_action",
        ]
        for field in required_fields:
            assert field in payload, f"降级 Payload 缺少必要字段: {field}"

    def test_degradation_adds_circuit_broken_message(self):
        """熔断触发时应在 messages 中追加熔断通知消息。"""
        mock_graph = _make_mock_graph(raise_error=GraphRecursionError("test"))
        breaker = MultiDimensionalCircuitBreaker(mock_graph)
        result = breaker.execute(_base_initial_state())

        messages = result.get("messages", [])
        from langchain_core.messages import AIMessage
        cb_messages = [m for m in messages if isinstance(m, AIMessage) and "熔断" in m.content]
        assert len(cb_messages) >= 1, "熔断通知消息未出现在 messages 中"
