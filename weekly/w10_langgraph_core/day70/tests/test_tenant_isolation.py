"""
多租户隔离测试：验证 MemorySaver + thread_id 的会话物理隔离与历史追溯
"""

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import HumanMessage, AIMessage

from cve_pipeline.state import make_initial_state
from cve_pipeline.graph_builder import build_cve_triage_graph
from cve_pipeline.nodes.input_sanitizer import input_sanitizer_node
from cve_pipeline.nodes.block_response import block_response_node
from cve_pipeline.routers.safety_router import route_after_sanitizer
from engines.session_manager import TenantSessionManager


# =============================================================================
# 测试辅助
# =============================================================================

def _build_minimal_graph_with_memory():
    """构建仅含 sanitizer + block_response 的最小测试图（无 LLM 节点，速度快）。

    拓扑：START → sanitizer →[R1]→ block_response → END
                                 ↘→ block_response → END （简化为单一终点）
    """
    from langgraph.graph import StateGraph, START, END
    from cve_pipeline.state import CVETriageState

    memory = MemorySaver()
    wf = StateGraph(CVETriageState)
    wf.add_node("input_sanitizer", input_sanitizer_node)
    wf.add_node("end_node", block_response_node)  # 简化：两路都接到同一终点节点
    wf.add_edge(START, "input_sanitizer")
    wf.add_edge("input_sanitizer", "end_node")
    wf.add_edge("end_node", END)
    return wf.compile(checkpointer=memory), TenantSessionManager(wf.compile(checkpointer=memory))


# =============================================================================
# thread_id 生成测试
# =============================================================================

class TestThreadIdGeneration:
    """TenantSessionManager.generate_thread_id 的测试。"""

    def test_thread_id_contains_tenant_id(self):
        """生成的 thread_id 应以 tenant_id 为前缀。"""
        tid = TenantSessionManager.generate_thread_id("acme_corp")
        assert tid.startswith("acme_corp:")

    def test_thread_ids_are_unique(self):
        """同一租户的连续生成调用应产生不同的 thread_id。"""
        ids = [TenantSessionManager.generate_thread_id("tenant_a") for _ in range(10)]
        assert len(set(ids)) == 10, "thread_id 不唯一，存在冲突"

    def test_different_tenants_different_namespaces(self):
        """不同租户的 thread_id 命名空间应完全不同。"""
        id_a = TenantSessionManager.generate_thread_id("tenant_a")
        id_b = TenantSessionManager.generate_thread_id("tenant_b")
        assert id_a.split(":")[0] != id_b.split(":")[0]


# =============================================================================
# 会话隔离测试
# =============================================================================

