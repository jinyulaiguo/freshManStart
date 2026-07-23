"""条件边路由管理模块 (Day 77 状态驱动路由 - Safe/Sensitive 条件解耦与本轮成功判定)

设计方案与架构说明：
----------------------------------------------------------------
本模块集中管理主图内部的条件边 (Conditional Edges) 路由跳转决策逻辑。
1. `risk_routing_condition`:
   - "safe": 无敏感风险，直接路由至 "sql_execution" (0 拦截物理自动放行)。
   - "sensitive": 敏感修改/写操作 且未审批 -> 路由至 "approval_gateway" (该节点配置了 interrupt_before 断点)。
   - "approved" / "edited": 已经过人类安全员放行/修改 -> 路由至 "sql_execution"。
   - "blocked" / "rejected": 高危规则熔断或人类拒绝 -> 直接跳转至 "result" 节点。
2. `execution_routing_condition`:
   - 只要本轮 `execution_result` 在 PostgreSQL 沙箱中物理执行成功并产出结果，即使历史 log 中存在旧异常残留，依然准确分流至 "post_analysis" (并行分析子图)。
   - 执行异常/未放行空结果 -> 跳转至 "result" 节点。
"""

import os
import sys
from typing import Literal

# 动态将工作区根目录添加到 sys.path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../"))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from weekly.w11_langgraph_advanced.day77.state.main_state import SQLAgentState


def risk_routing_condition(state: SQLAgentState) -> Literal["sql_execution", "approval_gateway", "result"]:
    """基于风控判定与人类审批状态精细决定后续分支。"""
    risk_level = state.get("risk_level", "sensitive")
    approval_status = state.get("approval_status", "pending")

    # 1. 人类拒绝 -> 终止
    if approval_status == "rejected":
        print("  🔀 [Route Decision] 审批状态为 'rejected' -> 跳转至 'result'")
        return "result"

    # 2. 高危熔断 -> 阻断
    if risk_level == "blocked":
        print("  🔀 [Route Decision] 风控等级为 'blocked' -> 直接阻断跳转至 'result'")
        return "result"

    # 3. 人类已放行/已编辑修正 -> 允许物理执行
    if approval_status in ["approved", "edited"]:
        print(f"  🔀 [Route Decision] 审批状态为 '{approval_status}' -> 允许放行至 'sql_execution'")
        return "sql_execution"

    # 4. Safe 只读查询 -> 自动放行 (不通过审批网关)
    if risk_level == "safe":
        print("  🔀 [Route Decision] 风控等级为 'safe' -> 自动放行至 'sql_execution' (不触发 HITL 挂起)")
        return "sql_execution"

    # 5. Sensitive 敏感操作 且处于 pending 状态 -> 走向 Approval Gateway 挂起断点
    print("  🔀 [Route Decision] 风控等级为 'sensitive' 且未审批 -> 路由至 'approval_gateway' 触发 HITL 阻断挂起")
    return "approval_gateway"


def execution_routing_condition(state: SQLAgentState) -> Literal["post_analysis", "result"]:
    """基于本轮 PG 物理执行结果精准决定后续路由。"""
    exec_res = state.get("execution_result")

    # 只要本轮 PG 物理执行成功且输出了结果 (非 None)，即代表本轮执行成功，放行进入分析子图！
    if exec_res is not None:
        print("  🔀 [Route Decision] 本轮 PG 执行成功 -> 挂载进入 'post_analysis' 并行分析子图")
        return "post_analysis"

    print("  🔀 [Route Decision] 执行存在错误/空结果 -> 跳转至 'result'")
    return "result"
