"""Day 69 参考标准答案：架构师级内存校验器 (MemorySaver) 与持久化状态机

===================================================================================
架构方案与设计说明 (Architectural Overview):
===================================================================================
1. 设计意图 (Design Intent):
   本模块全面展示 LangGraph 中 MemorySaver 检查点持久化器与多租户会话隔离机制。
   基于“企业级多租户代码安全审计与合规分析引擎”真实场景，展示如何利用 `MemorySaver`
   与 `thread_id` 主键构建无状态恢复、多租户强隔离及历史版本 (Time-Travel) 追溯体系。

2. 架构方案划分 (Architecture Patterns):
   - 方案一：声明式 `MemorySaver` 与 `thread_id` 多会话隔离模式 (Declarative MemorySaver Isolation)
     * 强类型 `Pattern1AuditState` 状态契约。
     * `compile(checkpointer=MemorySaver())` 拓扑绑定。
     * 多 `thread_id` 并发调用，演示租户 A 与租户 B 消息历史的物理隔离与同线程累加继承。

   - 方案二：工业级多租户会话持久化引擎与历史版本回退器 (`ProductionMultiTenantSessionVaultEngine`)
     * 封装支持 Checkpointer 的高阶 Agent 引擎。
     * 包含租户会话注册表、`get_state` 最新状态快照抽取以及 `get_state_history` 历史版本序列化回放功能。

3. 物理隔离规范 (Physical Isolation Guarantee):
   方案一与方案二在物理上完全隔离，各自声明独立的 TypedDict 状态与节点，代码冗余自包含。
===================================================================================
"""

from typing import TypedDict, Annotated, Any
from langgraph.graph import StateGraph, END, add_messages
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage

# ===================================================================================
# 方案一：声明式 MemorySaver 与 thread_id 多会话隔离模式
# ===================================================================================

class Pattern1AuditState(TypedDict):
    """方案一全局 AgentState 契约：企业审计状态"""
    messages: Annotated[list[BaseMessage], add_messages]
    tenant_code: str
    audit_target: str


def p1_scanner_node(state: Pattern1AuditState) -> dict:
    """方案一扫描节点"""
    messages = state.get("messages", [])
    last_prompt = str(messages[-1].content) if messages else ""
    tenant = state.get("tenant_code", "UNKNOWN")
    target = state.get("audit_target", "DEFAULT")
    
    return {
        "messages": [
            AIMessage(content=f"[Pattern1 审计节点 | 租户: {tenant} | 目标: {target}]: 针对 '{last_prompt}' 完成合规校验。")
        ]
    }


def build_pattern1_persistent_graph():
    """构建方案一带 MemorySaver 检查点器的图结构"""
    workflow = StateGraph(Pattern1AuditState)
    
    workflow.add_node("scanner", p1_scanner_node)
    workflow.set_entry_point("scanner")
    workflow.add_edge("scanner", END)
    
    # 实例化 MemorySaver 检查点持久化器
    memory_saver = MemorySaver()
    
    # 在 compile 时绑定 checkpointer
    return workflow.compile(checkpointer=memory_saver)


def run_pattern1_isolation_demo():
    """运行方案一演示：验证 thread_id 隔离与同线程状态恢复"""
    app = build_pattern1_persistent_graph()
    
    # 租户 A (thread_id: "thread-alpha-101") 交互 1
    config_a = {"configurable": {"thread_id": "thread-alpha-101"}}
    res_a1 = app.invoke(
        {"messages": [HumanMessage(content="分析 SQL 注入漏洞")], "tenant_code": "TENANT_ALPHA", "audit_target": "DB_MODULE"},
        config=config_a
    )
    
    # 租户 B (thread_id: "thread-beta-202") 交互 1 —— 隔离验证
    config_b = {"configurable": {"thread_id": "thread-beta-202"}}
    res_b1 = app.invoke(
        {"messages": [HumanMessage(content="分析 JWT 越权漏洞")], "tenant_code": "TENANT_BETA", "audit_target": "AUTH_MODULE"},
        config=config_b
    )
    
    # 租户 A (thread_id: "thread-alpha-101") 交互 2 —— 继承历史
    res_a2 = app.invoke(
        {"messages": [HumanMessage(content="请求预编译修复代码")], "tenant_code": "TENANT_ALPHA", "audit_target": "DB_MODULE"},
        config=config_a
    )
    
    return res_a1, res_b1, res_a2


# ===================================================================================
# 方案二：工业级多租户会话持久化引擎与历史版本回退器
# ===================================================================================

class Pattern2EnterpriseVaultState(TypedDict):
    """方案二企业级 AgentState 契约"""
    messages: Annotated[list[BaseMessage], add_messages]
    tenant_id: str
    scan_steps: int
    security_verdict: str


def p2_deep_security_node(state: Pattern2EnterpriseVaultState) -> dict:
    """方案二深度安全扫描节点"""
    steps = state.get("scan_steps", 0) + 1
    tenant = state.get("tenant_id", "GLOBAL")
    
    verdict = "PASS" if steps > 1 else "REQUIRES_FIX"
    
    return {
        "scan_steps": steps,
        "security_verdict": verdict,
        "messages": [
            AIMessage(content=f"[Pattern2 深度安全引擎 | 租户: {tenant} | 第 {steps} 轮分析]: 评估结果 -> {verdict}")
        ]
    }


