"""工具调用人工审批与运行时拦截重写 (Day 72 参考标准答案)

设计方案与架构说明：
----------------------------------------------------------------
本模块演示了工业级 Agent 系统中针对 LLM 生成的工具参数进行“人工拦截与原位重写”的核心范式。
当 LLM 决策生成错误的工具参数（如错误的 `user_id` 或危险的 SQL 参数）时：
1. 拓扑级拦截：在 `tools` 节点执行前配置 `interrupt_before=["tools"]` 强制冻结。
2. 快照提取与覆写：读取 `snapshot.values["messages"][-1]` 中的 `AIMessage`，保持 `tool_call_id` 不变，精确定制重写 `args` 字典。
3. `as_node` 挂载：使用 `graph.update_state(config, {"messages": [updated_ai_msg]}, as_node="agent")` 挂载。
4. 原位解冻：调用 `app.invoke(None, config)`，控制流无需重新调用大模型，直接由 ToolNode 拿纠偏后的参数执行查询。

结构与数据流：
--------------
AgentState -> [agent_node] -> (interrupt_before) -> [tool_node] -> END
"""

import sys
from typing import Dict, Any, List, TypedDict, Optional
from typing_extensions import Annotated
import operator

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver


# ============================================================================
# 模拟数据库与状态契约
# ============================================================================

# 模拟客服后台订单数据库
MOCK_DATABASE = {
    "USR_1001": [
        {"order_id": "ORD_2026_A1", "product": "AI Agent 进阶课", "amount": 299.0},
        {"order_id": "ORD_2026_A2", "product": "Python 异步并发实战", "amount": 199.0}
    ],
    "USR_1002": [
        {"order_id": "ORD_2026_B1", "product": "LLM 架构设计指南", "amount": 399.0}
    ]
}


class AgentCustomerServiceState(TypedDict):
    """客服 Agent 状态字典契约。
    
    Attributes:
        messages: 消息日志链
        audit_log: 人工干预与拦截审计日志
    """
    messages: Annotated[List[BaseMessage], operator.add]
    audit_log: Annotated[List[str], operator.add]


# ============================================================================
# 图节点定义 (Node Implementations)
# ============================================================================

def agent_decision_node(state: AgentCustomerServiceState) -> Dict[str, Any]:
    """Agent 决策节点：模拟 LLM 接收用户提问并决策调用 `query_user_orders` 工具。
    这里故意模拟 LLM 产生幻觉生成了错误的 user_id: 'ERR_9999'。
    """
    print("\n[Node: Agent] LLM 正在推演决策...")
    
    # 模拟大模型生成的带有错误参数的 Tool Call
    faulty_tool_call = {
        "name": "query_user_orders",
        "args": {"user_id": "ERR_9999", "limit": 10},  # 故意填错的 ID
        "id": "call_mock_id_7788"
    }
    
    ai_message = AIMessage(
        content="我将为您查询用户订单信息。",
        tool_calls=[faulty_tool_call]
    )
    
    return {
        "messages": [ai_message],
        "audit_log": [f"Agent 决策生成工具调用: name={faulty_tool_call['name']}, args={faulty_tool_call['args']}"]
    }


def customer_tool_execution_node(state: AgentCustomerServiceState) -> Dict[str, Any]:
    """工具执行节点：提取最新的 AIMessage.tool_calls 并执行数据库查询。"""
    print("\n[Node: Tools] 正在执行工具查询...")
    
    last_message = state["messages"][-1]
    if not isinstance(last_message, AIMessage) or not last_message.tool_calls:
        return {"audit_log": ["ToolNode 错误: 未能在最新消息中匹配到 tool_calls"]}
        
    tool_call = last_message.tool_calls[0]
    user_id = tool_call["args"].get("user_id")
    call_id = tool_call["id"]
    
    print(f"  -> 工具执行参数 user_id: '{user_id}' (Call ID: {call_id})")
    
    # 从模拟数据库检索
    if user_id in MOCK_DATABASE:
        orders = MOCK_DATABASE[user_id]
        result_str = f"成功查获用户 {user_id} 的订单: {orders}"
        print(f"  -> {result_str}")
    else:
        result_str = f"查询失败: 数据库中未找到用户 ID '{user_id}'"
        print(f"  ⚠️ {result_str}")
        
    tool_message = ToolMessage(
        content=result_str,
        tool_call_id=call_id
    )
    
    return {
        "messages": [tool_message],
        "audit_log": [f"ToolNode 执行完成: user_id={user_id}"]
    }


# ============================================================================
# 构建编排图 (Graph Assembly)
# ============================================================================

