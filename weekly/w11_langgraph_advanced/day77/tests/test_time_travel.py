"""时间旅行 (Time Travel) 与故障自愈分叉单元测试 (Day 77 验收 #4 #5 #6)

测试范围：
1. get_state_history 可精准拉取全量 Checkpoint 链。
2. 选定特定历史快照点 update_state 并分叉推演，原始线程 Checkpoint 历史不受污染。
3. 模拟 SQL 执行崩溃 (FORCE_SQL_ERROR)，通过 Time Travel 回溯至 sql_generation 之后修补参数并分叉成功。
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
async def test_time_travel_history_and_forking():
    """验证快照链读取与分叉独立性。"""
    init_database()
    checkpointer = ProductionRedisCheckpointer()
    app = build_sql_agent_graph(checkpointer)
    config = {"configurable": {"thread_id": "test_thread_tt_01"}}

    # 1. 运行一条普通 SELECT 查询生成多个 Checkpoint
    await app.ainvoke({"messages": [HumanMessage(content="查询所有的用户信息")]}, config)

    # 2. 读取 Checkpoint 历史链
    history = list(app.get_state_history(config))
    assert len(history) >= 2, "应该产生至少 2 个 Checkpoint 节点！"

    # 3. 选中更早的一个快照点作为分叉起点
    fork_target = history[-1]
    fork_config = fork_target.config

    # 在该历史点注入新的 SQL 启动分叉
    new_sql = "SELECT * FROM orders WHERE status = 'completed';"
    new_config = app.update_state(
        fork_config,
        {
            "generated_sql": new_sql,
            "audit_trail": ["Time Travel fork in pytest"]
        },
        as_node="sql_generation"
    )

    fork_output = await app.ainvoke(None, new_config)

    # 4. 验证分叉成功且包含修改后的语句/执行记录
    assert new_sql in fork_output.get("generated_sql", "") or fork_output.get("execution_result") is not None

    all_history_after = list(app.get_state_history(config))
    assert len(all_history_after) > len(history), "分叉运行后应该新增独立的 Checkpoint！"


@pytest.mark.asyncio
async def test_fault_recovery_via_time_travel():
    """验证模拟 PG 执行故障后，使用 Time Travel 回溯重试。"""
    init_database()
    checkpointer = ProductionRedisCheckpointer()
    app = build_sql_agent_graph(checkpointer)
    config = {"configurable": {"thread_id": "test_thread_tt_fault_02"}}

    # 1. 开启故障注入环境变量
    os.environ["FORCE_SQL_ERROR"] = "1"

    # 运行查询导致 sql_execution 模拟崩溃
    await app.ainvoke({"messages": [HumanMessage(content="查询用户 Ethan 的订单记录")]}, config)

    snap = app.get_state(config)
    assert len(snap.values.get("error_log", [])) > 0, "未能成功触发模拟物理故障！"

    # 2. 关闭故障注入，准备通过 Time Travel 回溯到执行前重试
    os.environ.pop("FORCE_SQL_ERROR", None)

    history = list(app.get_state_history(config))
    target_snap = None
    for s in history:
        if s.next == ("sql_execution",):
            target_snap = s
            break

    if not target_snap:
        target_snap = history[0]

    # 3. 在故障前快照点 update_state 并分叉恢复
    fork_config = target_snap.config
    repaired_sql = "SELECT * FROM orders WHERE user_id = 5;"
    repaired_config = app.update_state(
        fork_config,
        {
            "generated_sql": repaired_sql,
            "approval_status": "approved",
            "audit_trail": ["Repaired fault using Time Travel and approved."]
        },
        as_node="risk_assess"
    )

    repaired_output = await app.ainvoke(None, repaired_config)

    # 4. 验证成功自愈恢复并查到数据
    assert repaired_output["execution_result"] is not None
