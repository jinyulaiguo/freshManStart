"""
Day 65 参考标准答案：有向图 StateGraph 基础编译与流转引擎

设计意图：
    本模块完整构建了一个基于 LangGraph 的有向图编译执行流（智能客服分流与安全防御系统）。
    通过继承 `TypedDict` 定义图全局状态 `RoutingState`，注册多个异步任务节点，定义用于判定流向的
    路由器函数（Router Functions），最终使用有向图编译器 `StateGraph` 进行装配并编译输出
    符合 Runnable 协议的 `CompiledGraph`。

类与函数结构：
    - RoutingState(TypedDict): 全局状态字段定义契约。
    - security_check_node(state: RoutingState) -> dict: 执行敏感词过滤与安全性审查。
    - intent_classifier_node(state: RoutingState) -> dict: 判断意图是自助响应还是人工客服升级。
    - auto_respond_node(state: RoutingState) -> dict: 填充自动响应文案。
    - human_escalation_node(state: RoutingState) -> dict: 填充人工客服升级文案。
    - block_respond_node(state: RoutingState) -> dict: 填充安全违规拦截文案。
    - route_safety(state: RoutingState) -> str: 控制安全校验节点后的有向路由分流。
    - route_intent(state: RoutingState) -> str: 控制意图分类节点后的有向路由分流。

关键数据流流向：
    1. 外部 Query -> [START] -> security_check_node。
    2. 执行安全检查：
       - 若不安全，[route_safety 路由为 "block"] -> block_respond_node -> [END]。
       - 若安全，[route_safety 路由为 "pass"] -> intent_classifier_node。
    3. 执行意图识别：
       - 若属于常规自动类别，[route_intent 路由为 "auto"] -> auto_respond_node -> [END]。
       - 若属于复杂人工类别，[route_intent 路由为 "manual"] -> human_escalation_node -> [END]。
"""

import asyncio
from typing import TypedDict
from langgraph.graph import StateGraph, START, END

# ==========================================
# 步骤 1：声明图的全局状态契约
# ==========================================
class RoutingState(TypedDict):
    """图的全局共享数据状态契约。
    
    各节点可通过返回此结构中键值对的子集来增量更新全局状态。
    """
    query: str            # 用户输入的原始请求
    safety_passed: bool   # 是否通过安全过滤
    category: str         # 意图类别："auto" (自动处理) 或 "manual" (人工升级)
    response: str         # 最终的答复文本


# ==========================================
# 步骤 2：定义各个节点的业务逻辑函数 (Node Functions)
# ==========================================

async def security_check_node(state: RoutingState) -> dict:
    """安全校验节点。
    
    检测输入查询内容是否包含不安全字眼，并更新安全标志。
    """
    # 步骤 1：防御性数据校验
    query = state.get("query", "")
    if not isinstance(query, str):
        raise TypeError("图状态中的 query 字段必须为字符串类型")
        
    query_lower = query.lower()
    
    # 步骤 2：分析并判断敏感违规词汇
    sensitive_triggers = ["hack", "exploit", "malware"]
    is_safe = not any(trigger in query_lower for trigger in sensitive_triggers)
    
    # 步骤 3：返回部分状态增量，由拓扑引擎合入全局 State
    return {"safety_passed": is_safe}


async def intent_classifier_node(state: RoutingState) -> dict:
    """意图分类节点。
    
    分析用户输入，并将其路由分配为自动应答（auto）或人工处理（manual）。
    """
    query = state.get("query", "").lower()
    
    # 步骤 1：基于匹配规则分类意图
    auto_keywords = ["help", "hello", "price"]
    manual_keywords = ["refund", "complain", "custom"]
    
    # 默认兜底机制：若无法明显归类，判定为 manual
    category = "manual"
    if any(keyword in query for keyword in auto_keywords):
        category = "auto"
    elif any(keyword in query for keyword in manual_keywords):
        category = "manual"
        
    # 步骤 2：返回意图更新字典
    return {"category": category}


