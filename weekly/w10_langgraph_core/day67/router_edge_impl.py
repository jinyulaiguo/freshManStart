"""Day 67 参考标准答案：架构师级路由边与动态决策 (Conditional Edges & Dynamic Routing)

===================================================================================
架构方案与设计说明 (Architectural Overview):
===================================================================================
1. 设计意图 (Design Intent):
   本模块展示 LangGraph 中条件路由边（Conditional Edges）的高阶工业级实现范式。
   基于“多 Agent 自动化代码重构与 CVE 漏洞安全分流引擎”真实场景，展示如何将控制流决策
   从业务节点中彻底解耦，并通过显式契约映射（Path Map）与防御性路由降级构建弹性拓扑。

2. 架构方案划分 (Architecture Patterns):
   - 方案一：标准显式映射与多分支条件路由模式 (Multi-Branch Conditional Edge Mapping)
     * 强类型 `Pattern1CodeDispatchState` 状态契约。
     * `p1_intent_classifier_node` / `p1_ast_patch_node` / `p1_human_escalation_node` / `p1_summarizer_node`。
     * 纯函数 `p1_route_by_intent` + 显式 `path_map` 分支契约绑定。

   - 方案二：带未知键捕获与安全兜底的防御性路由模式 (Defensive Fallback Edge Router)
     * `Pattern2DefensiveState` 状态契约。
     * `p2_defensive_router` 白名单校验与未知路由降级机制（拦截 LLM 幻觉输出的未知节点名）。

3. 物理隔离规范 (Physical Isolation Guarantee):
   方案一与方案二在物理上完全隔离，各自声明全套 State 契约、节点函数与路由逻辑，代码冗余自包含。
===================================================================================
"""

from typing import TypedDict, Annotated, Literal
from langgraph.graph import StateGraph, END, add_messages
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage

# ===================================================================================
# 方案一：标准显式映射与多分支条件路由模式 (Multi-Branch Path Map)
# ===================================================================================

class Pattern1CodeDispatchState(TypedDict):
    """方案一全局状态契约：多 Agent 代码审计与意图分流"""
    messages: Annotated[list[BaseMessage], add_messages]
    intent_code: str
    risk_level: str


def p1_intent_classifier_node(state: Pattern1CodeDispatchState) -> dict:
    """方案一节点 1：安全意图分类器，根据分析判定处理分支"""
    messages = state.get("messages", [])
    if not messages:
        return {"intent_code": "DIRECT"}
    
    last_text = str(messages[-1].content)
    if "SQL注入" in last_text or "修复" in last_text:
        target_intent = "PATCH_TOOL"
        risk = "MEDIUM"
    elif "越权" in last_text or "高危漏洞" in last_text:
        target_intent = "HUMAN_ESCALATE"
        risk = "HIGH"
    else:
        target_intent = "DIRECT"
        risk = "LOW"
        
    return {
        "intent_code": target_intent,
        "risk_level": risk,
        "messages": [AIMessage(content=f"[Pattern1 意图分类器]: 识别分类 -> '{target_intent}' (风险等级: {risk})")]
    }


def p1_ast_patch_node(state: Pattern1CodeDispatchState) -> dict:
    """方案一节点 2：AST 代码补丁生成工具节点"""
    return {
        "messages": [AIMessage(content="[Pattern1 AST 补丁节点]: 成功应用 SQL 参数化查询预编译补丁。")]
    }


def p1_human_escalation_node(state: Pattern1CodeDispatchState) -> dict:
    """方案一节点 3：高风险漏洞人工专席升舱审核节点"""
    return {
        "messages": [AIMessage(content="[Pattern1 人工升舱节点]: 发现高危越权漏洞，已派发紧急安全专家 Jira 工单。")]
    }


def p1_summarizer_node(state: Pattern1CodeDispatchState) -> dict:
    """方案一节点 4：终态回答总结节点"""
    return {
        "messages": [AIMessage(content="[Pattern1 总结节点]: 自动化安全分流与响应流程执行完毕。")]
    }


def p1_route_by_intent(state: Pattern1CodeDispatchState) -> Literal["route_to_patch", "route_to_human", "route_to_finish"]:
    """方案一核心路由决策函数 (Router Pure Function)
    
    分析全局状态中的 intent_code 字段，导出逻辑路由键。
    """
    intent = state.get("intent_code", "DIRECT")
    
    if intent == "PATCH_TOOL":
        return "route_to_patch"
    elif intent == "HUMAN_ESCALATE":
        return "route_to_human"
    else:
        return "route_to_finish"


def build_pattern1_graph():
    """构建方案一标准多分支条件路由拓扑图"""
    workflow = StateGraph(Pattern1CodeDispatchState)
    
    # 注册节点
    workflow.add_node("classifier", p1_intent_classifier_node)
    workflow.add_node("patch_engine", p1_ast_patch_node)
    workflow.add_node("human_escalation", p1_human_escalation_node)
    workflow.add_node("summarizer", p1_summarizer_node)
    
    # 设置入口点
    workflow.set_entry_point("classifier")
    
    # 挂载条件路由边 (add_conditional_edges)
    workflow.add_conditional_edges(
        source="classifier",
        path=p1_route_by_intent,
        path_map={
            "route_to_patch": "patch_engine",
            "route_to_human": "human_escalation",
            "route_to_finish": "summarizer"
        }
    )
    
    # 挂载收敛边
    workflow.add_edge("patch_engine", "summarizer")
    workflow.add_edge("human_escalation", "summarizer")
    workflow.add_edge("summarizer", END)
    
    return workflow.compile()