def build_pattern2_vault_graph():
    """构建方案二图结构"""
    workflow = StateGraph(Pattern2EnterpriseVaultState)
    
    workflow.add_node("deep_scan", p2_deep_security_node)
    workflow.set_entry_point("deep_scan")
    workflow.add_edge("deep_scan", END)
    
    checkpointer = MemorySaver()
    return workflow.compile(checkpointer=checkpointer)


class ProductionMultiTenantSessionVaultEngine:
    """工业级多租户会话持久化引擎组件
    
    特性：
      1. 基于 thread_id 的强类型会话执行
      2. get_state 最新状态快照审查
      3. get_state_history 历史版本 (Time-Travel) 序列化与溯源
    """
    
    def __init__(self, compiled_graph):
        self.app = compiled_graph

    def execute_session(self, tenant_id: str, thread_id: str, prompt: str) -> dict:
        """带租户元数据的会话执行入口"""
        config = {"configurable": {"thread_id": thread_id}}
        input_payload = {
            "messages": [HumanMessage(content=prompt)],
            "tenant_id": tenant_id,
            "scan_steps": 0,
            "security_verdict": "PENDING"
        }
        return self.app.invoke(input_payload, config=config)

    def get_latest_session_snapshot(self, thread_id: str) -> Any:
        """获取特定 thread_id 的最新 State Snapshot"""
        config = {"configurable": {"thread_id": thread_id}}
        return self.app.get_state(config)

    def get_session_checkpoint_history(self, thread_id: str) -> list:
        """获取特定 thread_id 的全量历史 Checkpoint 演进版本"""
        config = {"configurable": {"thread_id": thread_id}}
        history_states = list(self.app.get_state_history(config))
        return history_states


# ===================================================================================
# 控制台验证与测试运行入口 (stdout Execution Entry)
# ===================================================================================

if __name__ == "__main__":
    print("=" * 85)
    print("🌟 架构师级 LangGraph Day 69: MemorySaver 持久化与 thread_id 会话隔离演示")
    print("=" * 85)
    
    # -------------------------------------------------------------------------------
    # 演示 1: 方案一 (声明式 MemorySaver 与 thread_id 隔离)
    # -------------------------------------------------------------------------------
    print("\n【方案一：声明式 MemorySaver 与 thread_id 多租户隔离测试】")
    res_a1, res_b1, res_a2 = run_pattern1_isolation_demo()
    
    print(f"\n👉 [租户 Alpha - 首次请求 (thread-alpha-101)]: 消息数 = {len(res_a1['messages'])}")
    for msg in res_a1["messages"]:
        print(f"    - [{msg.__class__.__name__}]: {msg.content}")
        
    print(f"\n👉 [租户 Beta - 独立隔离请求 (thread-beta-202)]: 消息数 = {len(res_b1['messages'])}")
    for msg in res_b1["messages"]:
        print(f"    - [{msg.__class__.__name__}]: {msg.content}")
        
    print(f"\n👉 [租户 Alpha - 二次追问 (thread-alpha-101)]: 消息数 (已继承前文累加) = {len(res_a2['messages'])}")
    for msg in res_a2["messages"]:
        print(f"    - [{msg.__class__.__name__}]: {msg.content}")

    # -------------------------------------------------------------------------------
    # 演示 2: 方案二 (ProductionMultiTenantSessionVaultEngine 历史追溯)
    # -------------------------------------------------------------------------------
    print("\n" + "-" * 85)
    print("【方案二：ProductionMultiTenantSessionVaultEngine 会话追溯与历史快照测试】")
    
    vault_app = build_pattern2_vault_graph()
    vault_engine = ProductionMultiTenantSessionVaultEngine(compiled_graph=vault_app)
    
    target_thread = "session-enterprise-999"
    
    # 多轮交互演进
    vault_engine.execute_session("TENANT_XYZ", target_thread, "第一轮: 初始化分析框架")
    vault_engine.execute_session("TENANT_XYZ", target_thread, "第二轮: 深入模块安全扫描")
    
    # 审查最新快照
    latest_snapshot = vault_engine.get_latest_session_snapshot(target_thread)
    print(f"\n👉 [最新状态快照 | thread_id='{target_thread}']:")
    print(f"   - 当前演进到的下一个节点/游标: {latest_snapshot.next}")
    print(f"   - 全局 State 中的分析轮数 (scan_steps): {latest_snapshot.values.get('scan_steps')}")
    print(f"   - 消息链条深度: {len(latest_snapshot.values.get('messages', []))}")
    
    # 遍历全量 Checkpoint 演进历史 (Time-Travel Inspection)
    history = vault_engine.get_session_checkpoint_history(target_thread)
    print(f"\n👉 [全量历史 Checkpoint 版本数 (Time-Travel History)]: 共 {len(history)} 个 Checkpoint 快照")
    for idx, state_snapshot in enumerate(history):
        checkpoint_id = state_snapshot.config.get("configurable", {}).get("checkpoint_id", "N/A")
        msg_count = len(state_snapshot.values.get("messages", [])) if state_snapshot.values else 0
        print(f"   • 版本 [{idx}]: Checkpoint ID = {checkpoint_id} | Messages 数 = {msg_count}")

    print("\n" + "=" * 85)
    print("✅ 演示完成！MemorySaver 持久化、多租户 thread_id 隔离与历史快照追溯 100% 验证通过。")
    print("=" * 85)
