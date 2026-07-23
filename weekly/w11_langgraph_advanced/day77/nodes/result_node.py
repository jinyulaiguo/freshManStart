"""结果格式化节点 (Day 77 主图收尾 - 支持高危拦截与审批拒绝友好总结)

设计方案与架构说明：
----------------------------------------------------------------
本节点负责将执行结果或子图汇总结果，格式化为友好的终端/UI 文本响应。
优先判断高危 blocked 拦截与人类 rejected 拒绝状态，防止拉取历史 error_log 残留造成误导。

数据流：
--------
Input (execution_result, risk_level, approval_status, audit_trail) -> 格式化响应 -> 结束流程
"""

import os
import sys
from typing import Dict, Any

# 动态将工作区根目录添加到 sys.path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../"))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from weekly.w11_langgraph_advanced.day77.state.main_state import SQLAgentState


async def result_node(state: SQLAgentState) -> Dict[str, Any]:
    """主图节点：格式化输出响应。"""
    print(f"\n[Node: Result] 正在汇总最终结果...")
    exec_res = state.get("execution_result")
    errors = state.get("error_log", [])
    risk_level = state.get("risk_level")
    approval_status = state.get("approval_status")

    if risk_level == "blocked":
        summary_msg = "⛔ 高危拦截防护: 检测到全表无条件删除/破坏性操作，系统已物理切断执行路径。"
    elif approval_status == "rejected":
        summary_msg = "❌ 人类审批拒绝: 安全员拒绝放行该敏感 SQL 的物理执行。"
    elif exec_res is not None:
        summary_msg = f"🎉 任务顺利完成! 检索/影响数据: {len(exec_res)} 条记录。"
    elif errors:
        summary_msg = f"❌ 任务执行出现异常 (共 {len(errors)} 条错误记录): {errors[-1]}"
    else:
        summary_msg = "⚠️ 任务结束，未执行物理 Query。"

    print(f"  • {summary_msg}")

    return {
        "audit_trail": [f"Result Node summary: {summary_msg}"]
    }
