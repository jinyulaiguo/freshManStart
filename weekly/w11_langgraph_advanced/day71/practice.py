"""Day 71 练习模版：人在回路 (HITL) 中断机制与断点控制

说明：
本文件为学员练习专用模版。请根据规范完成其中的 TODO 核心逻辑。
包含静态拓扑断点 (interrupt_before) 与动态条件中断 (interrupt()) 两个核心练习。
"""

import sys
from typing import Dict, Any, List, TypedDict
from typing_extensions import Annotated
import operator

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import interrupt, Command


# ============================================================================
# 状态契约定义
# ============================================================================

class HighRiskTaskState(TypedDict):
    """高风险任务状态契约"""
    task_id: str
    action_name: str
    amount: float
    target_user: str
    status: str
    logs: Annotated[List[str], operator.add]


# ============================================================================
# 任务 1：静态拓扑断点练习 (Static Interrupt-Before)
# ============================================================================

def prepare_task_node(state: HighRiskTaskState) -> Dict[str, Any]:
    """节点 1：准备任务 Payload"""
    print(f"[Practice] 准备高风险任务 Payload: {state['task_id']}")
    return {
        "status": "PREPARED",
        "logs": [f"Task {state['task_id']} prepared."]
    }


def execute_high_risk_node(state: HighRiskTaskState) -> Dict[str, Any]:
    """节点 2：高风险动作执行节点 (静态阻断节点)"""
    # TODO 1.1: 打印当前执行信息 (target_user, amount, status)
    # TODO 1.2: 返回状态更新，设置 status 为 "EXECUTED"，并在 logs 中追加一条日志
    raise NotImplementedError("TODO: 请实现 execute_high_risk_node 函数逻辑")


def build_static_practice_graph():
    """构建带静态阻断的 StateGraph"""
    builder = StateGraph(HighRiskTaskState)
    
    # TODO 1.3: 注册节点 "prepare" 和 "execute"
    # TODO 1.4: 添加边 START -> prepare -> execute -> END
    # TODO 1.5: 实例化 MemorySaver 并 compile，配置在 "execute" 节点之前触发表单阻断 (interrupt_before)
    raise NotImplementedError("TODO: 请实现 build_static_practice_graph 逻辑")


# ============================================================================
# 任务 2：动态节点内中断练习 (Dynamic Node Interrupt)
# ============================================================================

def dynamic_approval_node(state: HighRiskTaskState) -> Dict[str, Any]:
    """节点 1：动态风险评估与 interrupt() 拦截"""
    amount = state.get("amount", 0.0)
    print(f"[Practice] 评估操作风险，金额: ${amount:.2f}")
    
    # TODO 2.1: 判断如果 amount > 5000.0，则触发动态中断
    #   - 调用 interrupt({"warning": "RISK_EXCEEDED", "amount": amount})
    #   - 获取人类返回的 approval 字段 (APPROVED / REJECTED)
    #   - 如果 APPROVED，返回 status="APPROVED", logs 增加日志
    #   - 如果 REJECTED，返回 status="REJECTED", logs 增加日志
    # TODO 2.2: 如果 amount <= 5000.0，直接返回 status="AUTO_APPROVED"
    raise NotImplementedError("TODO: 请实现 dynamic_approval_node 逻辑")


def dynamic_execution_node(state: HighRiskTaskState) -> Dict[str, Any]:
    """节点 2：依据审批状态决定是否完成交付"""
    # TODO 2.3: 如果 status 属于 ["APPROVED", "AUTO_APPROVED"]，返回成功日志，否则返回终止日志
    raise NotImplementedError("TODO: 请实现 dynamic_execution_node 逻辑")


def build_dynamic_practice_graph():
    """构建动态中断 StateGraph"""
    # TODO 2.4: 构建 StateGraph，注册节点并 compile (绑定 MemorySaver)
    raise NotImplementedError("TODO: 请实现 build_dynamic_practice_graph 逻辑")


# ============================================================================
# 调试主入口 (带有友好的 TODO 拦截)
# ============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("🚀 Day 71 HITL 中断机制练习入口")
    print("=" * 60)
    
    # 静态断点练习验证
    print("\n[练习 1] 验证静态拓扑断点与 update_state...")
    try:
        static_app = build_static_practice_graph()
        config = {"configurable": {"thread_id": "prac_static_01"}}
        init_state = {
            "task_id": "TASK_001",
            "action_name": "DELETE_USER",
            "amount": 0.0,
            "target_user": "wrong_user",
            "status": "INIT",
            "logs": []
        }
        static_app.invoke(init_state, config)
        snapshot = static_app.get_state(config)
        print(f"✅ 挂起成功，当前待执行节点: {snapshot.next}")
    except NotImplementedError as e:
        print(f"💡 [TODO 提示] 静态断点练习未完成: {e}")
    except Exception as e:
        print(f"❌ 运行报错: {e}")
        
    # 动态中断练习验证
    print("\n[练习 2] 验证动态 interrupt() 与 Command(resume=...)...")
    try:
        dynamic_app = build_dynamic_practice_graph()
        config = {"configurable": {"thread_id": "prac_dynamic_01"}}
        init_state = {
            "task_id": "TASK_002",
            "action_name": "WIRE_TRANSFER",
            "amount": 8000.0,
            "target_user": "alice",
            "status": "INIT",
            "logs": []
        }
        dynamic_app.invoke(init_state, config)
        snapshot = dynamic_app.get_state(config)
        print(f"✅ 动态挂起成功，当前待执行节点: {snapshot.next}")
    except NotImplementedError as e:
        print(f"💡 [TODO 提示] 动态中断练习未完成: {e}")
    except Exception as e:
        print(f"❌ 运行报错: {e}")
