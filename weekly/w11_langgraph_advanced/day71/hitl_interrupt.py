"""企业级人在回路 (Human-in-the-Loop, HITL) 安全审计与断点控制引擎 (Day 71 参考标准答案)

设计方案与架构说明：
----------------------------------------------------------------
本模块旨在提供生产级 Agent 高风险操作（如高额转账、商业邮件发送）的安全拦截屏障。
基于 LangGraph 状态图框架，物理隔离演示了静态拓扑断点与动态条件中断两套范式：

1. 范式一：静态拓扑断点 (Static Interrupt-Before Barrier)
   - 在 compile 阶段硬编码拦截 target 节点 (`interrupt_before=["send_email"]`)。
   - 图流转到该节点前强制挂起，控制权返回调用方。外部调用 update_state 修正后恢复流转。

2. 范式二：动态节点内中断 (Dynamic Node Interrupt)
   - 在节点内部基于风险指标（如金额 > 10,000）调用 `interrupt()` 挂起。
   - 外部传入 `Command(resume=...)` 注入审核决定，图原位从中断处缝合恢复。

结构与数据流：
--------------
AgentState (TypedDict) -> [risk_assessment_node] -> (分支判定) -> [send_email_node] -> END
"""

import sys
from typing import Dict, Any, List, TypedDict, Literal
from typing_extensions import Annotated
import operator

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import interrupt, Command


# ============================================================================
# 状态契约定义 (State Schemas)
# ============================================================================

class RiskAuditState(TypedDict):
    """高风险操作安全审计状态字典。
    
    Attributes:
        task_id: 业务任务唯一 ID
        action_type: 操作类型 (如 "SEND_EMAIL", "TRANSFER_MONEY")
        amount: 涉案金额 (USD)
        recipient: 接收方地址/账号
        content: 风险操作内容描述
        audit_status: 审计状态 ("PENDING", "APPROVED", "REJECTED", "MODIFIED")
        audit_log: 审计日志链
    """
    task_id: str
    action_type: str
    amount: float
    recipient: str
    content: str
    audit_status: str
    audit_log: Annotated[List[str], operator.add]


# ============================================================================
# 方案一：静态拓扑断点机制 (Static Interrupt-Before Pattern)
# ============================================================================

def static_draft_node(state: RiskAuditState) -> Dict[str, Any]:
    """业务拟定节点：生成待发送的商业邮件/指令 Payload。"""
    print(f"\n[Static Workflow] 步骤1: 拟定高风险任务 Payload ({state['task_id']})")
    return {
        "audit_status": "DRAFTED",
        "audit_log": [f"Task {state['task_id']} drafted for recipient {state['recipient']}."]
    }


def static_send_email_node(state: RiskAuditState) -> Dict[str, Any]:
    """高风险邮件发送节点：此节点在前置编译时配置了 interrupt_before 阻断。"""
    print(f"\n[Static Workflow] 步骤2: 正在执行高风险邮件发送...")
    print(f"  -> 收件人: {state['recipient']}")
    print(f"  -> 内容: {state['content']}")
    print(f"  -> 审计状态: {state['audit_status']}")
    
    return {
        "audit_status": "COMPLETED",
        "audit_log": [f"Email successfully sent to {state['recipient']}."]
    }


def build_static_hitl_graph():
    """构建带静态拓扑断点的 StateGraph。"""
    builder = StateGraph(RiskAuditState)
    
    # 1. 注册节点
    builder.add_node("draft_node", static_draft_node)
    builder.add_node("send_email", static_send_email_node)
    
    # 2. 构建拓扑边
    builder.add_edge(START, "draft_node")
    builder.add_edge("draft_node", "send_email")
    builder.add_edge("send_email", END)
    
    # 3. 绑定持久化 Checkpointer 并配置静态拦截器
    checkpointer = MemorySaver()
    app = builder.compile(
        checkpointer=checkpointer,
        interrupt_before=["send_email"]  # 强制在 send_email 前挂起
    )
    return app


# ============================================================================
# 方案二：动态条件中断机制 (Dynamic Node Interrupt Pattern)
# ============================================================================