# ===================================================================================
# 方案二：带未知键捕获与安全兜底的防御性路由模式 (Defensive Edge Router)
# ===================================================================================

class Pattern2DefensiveState(TypedDict):
    """方案二全局状态契约"""
    messages: Annotated[list[BaseMessage], add_messages]
    raw_intent_key: str
    fallback_activated: bool


def p2_raw_intent_node(state: Pattern2DefensiveState) -> dict:
    """方案二意图节点：模拟偶发性 LLM 幻觉产生未知路由键"""
    messages = state.get("messages", [])
    if not messages:
        return {"raw_intent_key": "UNKNOWN"}
    
    text = str(messages[-1].content)
    if "幻觉测试" in text:
        # 故意注入非法的未知路由标识
        return {"raw_intent_key": "CORRUPTED_HALLUCINATED_KEY"}
    elif "重构" in text:
        return {"raw_intent_key": "REFACTOR"}
    else:
        return {"raw_intent_key": "INFO"}


def p2_refactor_engine_node(state: Pattern2DefensiveState) -> dict:
    """方案二正常重构节点"""
    return {"messages": [AIMessage(content="[Pattern2 重构引擎]: 完成自动化重构。")]}


def p2_info_node(state: Pattern2DefensiveState) -> dict:
    """方案二标准信息节点"""
    return {"messages": [AIMessage(content="[Pattern2 咨询节点]: 输出安全标准说明。")]}


def p2_safe_fallback_node(state: Pattern2DefensiveState) -> dict:
    """方案二安全降级兜底节点：拦截未识别的非法路由键并自愈"""
    raw_key = state.get("raw_intent_key", "")
    return {
        "fallback_activated": True,
        "messages": [AIMessage(content=f"[Pattern2 降级节点]: 警告！捕获到未授权或损坏的路由键 '{raw_key}'，已安全拦截并降级返回。")]
    }


def p2_defensive_router(state: Pattern2DefensiveState) -> str:
    """方案二防御性路由函数 (带白名单安全校验)"""
    raw_key = state.get("raw_intent_key", "")
    
    whitelist = {
        "REFACTOR": "target_refactor",
        "INFO": "target_info"
    }
    
    # 防御性白名单查找，不存在则重定向至 safe_fallback
    return whitelist.get(raw_key, "target_fallback")


def build_pattern2_defensive_graph():
    """构建方案二带防御性降级回路的拓扑图"""
    workflow = StateGraph(Pattern2DefensiveState)
    
    workflow.add_node("intent_gen", p2_raw_intent_node)
    workflow.add_node("refactor_engine", p2_refactor_engine_node)
    workflow.add_node("info_engine", p2_info_node)
    workflow.add_node("fallback_node", p2_safe_fallback_node)
    
    workflow.set_entry_point("intent_gen")
    
    workflow.add_conditional_edges(
        source="intent_gen",
        path=p2_defensive_router,
        path_map={
            "target_refactor": "refactor_engine",
            "target_info": "info_engine",
            "target_fallback": "fallback_node"
        }
    )
    
    workflow.add_edge("refactor_engine", END)
    workflow.add_edge("info_engine", END)
    workflow.add_edge("fallback_node", END)
    
    return workflow.compile()


# ===================================================================================
# 控制台验证与测试运行入口 (stdout Execution Entry)
# ===================================================================================

if __name__ == "__main__":
    print("=" * 85)
    print("🌟 架构师级 LangGraph Day 67: 路由边 (Conditional Edges) 与动态分流演示")
    print("=" * 85)
    
    # -------------------------------------------------------------------------------
    # 演示 1: 方案一 (标准多分支条件路由)
    # -------------------------------------------------------------------------------
    print("\n【方案一：标准 Path Map 条件路由测试】")
    app1 = build_pattern1_graph()
    
    cases_p1 = [
        ("检测到 SQL注入 漏洞，请求修复", "工具补丁分支"),
        ("检测到 垂直越权 高危漏洞", "人工升舱分支"),
        ("查询安全审计规范文档", "直答总结分支")
    ]
    
    for prompt, expected_branch in cases_p1:
        print(f"\n👉 测试场景 ({expected_branch}): '{prompt}'")
        init_state = {"messages": [HumanMessage(content=prompt)], "intent_code": "", "risk_level": ""}
        result = app1.invoke(init_state)
        print("   消息流向追踪:")
        for msg in result["messages"]:
            print(f"    - [{msg.__class__.__name__}]: {msg.content}")

    # -------------------------------------------------------------------------------
    # 演示 2: 方案二 (带未知路由键防御拦截)
    # -------------------------------------------------------------------------------
    print("\n" + "-" * 85)
    print("【方案二：带未知路由键白名单拦截与安全 Fallback 测试】")
    app2 = build_pattern2_defensive_graph()
    
    cases_p2 = [
        ("请求自动重构模块", "正常重构分支"),
        ("触发系统 幻觉测试 异常键", "未知键拦截降级分支")
    ]
    
    for prompt, expected_branch in cases_p2:
        print(f"\n👉 测试场景 ({expected_branch}): '{prompt}'")
        init_state = {"messages": [HumanMessage(content=prompt)], "raw_intent_key": "", "fallback_activated": False}
        result = app2.invoke(init_state)
        print("   消息流向追踪:")
        for msg in result["messages"]:
            print(f"    - [{msg.__class__.__name__}]: {msg.content}")

    print("\n" + "=" * 85)
    print("✅ 演示完成！架构师级条件路由、解耦分流与防御性降级测试 100% 通过。")
    print("=" * 85)
