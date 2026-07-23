"""Redis 持久化与跨进程恢复单元测试 (Day 77 验收 #9 - 适配 approval_gateway 网关断点)

测试范围：
1. Graph 1 实例在触发 approval_gateway 挂起后存盘至 Docker Redis。
2. 彻底销毁 Graph 1 内存对象 (del graph_1)，模拟进程崩溃重启。
3. 实例化全新的 Graph 2 对象并绑定相同 Redis 句柄，成功还原 StateSnapshot 且继续原位解冻推演。
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
async def test_redis_cross_process_recovery():
    """验证物理销毁 Graph 实例后，基于 Redis 完美恢复流程。"""
    init_database()
    config = {"configurable": {"thread_id": "test_thread_redis_persistence_99"}}

    # ------------------------------------------------------------------------
    # 阶段 A: Graph 1 运行，在 approval_gateway 前挂起存盘
    # ------------------------------------------------------------------------
    cp_1 = ProductionRedisCheckpointer()
    app_1 = build_sql_agent_graph(cp_1)

    await app_1.ainvoke({"messages": [HumanMessage(content="更新用户 Fiona 的状态为 inactive")]}, config)
    snap_1 = app_1.get_state(config)
    assert snap_1.next == ("approval_gateway",)

    # ------------------------------------------------------------------------
    # 阶段 B: 物理销毁 Graph 1 实例 (模拟物理崩溃)
    # ------------------------------------------------------------------------
    del app_1
    del cp_1

    # ------------------------------------------------------------------------
    # 阶段 C: 实例化全新的 Graph 2，绑定 Redis 还原 State
    # ------------------------------------------------------------------------
    cp_2 = ProductionRedisCheckpointer()
    app_2 = build_sql_agent_graph(cp_2)

    snap_2 = app_2.get_state(config)
    assert snap_2.next == ("approval_gateway",), "恢复失败：Graph 2 未能从 Redis 恢复待执行节点！"
    assert snap_2.values["generated_sql"] is not None

    # ------------------------------------------------------------------------
    # 阶段 D: 在 Graph 2 中调用 update_state 并 invoke(None) 原位解冻
    # ------------------------------------------------------------------------
    app_2.update_state(
        config,
        {
            "approval_status": "approved",
            "audit_trail": ["Approved after Redis recovery"]
        },
        as_node="risk_assess"
    )
    final_output = await app_2.ainvoke(None, config)

    assert final_output["approval_status"] == "approved"
    assert final_output["execution_result"] is not None