def dynamic_risk_eval_node(state: RiskAuditState) -> Dict[str, Any]:
    """动态风险评估节点：当转账金额高于 $10,000 时，动态调用 interrupt() 触发阻断。"""
    print(f"\n[Dynamic Workflow] 评估操作风险... 金额: ${state['amount']:.2f}")
    
    # 步骤 1: 检查动态触发条件
    if state["amount"] > 10000.0:
        print(f"  ⚠️ 警告: 金额 ${state['amount']} 超过安全阈值 ($10,000)，触发动态挂起中断！")
        
        # 步骤 2: 调用 interrupt() 冻结当前帧并呈报外部 Payload
        # interrupt() 会抛出特制异常中断执行，恢复时其返回值即为 Command(resume=...) 传入的数据
        approval_response = interrupt({
            "warning": "HIGH_VALUE_TRANSFER_RISK",
            "amount": state["amount"],
            "recipient": state["recipient"],
            "prompt": "请审核此笔大额转账请求 (APPROVED / REJECTED)"
        })
        
        # 步骤 3: 提取 Resume 注入的人工决策数据
        print(f"  收到人工审核结果反馈: {approval_response}")
        decision = approval_response.get("decision", "REJECTED")
        reason = approval_response.get("reason", "No reason provided.")
        
        if decision == "APPROVED":
            return {
                "audit_status": "APPROVED",
                "audit_log": [f"Dynamic audit APPROVED by human. Reason: {reason}"]
            }
        else:
            return {
                "audit_status": "REJECTED",
                "audit_log": [f"Dynamic audit REJECTED by human. Reason: {reason}"]
            }
            
    # 金额在安全阈值内，直接批准
    return {
        "audit_status": "AUTO_APPROVED",
        "audit_log": ["Amount within safe limit. Auto approved."]
    }


def dynamic_execution_node(state: RiskAuditState) -> Dict[str, Any]:
    """终极动作执行节点。"""
    if state["audit_status"] in ["APPROVED", "AUTO_APPROVED"]:
        print(f"  ✅ 执行成功: 已向 {state['recipient']} 转账 ${state['amount']}")
        return {"audit_log": [f"Transferred ${state['amount']} to {state['recipient']}."]}
    else:
        print(f"  ❌ 执行终止: 审计未通过 (当前状态: {state['audit_status']})")
        return {"audit_log": ["Transaction aborted due to failed audit."]}


def build_dynamic_hitl_graph():
    """构建带动态节点中断的 StateGraph。"""
    builder = StateGraph(RiskAuditState)
    
    builder.add_node("eval_risk", dynamic_risk_eval_node)
    builder.add_node("execute_transfer", dynamic_execution_node)
    
    builder.add_edge(START, "eval_risk")
    builder.add_edge("eval_risk", "execute_transfer")
    builder.add_edge("execute_transfer", END)
    
    checkpointer = MemorySaver()
    return builder.compile(checkpointer=checkpointer)


# ============================================================================
# 主运行验证程序 (Main Execution Suite)
# ============================================================================

