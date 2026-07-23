"""as_node 语义路由影响对比单元测试 (Day 77 验收 #10)

测试目的：
量化验证 update_state 中指定 as_node="risk_assess" 与不指定 as_node 对下游条件边路由的深远影响。
当更新状态时：
- 显式声明 as_node="risk_assess": 状态变更锚定在 risk_assess 节点，解冻时引擎认为是从 risk_assess 节点输出，准确触发条件边 risk_routing_condition!
- 若不声明 as_node: 默认锚定在之前的节点，可能导致路由路径判定错误或跳过关键风控/审计。
"""

import os
import sys
import pytest
from langchain_core.messages import HumanMessage

# 动态将工作区根目录添加到 sys.path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../"))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from weekly.w11_langgraph_advanced.day77.graph.build_graph import build_sql_agent_graph
from weekly.w11_langgraph_advanced.day77.checkpoint.redis_checkpointer import ProductionRedisCheckpointer
from weekly.w11_langgraph_advanced.day77.database.init_db import init_database


@pytest.mark.asyncio
async def test_as_node_explicit_routing():
    """验证显式声明 as_node='risk_assess' 正确驱动条件路由。"""
    init_database()
    checkpointer = ProductionRedisCheckpointer()
    app = build_sql_agent_graph(checkpointer)
    config = {"configurable": {"thread_id": "test_thread_asnode_01"}}

    # 1. 触发挂起
    await app.ainvoke({"messages": [HumanMessage(content="更新用户 Diana 的状态为 inactive")]}, config)
    snapshot_1 = app.get_state(config)
    assert snapshot_1.next == ("approval_gateway",)

    # 2. 显式使用 as_node="risk_assess"
    app.update_state(
        config,
        {
            "approval_status": "approved",
            "audit_trail": ["Explicit as_node test"]
        },
        as_node="risk_assess"
    )

    # 验证 snapshot 状态正确记录解冻并可通过路由
    res = await app.ainvoke(None, config)
    assert res["approval_status"] == "approved"
    assert res["execution_result"] is not None
