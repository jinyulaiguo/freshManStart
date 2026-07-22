"""Day 67 练习：架构师级路由边与动态决策 (Conditional Edges & Dynamic Routing)

===================================================================================
架构设计说明 (Architectural Overview):
===================================================================================
1. 业务场景 (Business Domain):
   本练习基于真实的“多 Agent 自动化代码重构与 CVE 漏洞安全分流引擎”业务场景。
   在安全审查流程中，系统依据分类意图动态路由：轻微语法报错分流至 `ast_patch_node` (工具修复)，
   高危越权漏洞分流至 `human_escalation_node` (人工专家专席升舱)，普通咨询分流至 `summarizer_node`。

2. 类与组件结构 (Hierarchy):
   - `CodeDispatchState`: 生产级强类型 AgentState，包含消息历史、意图代码及风险等级。
   - `intent_classifier_node`: 安全意图分析节点。
   - `ast_patch_node`: 补丁生成工具节点。
   - `human_escalation_node`: 高风险专席升舱节点。
   - `summarizer_node`: 终态答复总结节点。
   - `route_by_intent`: 核心路由决策纯函数，分析全局 State 并导出逻辑路由键。
   - `build_dynamic_dispatch_graph`: 拓扑构建与 `add_conditional_edges` 契约挂载。

3. 关键数据流 (Key Data Flow):
   [Security Issue Input] ──> [intent_classifier_node]
                                       │
                         (route_by_intent 纯函数决策)
                                       │
         ┌─────────────────────────────┼─────────────────────────────┐
         ▼ ("route_to_patch")          ▼ ("route_to_human")          ▼ ("route_to_finish")
  [ast_patch_node]             [human_escalation_node]         [summarizer_node]
         │                             │                             │
  (静态边 add_edge)             (静态边 add_edge)               [END 节点]
         │                             │
         └────────────────────────────> [summarizer_node]
===================================================================================
"""

from typing import TypedDict, Annotated, Literal
from langgraph.graph import StateGraph, END, add_messages
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage

# ===================================================================================
# 1. 状态契约定义 (State Contract)
# ===================================================================================

class CodeDispatchState(TypedDict):
    """全局 Agent 状态载体
    
    Attributes:
        messages: 带有 add_messages 归约器的对话消息历史列表
        intent_code: 意图标识 ('PATCH_TOOL', 'HUMAN_ESCALATE', 'DIRECT')
        risk_level: 风险等级 ('LOW', 'MEDIUM', 'HIGH')
    """
    messages: Annotated[list[BaseMessage], add_messages]
    intent_code: str
    risk_level: str


# ===================================================================================
# 2. 图节点实现 (Nodes Implementation)
# ===================================================================================

def intent_classifier_node(state: CodeDispatchState) -> dict:
    """意图分类节点：分析用户输入并识别安全处理意图"""
    messages = state.get("messages", [])
    if not messages:
        return {"intent_code": "DIRECT", "risk_level": "LOW"}
    
    text = str(messages[-1].content)
    if "SQL" in text or "修复" in text:
        intent = "PATCH_TOOL"
        risk = "MEDIUM"
    elif "越权" in text or "高危" in text:
        intent = "HUMAN_ESCALATE"
        risk = "HIGH"
    else:
        intent = "DIRECT"
        risk = "LOW"
        
    return {
        "intent_code": intent,
        "risk_level": risk,
        "messages": [AIMessage(content=f"[意图分类节点]: 识别分流意图为 -> {intent}")]
    }


def ast_patch_node(state: CodeDispatchState) -> dict:
    """补丁生成工具节点"""
    return {"messages": [AIMessage(content="[AST 补丁节点]: 成功应用 pre-compiled 预编译查询补丁。")]}


def human_escalation_node(state: CodeDispatchState) -> dict:
    """人工专席升舱节点"""
    return {"messages": [AIMessage(content="[人工升舱节点]: 发现高危越权漏洞，已派发安全专家工单。")]}


def summarizer_node(state: CodeDispatchState) -> dict:
    """总结答复节点"""
    return {"messages": [AIMessage(content="[总结回复节点]: 自动化安全审计分流处理完毕！")]}


