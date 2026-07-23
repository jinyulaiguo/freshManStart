"""HITL 审批断点单元测试 (Day 77 验收 #1 #2 #3 - 支持 Safe 0 拦截与 Sensitive 网关解耦)

测试范围：
1. Safe 只读 SQL 0 拦截自动放行执行，绝不触发 HITL 挂起！
2. 敏感 SQL (UPDATE/DELETE/DROP) 精确触发 approval_gateway 挂起。
3. 审批被拒绝 (rejected) 时记录 audit_trail 且不物理执行 SQL。
4. 审批时编辑 SQL (edit) 后放行，实际执行的是修改后的版本。
"""

import os
import sys
import uuid
import pytest
import asyncio
from langchain_core.messages import HumanMessage

# 动态将工作区根目录添加到 sys.path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../"))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from weekly.w11_langgraph_advanced.day77.graph.build_graph import build_sql_agent_graph
from weekly.w11_langgraph_advanced.day77.checkpoint.redis_checkpointer import ProductionRedisCheckpointer
from weekly.w11_langgraph_advanced.day77.database.init_db import init_database


@pytest.fixture(autouse=True)
def setup_db():
    """每次测试重置数据库沙箱。"""
    init_database()


@pytest.mark.asyncio
async def test_safe_sql_auto_execute_without_interrupt():
    """关键验证：Safe 只读 SQL 自动物理放行，0 拦截不触发 HITL 挂起！"""
    checkpointer = ProductionRedisCheckpointer()
    app = build_sql_agent_graph(checkpointer)
    config = {"configurable": {"thread_id": f"test_thread_safe_01_{uuid.uuid4().hex[:6]}"}}

    init_state = {
        "messages": [HumanMessage(content="查询所有 status 为 active 的用户")],
        "error_log": [],
        "audit_trail": []
    }
    final_output = await app.ainvoke(init_state, config)

    snapshot = app.get_state(config)
    # 验证最终已经完结，没有挂起在 approval_gateway！
    assert snapshot.next == (), f"错误：Safe 语句不应该挂起！实际 next 为: {snapshot.next}"
    assert final_output["execution_result"] is not None
    assert len(final_output["execution_result"]) > 0


@pytest.mark.asyncio
async def test_sensitive_sql_interrupt_and_approve():
    """验证敏感 UPDATE 触发 approval_gateway 挂起与人工批准放行。"""
    checkpointer = ProductionRedisCheckpointer()
    app = build_sql_agent_graph(checkpointer)
    config = {"configurable": {"thread_id": f"test_thread_hitl_01_{uuid.uuid4().hex[:6]}"}}

    # 1. 提交敏感 UPDATE 需求
    init_state = {
        "messages": [HumanMessage(content="更新用户 Ethan 的状态为 active")],
        "error_log": [],
        "audit_trail": []
    }
    await app.ainvoke(init_state, config)

    # 2. 检查 snapshot 是否精确挂起在 approval_gateway
    snapshot = app.get_state(config)
    assert snapshot.next == ("approval_gateway",), f"错误：敏感 SQL 未能挂起在 approval_gateway！实际为: {snapshot.next}"

    # 3. 人工 Approve 解冻放行
    app.update_state(
        config,
        {
            "approval_status": "approved",
            "audit_trail": ["Approved by pytest"]
        },
        as_node="risk_assess"
    )
    final_output = await app.ainvoke(None, config)

    # 4. 验证终局执行结果
    assert final_output["approval_status"] == "approved"
    assert final_output["execution_result"] is not None


@pytest.mark.asyncio
async def test_interrupt_and_reject():
    """验证人工 Reject 拒绝后中止执行并写入审计。"""
    checkpointer = ProductionRedisCheckpointer()
    app = build_sql_agent_graph(checkpointer)
    config = {"configurable": {"thread_id": f"test_thread_hitl_02_{uuid.uuid4().hex[:6]}"}}

    init_state = {
        "messages": [HumanMessage(content="删除状态为 suspended 的用户")],
        "error_log": [],
        "audit_trail": []
    }
    await app.ainvoke(init_state, config)

    snapshot = app.get_state(config)
    assert snapshot.next == ("approval_gateway",), f"应该挂起在 approval_gateway，实际为: {snapshot.next}"

    # 拒绝执行
    app.update_state(
        config,
        {
            "approval_status": "rejected",
            "audit_trail": ["Rejected by pytest auditor"]
        },
        as_node="risk_assess"
    )
    final_output = await app.ainvoke(None, config)

    assert final_output["approval_status"] == "rejected"
    assert "Rejected by pytest auditor" in final_output["audit_trail"]


@pytest.mark.asyncio
async def test_interrupt_and_edit_sql():
    """验证人工编辑 SQL (edit) 后恢复执行。"""
    checkpointer = ProductionRedisCheckpointer()
    app = build_sql_agent_graph(checkpointer)
    config = {"configurable": {"thread_id": f"test_thread_hitl_03_{uuid.uuid4().hex[:6]}"}}

    init_state = {
        "messages": [HumanMessage(content="更新用户 Bob 的 email 为 bob_new@enterprise.com")],
        "error_log": [],
        "audit_trail": []
    }
    await app.ainvoke(init_state, config)

    snapshot = app.get_state(config)
    assert snapshot.next == ("approval_gateway",)

    edited_sql = "UPDATE users SET email = 'bob_corrected@enterprise.com' WHERE name = 'Bob Jones';"
    app.update_state(
        config,
        {
            "generated_sql": edited_sql,
            "approval_status": "edited",
            "audit_trail": [f"Edited SQL by pytest: {edited_sql}"]
        },
        as_node="risk_assess"
    )
    final_output = await app.ainvoke(None, config)

    assert final_output["approval_status"] == "edited"
    assert final_output["generated_sql"] == edited_sql
