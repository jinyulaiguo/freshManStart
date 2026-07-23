"""主图拼装与编排模块 (Day 77 核心编排引擎 - 精确 HITL 门禁网关)

设计方案与架构说明：
----------------------------------------------------------------
本模块负责组装与编译 SQL Agent 主控制流拓扑图。
1. 精确 HITL 人工介入断点 (Targeted HITL Gateway):
   - 注册 `approval_gateway` 门禁节点，配置 `interrupt_before=["approval_gateway"]`。
   - 当 `risk_assessment_node` 判明 SQL 为 "safe" 时，跳过门禁网关直接流转至 "sql_execution"，实现 0 拦截物理自动放行。
   - 仅当 SQL 为 "sensitive" 且待审批时，控制流精准路由至 "approval_gateway" 触发断点挂起存盘！
2. 子图嵌套 (Subgraph Integration):
   - 将 compiled 的 `AnalysisSubState` 分析子图作为独立 Node 挂载至 "post_analysis" 位置。
3. 自定义 Checkpointer 绑定:
   - 默认绑定 `ProductionRedisCheckpointer` 支撑跨进程持久化与 Time Travel 分叉。

拓扑结构：
----------
[START] -> sql_generation -> risk_assess -> (条件路由) ──┬─► (safe / approved) ───────────────────────────► sql_execution ──► (条件路由) ──┬─► post_analysis ──► result ──► [END]
                                                          ├─► (sensitive) ──► ⛔ approval_gateway ⛔ ────────┤                                   │
                                                          └─► (blocked/rejected) ──────────────────────────┴──────────────────────────────────┴─► result ─────────┘
"""

import os
import sys
from typing import Optional, Dict, Any

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.base import BaseCheckpointSaver

# 动态将工作区根目录添加到 sys.path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../"))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from weekly.w11_langgraph_advanced.day77.state.main_state import SQLAgentState
from weekly.w11_langgraph_advanced.day77.nodes import (
    sql_generation_node,
    risk_assessment_node,
    sql_execution_node,
    result_node,
)
from weekly.w11_langgraph_advanced.day77.subgraph import build_analysis_subgraph
from weekly.w11_langgraph_advanced.day77.graph.routing import (
    risk_routing_condition,
    execution_routing_condition,
)
from weekly.w11_langgraph_advanced.day77.checkpoint.redis_checkpointer import ProductionRedisCheckpointer


def approval_gateway_node(state: SQLAgentState) -> Dict[str, Any]:
    """HITL 审批门禁节点：仅作为 Sensitive 操作的中断存盘挂起锚点。"""
    return {
        "audit_trail": ["HITL approval gateway engaged for sensitive SQL operation."]
    }


def build_sql_agent_graph(checkpointer: Optional[BaseCheckpointSaver] = None):
    """构建并编译 SQL Agent 状态图。
    
    Args:
        checkpointer: 自定义 Checkpointer 句柄。若为 None，默认实例化 ProductionRedisCheckpointer。
        
    Returns:
        CompiledStateGraph: 可执行与挂起解冻的 Compiled 图对象。
    """
    if checkpointer is None:
        checkpointer = ProductionRedisCheckpointer()

    builder = StateGraph(SQLAgentState)

    # 1. 注册主节点
    builder.add_node("sql_generation", sql_generation_node)
    builder.add_node("risk_assess", risk_assessment_node)
    builder.add_node("approval_gateway", approval_gateway_node)
    builder.add_node("sql_execution", sql_execution_node)
    builder.add_node("result", result_node)

    # 2. 挂载嵌套分析子图
    analysis_subgraph = build_analysis_subgraph()
    builder.add_node("post_analysis", analysis_subgraph)

    # 3. 构造基础连线
    builder.add_edge(START, "sql_generation")
    builder.add_edge("sql_generation", "risk_assess")
    builder.add_edge("approval_gateway", "sql_execution")

    # 4. 构造条件边路由
    builder.add_conditional_edges(
        "risk_assess",
        risk_routing_condition,
        {
            "sql_execution": "sql_execution",
            "approval_gateway": "approval_gateway",
            "result": "result"
        }
    )

    builder.add_conditional_edges(
        "sql_execution",
        execution_routing_condition,
        {
            "post_analysis": "post_analysis",
            "result": "result"
        }
    )

    builder.add_edge("post_analysis", "result")
    builder.add_edge("result", END)

    # 5. 绑定持久化 Checkpointer 并配置仅在 "approval_gateway" 敏感网关前打断挂起！
    return builder.compile(
        checkpointer=checkpointer,
        interrupt_before=["approval_gateway"]  # 精确敏感断点！
    )