# ===================================================================================
# 3. 练习核心：条件路由决策函数 (TODO)
# ===================================================================================

def route_by_intent(state: CodeDispatchState) -> Literal["route_to_patch", "route_to_human", "route_to_finish"]:
    """路由决策纯函数：根据全局状态中的 intent_code 导出逻辑路由键
    
    Args:
        state: 当前全局 CodeDispatchState 快照
        
    Returns:
        逻辑路由键，必须为 "route_to_patch", "route_to_human" 或 "route_to_finish" 之一
        
    Raises:
        NotImplementedError: 学员需手动补全分支路由决策逻辑
    """
    # TODO: 步骤 1 - 从 state 中提取 intent_code 属性 (默认 fallback 为 "DIRECT")
    # TODO: 步骤 2 - 根据 intent_code 进行分支判断：
    #       - 当 intent_code == "PATCH_TOOL" 时，返回 "route_to_patch"
    #       - 当 intent_code == "HUMAN_ESCALATE" 时，返回 "route_to_human"
    #       - 其他情况，返回 "route_to_finish"
    raise NotImplementedError("TODO: 请在 route_by_intent 中实现状态意图分析与逻辑路由键导出！")


# ===================================================================================
# 4. 拓扑图构建与条件边挂载 (TODO)
# ===================================================================================

def build_dynamic_dispatch_graph():
    """构建带条件路由边的 StateGraph 并编译
    
    Returns:
        编译后的 CompiledGraph 实例
        
    Raises:
        NotImplementedError: 学员需手动实现节点注册与 add_conditional_edges 挂载
    """
    workflow = StateGraph(CodeDispatchState)
    
    # 步骤 1: 注册 Node
    workflow.add_node("classifier", intent_classifier_node)
    workflow.add_node("ast_patcher", ast_patch_node)
    workflow.add_node("human_escalation", human_escalation_node)
    workflow.add_node("summarizer", summarizer_node)
    
    # 步骤 2: 设置入口点
    workflow.set_entry_point("classifier")
    
    # TODO: 步骤 3 - 挂载条件路由边 (add_conditional_edges)
    # 提示: 为 "classifier" 节点挂载条件边，传入决策函数 route_by_intent，
    # 显式定义 path_map 字典：
    # path_map = {
    #     "route_to_patch": "ast_patcher",
    #     "route_to_human": "human_escalation",
    #     "route_to_finish": "summarizer"
    # }
    
    # TODO: 步骤 4 - 添加收敛静态边 (add_edge)
    # 将 ast_patcher 与 human_escalation 连至 summarizer，并将 summarizer 连至 END 节点。
    
    raise NotImplementedError("TODO: 请在 build_dynamic_dispatch_graph 中使用 add_conditional_edges 挂载条件路由边！")


# ===================================================================================
# 5. 调试运行入口 (Student Interactive Console Verification)
# ===================================================================================

if __name__ == "__main__":
    print("=" * 75)
    print("🚀 Day 67 练习：架构师级路由边与动态分流 - 本地调试")
    print("=" * 75)
    
    try:
        app = build_dynamic_dispatch_graph()
        
        print("\n--- 调试用例 1: 输入 ['检测到 SQL 注入漏洞'] ---")
        test_state = {
            "messages": [HumanMessage(content="检测到 SQL 注入漏洞")],
            "intent_code": "",
            "risk_level": ""
        }
        res = app.invoke(test_state)
        for msg in res["messages"]:
            print(f"  [{msg.__class__.__name__}]: {msg.content}")
            
        print("\n✅ 练习验证成功！系统已成功按意图分流并正确执行拓扑流转。")

    except NotImplementedError as e:
        print("\n" + "!" * 75)
        print("⚠️ 捕获到未实现占位符 (NotImplementedError)：")
        print(f"👉 提示信息: {e}")
        print("💡 请打开练习文件 weekly/w10_langgraph_core/day67/practice.py 补全 TODO 代码。")
        print("!" * 75)