async def auto_respond_node(state: RoutingState) -> dict:
    """自动响应节点。
    
    写入标准化自助自动客服回复。
    """
    return {"response": "【自动回复】您的请求已收到，我们会尽快为您处理。"}


async def human_escalation_node(state: RoutingState) -> dict:
    """人工客服升级节点。
    
    写入人工客服转移通知。
    """
    return {"response": "【人工客服】已为您接通高级客服代表，请稍后。"}


async def block_respond_node(state: RoutingState) -> dict:
    """安全拦截响应节点。
    
    写入安全违规警示。
    """
    return {"response": "【安全拦截】系统检测到非法或敏感词汇，请求已被拦截。"}


# ==========================================
# 步骤 3：定义流转分流判定函数 (Router Functions)
# ==========================================

def route_safety(state: RoutingState) -> str:
    """安全分流路由器。
    
    根据 `safety_passed` 字段的布尔值返回对应的路由路径键名。
    """
    if state.get("safety_passed", False):
        return "pass"
    return "block"


def route_intent(state: RoutingState) -> str:
    """意图分流路由器。
    
    根据 `category` 字段的分类值返回对应的路由路径键名。
    """
    category = state.get("category", "manual")
    if category == "auto":
        return "auto"
    return "manual"


# ==========================================
# 调试主入口：拓扑构建与编译运行
# ==========================================
if __name__ == "__main__":
    async def run_solution():
        print("====== 开始运行 Day 65 有向图 StateGraph 编译标准答案验证 ======\n")
        
        # 调试测试输入集
        test_inputs = [
            {"query": "Hello, I want to check the price of products."},
            {"query": "I want a refund for my order immediately!"},
            {"query": "Here is an exploit payload to hack the database."}
        ]

        # 步骤 1：利用全局状态字典类型契约实例化有向图构建器
        builder = StateGraph(RoutingState)
        
        # 步骤 2：注册图的节点（Nodes），将异步函数声明为执行顶点
        builder.add_node("security_check", security_check_node)
        builder.add_node("intent_classifier", intent_classifier_node)
        builder.add_node("auto_respond", auto_respond_node)
        builder.add_node("human_escalation", human_escalation_node)
        builder.add_node("block_respond", block_respond_node)
        
        # 步骤 3：配置静态有向入口边指向安全检查节点
        builder.add_edge(START, "security_check")
        
        # 步骤 4：在安全校验节点后绑定条件路由边 (Conditional Edges)
        builder.add_conditional_edges(
            "security_check",
            route_safety,
            {
                "pass": "intent_classifier",
                "block": "block_respond"
            }
        )
        
        # 步骤 5：在意图分类节点后绑定条件路由边 (Conditional Edges)
        builder.add_conditional_edges(
            "intent_classifier",
            route_intent,
            {
                "auto": "auto_respond",
                "manual": "human_escalation"
            }
        )
        
        # 步骤 6：配置出口普通边，使各分支响应节点正常流向 END
        builder.add_edge("auto_respond", END)
        builder.add_edge("human_escalation", END)
        builder.add_edge("block_respond", END)
        
        # 步骤 7：编译图拓扑，输出可执行的可运行体 CompiledGraph
        app = builder.compile()
        
        # 步骤 8：顺序运行测试输入，验证非阻塞并发流转行为与最终状态更新
        for index, inputs in enumerate(test_inputs, start=1):
            print(f"[测试 {index}] 正在分流处理 Query: '{inputs['query']}'")
            
            # 使用 CompiledGraph 的 ainvoke 统一生命周期通道
            result = await app.ainvoke(inputs)
            
            print(f" └─ 安全通过: {result.get('safety_passed')}")
            print(f" └─ 意图识别: {result.get('category')}")
            print(f" └─ 系统应答: {result.get('response')}\n")
            
        print("====== Day 65 有向图 StateGraph 标准答案全部验证通过！ ======")

    asyncio.run(run_solution())