def build_tool_approval_graph():
    """构建支持工具参数拦截重写的 StateGraph 流程图。"""
    builder = StateGraph(AgentCustomerServiceState)
    
    # 1. 注册节点
    builder.add_node("agent", agent_decision_node)
    builder.add_node("tools", customer_tool_execution_node)
    
    # 2. 构建连线
    builder.add_edge(START, "agent")
    builder.add_edge("agent", "tools")
    builder.add_edge("tools", END)
    
    # 3. 绑定 MemorySaver 并配置在 "tools" 节点前挂起拦截
    checkpointer = MemorySaver()
    app = builder.compile(
        checkpointer=checkpointer,
        interrupt_before=["tools"]  # 在工具执行前打断挂起
    )
    return app


# ============================================================================
# 主运行验证程序 (Main Execution Suite)
# ============================================================================

def main():
    print("=" * 70)
    print("🚀 Day 72: 工具调用人工审批与运行时拦截重写实战")
    print("=" * 70)
    
    app = build_tool_approval_graph()
    config = {"configurable": {"thread_id": "tool_intercept_thread_101"}}
    
    # 初始用户输入
    initial_state = {
        "messages": [HumanMessage(content="帮我查一下用户 USR_1001 的订单记录。")],
        "audit_log": ["初始化用户请求"]
    }
    
    # ------------------------------------------------------------------------
    # 阶段 1: 首次启动图推演，将在 tools 节点前打断
    # ------------------------------------------------------------------------
    print("\n--- 阶段 A: 启动 Agent 决策节点 ---")
    app.invoke(initial_state, config)
    
    # 检查当前挂起快照
    snapshot = app.get_state(config)
    print("\n--- 阶段 B: 图已进入中断挂起状态 ---")
    print(f"  • 当前待执行节点 (snapshot.next): {snapshot.next}")
    
    # 提取最新的 AIMessage 查看大模型生成的错误参数
    last_ai_msg = snapshot.values["messages"][-1]
    faulty_args = last_ai_msg.tool_calls[0]["args"]
    tool_call_id = last_ai_msg.tool_calls[0]["id"]
    print(f"  • 捕获 LLM 决策出的工具参数: {faulty_args}")
    
    # 断言确认：图应该处于 tools 挂起状态
    assert snapshot.next == ("tools",), "错误：未能成功在 tools 节点前触发挂起阻断！"
    
    # ------------------------------------------------------------------------
    # 阶段 2: 人工审计介入，发现 user_id 错误，进行原位参数重写
    # ------------------------------------------------------------------------
    print("\n--- 阶段 C: 人工审计发现参数错误 ('ERR_9999')，进行原位重写 ---")
    
    # 构造修正后的 tool_calls 字典 (保持相同的 tool_call_id)
    corrected_tool_call = {
        "name": last_ai_msg.tool_calls[0]["name"],
        "args": {"user_id": "USR_1001", "limit": 5},  # 将 ERR_9999 修正为 USR_1001
        "id": tool_call_id
    }
    
    # 创建新的 AIMessage 对象
    corrected_ai_msg = AIMessage(
        content=last_ai_msg.content,
        tool_calls=[corrected_tool_call],
        id=last_ai_msg.id
    )
    
    # 通过 update_state 覆盖 messages，且关键必须指定 as_node="agent"
    print(f"  -> 执行 update_state(config, patch, as_node='agent')...")
    app.update_state(
        config,
        {
            "messages": [corrected_ai_msg],
            "audit_log": [f"Human auditor corrected tool_calls args from '{faulty_args}' to '{corrected_tool_call['args']}'"]
        },
        as_node="agent"
    )
    
    # 重新核查 snapshot
    snapshot_after_update = app.get_state(config)
    updated_args = snapshot_after_update.values["messages"][-1].tool_calls[0]["args"]
    print(f"  • 验证覆写后的工具参数: {updated_args}")
    assert updated_args == {"user_id": "USR_1001", "limit": 5}, "覆写失败：工具参数未成功更新！"
    
    # ------------------------------------------------------------------------
    # 阶段 3: 恢复执行 (Pass None) 解冻控制流
    # ------------------------------------------------------------------------
    print("\n--- 阶段 D: 解冻恢复控制流 (Pass None) 并由 ToolNode 执行 ---")
    final_output = app.invoke(None, config)
    
    # 验证最终执行结果
    print("\n--- 阶段 E: 图执行完毕，核查最终状态输出 ---")
    final_tool_msg = final_output["messages"][-1]
    print(f"  • 最终 ToolMessage 内容: {final_tool_msg.content}")
    print(f"  • 完整审计日志链 (audit_log):")
    for log in final_output["audit_log"]:
        print(f"      - {log}")
        
    # 断言确认成功查获数据
    assert "ORD_2026_A1" in final_tool_msg.content, "最终验证失败：ToolNode 未能查获正确用户的数据！"
    print("\n✅ 全流程自动化测试过关验证通过！")


if __name__ == "__main__":
    main()
