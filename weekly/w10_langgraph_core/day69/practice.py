"""Day 69 练习：架构师级内存校验器 (MemorySaver) 与持久化状态机

===================================================================================
架构设计说明 (Architectural Overview):
===================================================================================
1. 业务场景 (Business Domain):
   本练习基于“多租户企业级代码安全审计助手”真实场景。
   不同企业租户 (Tenant Alpha 与 Tenant Beta) 并发向系统提交安全扫描请求，
   系统需要通过 `MemorySaver` 与 `thread_id` 绝对隔离不同租户的上下文，
   并在相同 `thread_id` 多轮交互时自动加载前文历史。

2. 类与组件结构 (Component Hierarchy):
   - `EnterpriseAuditState`: 生产级强类型 AgentState，封装 messages 对话历史、tenant_id 与 audit_session_id。
   - `security_scan_node`: 模拟执行代码安全分析并返回阶段性审计消息。
   - `build_persistent_audit_graph`: 构建 StateGraph，绑定 `MemorySaver` 持久化检查点器并编译。
   - `execute_tenant_session`: 租户会话执行包装函数，负责构建带有 `thread_id` 的 config 字典并调用。

3. 关键数据流 (Key Data Flow):
   [Tenant A Request (thread_id="tenant-alpha")] ──> [execute_tenant_session]
                                                             │
                                          (传入 config={"configurable": {"thread_id": "tenant-alpha"}})
                                                             │
                                                  [MemorySaver 检查点管理器]
                                                             │
                                                (反序列化并自动加载历史快照)
                                                             │
                                                  [security_scan_node]
===================================================================================
"""

from typing import TypedDict, Annotated
from langgraph.graph import StateGraph, END, add_messages
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage

# ===================================================================================
# 1. 生产级强类型状态契约 (Enterprise State Contract)
# ===================================================================================

class EnterpriseAuditState(TypedDict):
    """企业级安全审计 AgentState 契约
    
    Attributes:
        messages: 带有 add_messages 归约器的对话消息历史列表
        tenant_id: 租户唯一标识符 (如 'tenant-alpha')
        audit_session_id: 审计会话编号
    """
    messages: Annotated[list[BaseMessage], add_messages]
    tenant_id: str
    audit_session_id: str


# ===================================================================================
# 2. 真实业务节点实现 (Business Domain Nodes)
# ===================================================================================

def security_scan_node(state: EnterpriseAuditState) -> dict:
    """安全扫描节点：执行静态代码审查并生成阶段性响应"""
    messages = state.get("messages", [])
    last_text = str(messages[-1].content) if messages else "空请求"
    tenant = state.get("tenant_id", "UNKNOWN_TENANT")
    session_id = state.get("audit_session_id", "UNKNOWN_SESSION")
    
    return {
        "messages": [
            AIMessage(content=f"[安全扫描节点 | 租户: {tenant} | 会话: {session_id}]: 已完成针对 '{last_text}' 的合规扫描。")
        ]
    }


# ===================================================================================
# 3. 练习核心：绑定 MemorySaver 编译拓扑图 (TODO)
# ===================================================================================

def build_persistent_audit_graph():
    """构建带 MemorySaver 检查点持久化器的 StateGraph 并编译
    
    Returns:
        编译后支持 MemorySaver 的 CompiledGraph 实体
        
    Raises:
        NotImplementedError: 学员需手动补全 MemorySaver 实例化与 compile(checkpointer=...) 绑定
    """
    workflow = StateGraph(EnterpriseAuditState)
    
    workflow.add_node("scan", security_scan_node)
    workflow.set_entry_point("scan")
    workflow.add_edge("scan", END)
    
    # TODO: 步骤 1 - 实例化 MemorySaver() 检查点保存器对象
    # memory = MemorySaver()
    
    # TODO: 步骤 2 - 在 workflow.compile(...) 中传入 checkpointer=memory
    # return workflow.compile(checkpointer=memory)
    
    raise NotImplementedError("TODO: 请在 build_persistent_audit_graph 中实例化 MemorySaver 并绑定 checkpointer 编译！")


# ===================================================================================
# 4. 练习核心：透传 thread_id 配置执行包装器 (TODO)
# ===================================================================================

def execute_tenant_session(app, user_input: str, tenant_id: str, thread_id: str) -> dict:
    """带 thread_id 会话隔离的图执行包装函数
    
    Args:
        app: 编译后的支持 Checkpointer 的 Runnable 图实例
        user_input: 用户输入的用户指令文本
        tenant_id: 租户 ID
        thread_id: 会话隔离唯一的 Thread ID 标识符
        
    Returns:
        包含持久化反序列化后完整消息历史的 State 字典
        
    Raises:
        NotImplementedError: 学员需手动补全带 thread_id 的 config 构建与 invoke 调用
    """
    # TODO: 步骤 1 - 构造 config 字典，包含 configurable:
    #       config = {"configurable": {"thread_id": thread_id}}
    # TODO: 步骤 2 - 构造输入 state 字典：
    #       input_state = {
    #           "messages": [HumanMessage(content=user_input)],
    #           "tenant_id": tenant_id,
    #           "audit_session_id": thread_id
    #       }
    # TODO: 步骤 3 - 调用 app.invoke(input_state, config=config) 并返回结果
    
    raise NotImplementedError("TODO: 请在 execute_tenant_session 中构造 configurable.thread_id 并调用 app.invoke！")


# ===================================================================================
# 5. 调试运行入口 (Student Interactive Console Verification)
# ===================================================================================

if __name__ == "__main__":
    print("=" * 75)
    print("🚀 Day 69 练习：内存校验器 (MemorySaver) 与持久化状态机 - 本地调试")
    print("=" * 75)
    
    try:
        app = build_persistent_audit_graph()
        
        # 1. 租户 Alpha 发起第一次请求 (thread_id: "thread-alpha-101")
        print("\n--- 1. 租户 Alpha (thread-alpha-101) 第一次扫描请求 ---")
        res_a1 = execute_tenant_session(app, "扫描支付 API 越权漏洞", "tenant-alpha", "thread-alpha-101")
        print(f"  当前消息总数: {len(res_a1['messages'])}")
        
        # 2. 租户 Beta 发起第一次请求 (thread_id: "thread-beta-202") —— 验证绝对隔离
        print("\n--- 2. 租户 Beta (thread-beta-202) 独立扫描请求 ---")
        res_b1 = execute_tenant_session(app, "扫描用户库 SQL 注入", "tenant-beta", "thread-beta-202")
        print(f"  当前消息总数: {len(res_b1['messages'])}")
        
        # 3. 租户 Alpha 继续第二次请求 (thread_id: "thread-alpha-101") —— 验证历史加载
        print("\n--- 3. 租户 Alpha (thread-alpha-101) 多轮追问请求 ---")
        res_a2 = execute_tenant_session(app, "追问支付 API 修复建议", "tenant-alpha", "thread-alpha-101")
        print(f"  当前消息总数 (应自动继承前文累加至 4): {len(res_a2['messages'])}")
        
        print("\n✅ 练习验证成功！线程级上下文隔离与 MemorySaver 历史恢复验证通过。")

    except NotImplementedError as e:
        print("\n" + "!" * 75)
        print("⚠️ 捕获到未实现占位符 (NotImplementedError)：")
        print(f"👉 提示信息: {e}")
        print("💡 请打开练习文件 weekly/w10_langgraph_core/day69/practice.py 补全 TODO 代码。")
        print("!" * 75)