def run_static_demo():
    """演示静态 interrupt_before 的挂起、状态读取、update_state 干预与恢复全流转。"""
    print("=" * 70)
    print(">>> 演示 1：静态拓扑断点 (interrupt_before) 与人工状态修正")
    print("=" * 70)
    
    app = build_static_hitl_graph()
    config = {"configurable": {"thread_id": "static_thread_001"}}
    
    initial_state = {
        "task_id": "EMAIL_9981",
        "action_type": "SEND_EMAIL",
        "amount": 0.0,
        "recipient": "wrong_recipient@example.com",  # 故意填错
        "content": "含有敏感财务信息的终版合同数据",
        "audit_status": "INIT",
        "audit_log": []
    }
    
    # 步骤 1: 第一次运行图，将在 send_email 前自动打断挂起
    print("\n--- 阶段 A: 启动图运行 ---")
    events = app.invoke(initial_state, config)
    
    # 步骤 2: 查验当前快照 (StateSnapshot)
    snapshot = app.get_state(config)
    print("\n--- 阶段 B: 图已挂起，查看 StateSnapshot ---")
    print(f"  • 待执行节点 (snapshot.next): {snapshot.next}")
    print(f"  • 当前已知状态 recipient: {snapshot.values.get('recipient')}")
    print(f"  • 当前状态 audit_status: {snapshot.values.get('audit_status')}")
    
    # 断言确认：图确实在 send_email 前阻断了
    assert snapshot.next == ("send_email",), "静态断点失败：未能准确在 send_email 之前阻断！"
    
    # 步骤 3: 人工干预 - 通过 update_state 修改收件人地址与审批状态
    print("\n--- 阶段 C: 人工审计介入，发现收件人错误，修正参数并批准 ---")
    app.update_state(
        config,
        {
            "recipient": "correct_ceo@enterprise.com",
            "audit_status": "MANUALLY_APPROVED",
            "audit_log": ["Human auditor changed recipient to correct_ceo@enterprise.com and approved."]
        }
    )
    
    # 再次检查 snapshot 确认 update_state 覆写成功
    snapshot_after_update = app.get_state(config)
    print(f"  • 修正后的 recipient: {snapshot_after_update.values.get('recipient')}")
    
    # 步骤 4: 恢复运行 (Pass None as input to resume from checkpoint)
    print("\n--- 阶段 D: 从断点恢复执行图 ---")
    final_output = app.invoke(None, config)
    
    print("\n--- 阶段 E: 图执行完毕，最终状态如下 ---")
    print(f"  • 最终状态 audit_status: {final_output['audit_status']}")
    print(f"  • 最终日志链 audit_log:")
    for log in final_output["audit_log"]:
        print(f"      - {log}")


def run_dynamic_demo():
    """演示动态 interrupt() 触发、Payload 获取与 Command(resume=...) 注入。"""
    print("\n" + "=" * 70)
    print(">>> 演示 2：动态节点内断点 (interrupt()) 与 Command(resume=...) 恢复")
    print("=" * 70)
    
    app = build_dynamic_hitl_graph()
    config = {"configurable": {"thread_id": "dynamic_thread_002"}}
    
    high_value_transfer = {
        "task_id": "TRANS_8820",
        "action_type": "TRANSFER_MONEY",
        "amount": 50000.0,  # 故意填入 $50,000 触发动态中断
        "recipient": "vendor_account_998@bank.com",
        "content": "大额设备采购款",
        "audit_status": "INIT",
        "audit_log": []
    }
    
    # 步骤 1: 运行图，动态风险评估节点抛出 interrupt()
    print("\n--- 阶段 A: 发起 $50,000 大额转账任务 ---")
    app.invoke(high_value_transfer, config)
    
    # 步骤 2: 查看挂起的 snapshot 与 tasks 中的 interrupt payload
    snapshot = app.get_state(config)
    print("\n--- 阶段 B: 图已动态挂起，检索安全告警 Payload ---")
    print(f"  • 待执行节点 (snapshot.next): {snapshot.next}")
    
    # 从 tasks 中提取 interrupt 暴露的问询字典
    pending_tasks = snapshot.tasks
    if pending_tasks and pending_tasks[0].interrupts:
        interrupt_payload = pending_tasks[0].interrupts[0].value
        print(f"  • 拦截警告 Payload: {interrupt_payload}")
    
    # 步骤 3: 使用 Command(resume=...) 注入人工审核同意结果
    print("\n--- 阶段 C: 人工审计介入，传入 Command(resume=...) 解冻 ---")
    resume_command = Command(
        resume={
            "decision": "APPROVED",
            "reason": "已校验采购合同无误，批准放行。"
        }
    )
    
    # 传入 Command(resume=...) 恢复图运行
    final_output = app.invoke(resume_command, config)
    
    print("\n--- 阶段 D: 动态流程终局结果 ---")
    print(f"  • 审计状态: {final_output['audit_status']}")
    print(f"  • 审计日志:")
    for log in final_output["audit_log"]:
        print(f"      - {log}")


if __name__ == "__main__":
    run_static_demo()
    run_dynamic_demo()
