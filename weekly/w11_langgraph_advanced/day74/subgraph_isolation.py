"""子图（Subgraph）状态隔离与并发子流程设计 (Day 74 参考标准答案)

设计方案与架构说明：
----------------------------------------------------------------
本模块演示了工业级 Agent 系统中利用子图 (Subgraph) 进行“状态隔离与受限数据映射”的架构模式。
在电商主订单处理系统中：
1. 主图 ParentGraph：处理用户下单、收货地址与退款申请分退。主图状态 `ParentOrderState` 包含全局订单数据。
2. 退款子图 RefundChildGraph：处理繁复的退款逻辑（银行接口重试、反欺诈风控校验）。子图状态 `ChildRefundState` 包含局部高频日志 `internal_logs` 与重试计数 `retry_count`。
3. 状态隔离机制：子图内部产生的多轮高频日志绝不泄漏至主图 `ParentOrderState`；退款完成后，仅将退款结果 `refund_status` 与 `transaction_id` 映射写入主图。

结构与数据流：
--------------
ParentGraph [START] -> process_order -> [RefundChildGraph Node] -> finalize_order -> [END]
"""

import sys
from typing import Dict, Any, List, TypedDict, Optional
from typing_extensions import Annotated
import operator

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver


# ============================================================================
# 1. 契约定义：主图状态 vs 子图隔离状态
# ============================================================================

class ParentOrderState(TypedDict):
    """主图订单处理全局状态。
    
    Attributes:
        order_id: 订单唯一编号
        customer_id: 客户 ID
        total_amount: 订单金额
        refund_status: 退款结果 (由子图写回)
        transaction_id: 退款交易号 (由子图写回)
        main_logs: 主图全局日志链
    """
    order_id: str
    customer_id: str
    total_amount: float
    refund_status: str
    transaction_id: str
    main_logs: Annotated[List[str], operator.add]


# 子图专用状态 (输入/输出/内部私有变量)
class ChildRefundInputState(TypedDict):
    order_id: str
    total_amount: float


class ChildRefundOutputState(TypedDict):
    refund_status: str
    transaction_id: str


class ChildRefundState(ChildRefundInputState, ChildRefundOutputState):
    """子图内部完整状态：包含私有的高频重试与内部诊断日志，绝对不污染主图。"""
    internal_logs: List[str]
    retry_count: int


# ============================================================================
# 2. 构建退款子图 (Child Graph Implementation)
# ============================================================================

def child_risk_check_node(state: ChildRefundState) -> Dict[str, Any]:
    """子图节点 1: 反欺诈风控校验。"""
    print(f"\n  [Subgraph Node 1: Risk] 执行退款风控核查 (order_id: {state['order_id']})...")
    logs = [f"Risk check passed for amount ${state['total_amount']}"]
    return {
        "internal_logs": logs,
        "retry_count": 1
    }


def child_bank_gateway_node(state: ChildRefundState) -> Dict[str, Any]:
    """子图节点 2: 调用第三方银行接口退款 (模拟高频内部重试)。"""
    print(f"  [Subgraph Node 2: Bank] 调用底层银行退款 Gateway...")
    
    # 模拟子图内部高频重试产生的私有数据
    internal_trace = [
        "Bank Gateway attempt 1: latency 120ms",
        "Bank Gateway attempt 2: connection reset, retrying",
        "Bank Gateway attempt 3: SUCCESS"
    ]
    
    return {
        "refund_status": "REFUNDED_SUCCESS",
        "transaction_id": f"TX_BANK_{state['order_id']}_8899",
        "internal_logs": state.get("internal_logs", []) + internal_trace,
        "retry_count": state.get("retry_count", 1) + 2
    }


def build_refund_subgraph():
    """构建独立可运行的退款子图。"""
    builder = StateGraph(ChildRefundState)
    
    builder.add_node("risk_check", child_risk_check_node)
    builder.add_node("bank_gateway", child_bank_gateway_node)
    
    builder.add_edge(START, "risk_check")
    builder.add_edge("risk_check", "bank_gateway")
    builder.add_edge("bank_gateway", END)
    
    # 编译子图 (显式声明 input 与 output state 过滤)
    return builder.compile()