class TestSessionIsolation:
    """MemorySaver thread_id 多租户会话物理隔离测试。"""

    def _run_with_thread(self, app, thread_id: str, raw_input: str, tenant_id: str) -> dict:
        """在指定 thread 下运行最小图。"""
        config = {"configurable": {"thread_id": thread_id}}
        initial = make_initial_state(
            raw_input=raw_input,
            tenant_id=tenant_id,
            request_trace_id=f"trace-{thread_id}",
        )
        return app.invoke(initial, config=config)

    def test_different_threads_isolated_message_history(self):
        """不同 thread_id 下的消息历史应完全隔离，互不干扰。"""
        memory = MemorySaver()
        from langgraph.graph import StateGraph, START, END
        from cve_pipeline.state import CVETriageState

        wf = StateGraph(CVETriageState)
        wf.add_node("sanitizer", input_sanitizer_node)
        wf.add_edge(START, "sanitizer")
        wf.add_edge("sanitizer", END)
        app = wf.compile(checkpointer=memory)

        thread_a = "tenant_a:session001"
        thread_b = "tenant_b:session002"

        result_a = self._run_with_thread(app, thread_a, "SQL 注入漏洞分析", "tenant_a")
        result_b = self._run_with_thread(app, thread_b, "XSS 跨站脚本分析", "tenant_b")

        # 验证 HumanMessage 历史是否物理隔离
        msgs_a = result_a.get("messages", [])
        msgs_b = result_b.get("messages", [])
        user_msgs_a = {m.content for m in msgs_a if isinstance(m, HumanMessage)}
        user_msgs_b = {m.content for m in msgs_b if isinstance(m, HumanMessage)}
        assert not user_msgs_a.intersection(user_msgs_b), "不同 thread 的用户消息历史存在交叉！"
        assert "SQL 注入漏洞分析" in user_msgs_a
        assert "XSS 跨站脚本分析" in user_msgs_b
        assert "SQL 注入漏洞分析" not in user_msgs_b

    def test_same_thread_accumulates_messages(self):
        """同一 thread_id 下的多次调用应累积消息历史。"""
        memory = MemorySaver()
        from langgraph.graph import StateGraph, START, END
        from cve_pipeline.state import CVETriageState

        wf = StateGraph(CVETriageState)
        wf.add_node("sanitizer", input_sanitizer_node)
        wf.add_edge(START, "sanitizer")
        wf.add_edge("sanitizer", END)
        app = wf.compile(checkpointer=memory)

        thread = "tenant_x:session999"
        config = {"configurable": {"thread_id": thread}}

        # 第一次调用
        state1 = make_initial_state("第一次漏洞分析", "tenant_x", "trace-1")
        result1 = app.invoke(state1, config=config)
        msg_count_1 = len(result1.get("messages", []))

        # 第二次调用（同一 thread，应继承前文）
        state2 = make_initial_state("第二次漏洞追问", "tenant_x", "trace-2")
        result2 = app.invoke(state2, config=config)
        msg_count_2 = len(result2.get("messages", []))

        assert msg_count_2 > msg_count_1, \
            f"同 thread 二次调用后消息数应增加：{msg_count_1} → {msg_count_2}"


# =============================================================================
# Checkpoint 历史追溯测试
# =============================================================================

class TestCheckpointHistory:
    """MemorySaver Checkpoint 版本追溯测试。"""

    def test_checkpoint_history_grows_with_invocations(self):
        """每次 invoke 后，Checkpoint 历史版本数应增加。"""
        memory = MemorySaver()
        from langgraph.graph import StateGraph, START, END
        from cve_pipeline.state import CVETriageState

        wf = StateGraph(CVETriageState)
        wf.add_node("sanitizer", input_sanitizer_node)
        wf.add_edge(START, "sanitizer")
        wf.add_edge("sanitizer", END)
        app = wf.compile(checkpointer=memory)

        thread = "history_test:thread001"
        config = {"configurable": {"thread_id": thread}}
        mgr = TenantSessionManager(app)

        # 首次调用前应无历史
        history_before = mgr.get_checkpoint_history(thread)
        count_before = len(history_before)

        # 执行一次
        state = make_initial_state("测试", "test", "trace-h1")
        app.invoke(state, config=config)

        history_after = mgr.get_checkpoint_history(thread)
        count_after = len(history_after)

        assert count_after > count_before, "invoke 后 Checkpoint 历史版本数应增加"

    def test_snapshot_contains_state_values(self):
        """最新状态快照应包含完整的 State 字段值。"""
        memory = MemorySaver()
        from langgraph.graph import StateGraph, START, END
        from cve_pipeline.state import CVETriageState

        wf = StateGraph(CVETriageState)
        wf.add_node("sanitizer", input_sanitizer_node)
        wf.add_edge(START, "sanitizer")
        wf.add_edge("sanitizer", END)
        app = wf.compile(checkpointer=memory)

        thread = "snapshot_test:abc"
        config = {"configurable": {"thread_id": thread}}
        mgr = TenantSessionManager(app)

        state = make_initial_state("快照测试漏洞", "tenant_snap", "trace-snap")
        app.invoke(state, config=config)

        snapshot = mgr.get_latest_snapshot(thread)
        assert snapshot is not None
        assert snapshot.values is not None
        assert "messages" in snapshot.values
        assert "tenant_id" in snapshot.values
        assert snapshot.values["tenant_id"] == "tenant_snap"
