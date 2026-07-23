"""子图并行与状态隔离单元测试 (Day 77 验收 #7 #8 - 适配 approval_gateway 网关)

测试范围：
1. 子图内部 summarize (2s 延迟)、validate、audit 并行 Fan-out 执行，merge 节点等待全部 Worker 完成后再解冻 Barrier。
2. 子图私有字段 audit_record 与 internal_trace 不会物理泄露至主图 ParentState。
"""

import os
import sys
import time
import uuid
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
async def test_subgraph_barrier_and_state_isolation():
    """验证 2s 延时 Barrier 同步屏障与子图私有字段隔离。"""
    init_database()
    checkpointer = ProductionRedisCheckpointer()
    app = build_sql_agent_graph(checkpointer)
    # 使用独立的 uuid thread_id 防止测试间污染
    unique_thread_id = f"test_thread_subgraph_{uuid.uuid4().hex[:8]}"
    config = {"configurable": {"thread_id": unique_thread_id}}

    start_t = time.time()
    await app.ainvoke({"messages": [HumanMessage(content="查询用户 Alice 的所有订单记录")]}, config)

    # 如果挂起在 approval_gateway 前，解冻放行以推进至 PG 执行与子图
    snap = app.get_state(config)
    if snap.next == ("approval_gateway",):
        app.update_state(
            config,
            {"approval_status": "approved", "audit_trail": ["Approved for subgraph test"]},
            as_node="risk_assess"
        )
        res = await app.ainvoke(None, config)
    else:
        res = snap.values

    elapsed = time.time() - start_t

    # 1. 验证耗时：因为 summarize 内部有 2.0s 延时，全流程必须包含至少 1.8 秒耗时
    assert elapsed >= 1.8, f"Barrier 校验失败：执行过快 ({elapsed:.2f}s)，未能阻塞等待 2s summarize Worker！"

    # 2. 验证结果已被正确写回主图
    assert res.get("execution_result") is not None

    # 3. 物理隔离验证：检查主图 values 中绝不包含子图私有字段 internal_trace 与 audit_record
    assert "internal_trace" not in res, "泄漏隐患：子图私有字段 internal_trace 污染了主图 State！"
    assert "audit_record" not in res, "泄漏隐患：子图私有字段 audit_record 污染了主图 State！"