# ============================================================================
# 3. 构建主图 (Parent Graph Implementation)
# ============================================================================

def parent_process_order_node(state: ParentOrderState) -> Dict[str, Any]:
    """主图节点 1: 解析主订单并准备发起退款流程。"""
    print(f"\n[Parent Node 1: Process] 处理主订单 {state['order_id']}...")
    return {
        "main_logs": [f"Order {state['order_id']} initiated for customer {state['customer_id']}."]
    }


def parent_finalize_order_node(state: ParentOrderState) -> Dict[str, Any]:
    """主图节点 2: 汇总退款结果并更新主订单库。"""
    print(f"\n[Parent Node 2: Finalize] 汇总子图返回结果...")
    print(f"  -> 退款状态: {state.get('refund_status')}")
    print(f"  -> 交易编号: {state.get('transaction_id')}")
    
    return {
        "main_logs": [f"Order finalize complete. Refund Status: {state.get('refund_status')}"]
    }


def build_parent_graph():
    """构建包含退款子图的主图。"""
    parent_builder = StateGraph(ParentOrderState)
    
    # 1. 实例化退款子图
    refund_child_app = build_refund_subgraph()
    
    # 2. 注册主图节点，并将子图 compiled app 直接作为 Node 绑定
    parent_builder.add_node("process_order", parent_process_order_node)
    parent_builder.add_node("refund_subgraph", refund_child_app)  # 嵌套子图！
    parent_builder.add_node("finalize_order", parent_finalize_order_node)
    
    # 3. 构建主图边
    parent_builder.add_edge(START, "process_order")
    parent_builder.add_edge("process_order", "refund_subgraph")
    parent_builder.add_edge("refund_subgraph", "finalize_order")
    parent_builder.add_edge("finalize_order", END)
    
    checkpointer = MemorySaver()
    return parent_builder.compile(checkpointer=checkpointer)


# ============================================================================
# 4. 主运行验证程序 (Main Execution Suite)
# ============================================================================

def main():
    print("=" * 70)
    print("🚀 Day 74: 子图（Subgraph）状态隔离与受限数据映射实战")
    print("=" * 70)
    
    parent_app = build_parent_graph()
    config = {"configurable": {"thread_id": "parent_thread_99001"}}
    
    initial_order_state = {
        "order_id": "ORD_REFUND_2026_09",
        "customer_id": "CUST_ALICE_88",
        "total_amount": 499.0,
        "refund_status": "PENDING",
        "transaction_id": "NONE",
        "main_logs": []
    }
    
    # 运行主图
    print("\n--- 阶段 A: 执行包含退款子图的主工作流 ---")
    final_state = parent_app.invoke(initial_order_state, config)
    
    print("\n--- 阶段 B: 验证主图与子图的状态隔离 ---")
    print(f"  • 主图最终 refund_status: {final_state.get('refund_status')}")
    print(f"  • 主图最终 transaction_id: {final_state.get('transaction_id')}")
    
    # 断言 1: 验证子图结果已被正确合入主图
    assert final_state["refund_status"] == "REFUNDED_SUCCESS", "隔离验证失败：子图退款结果未合入主图！"
    assert "TX_BANK_" in final_state["transaction_id"], "隔离验证失败：交易号未写入主图！"
    
    # 断言 2: 验证子图私有内部字段 (internal_logs, retry_count) 未泄露至主图 ParentState
    print(f"  • 检查主图是否存在子图私有字段 'internal_logs': { 'internal_logs' in final_state }")
    print(f"  • 检查主图是否存在子图私有字段 'retry_count': { 'retry_count' in final_state }")
    
    assert "internal_logs" not in final_state, "物理泄露：子图私有字段 internal_logs 污染了主图 State！"
    assert "retry_count" not in final_state, "物理泄露：子图私有字段 retry_count 污染了主图 State！"
    
    print(f"\n  • 主图日志链 (main_logs):")
    for log in final_state["main_logs"]:
        print(f"      - {log}")
        
    print("\n✅ 全流程子图状态隔离与受限数据映射验证通过！")


if __name__ == "__main__":
    main()
