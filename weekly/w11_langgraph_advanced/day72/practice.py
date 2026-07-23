"""Day 72 练习模版：工具调用人工审批与运行时拦截重写

说明：
本文件为学员练习专用模版。请根据规范完成其中的 TODO 核心逻辑。
目标：在工具执行前通过 interrupt_before 挂起，捕获错误参数并利用 update_state 进行原位覆写重写。
"""

import sys
from typing import Dict, Any, List, TypedDict
from typing_extensions import Annotated
import operator

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver


# ============================================================================
# 模拟数据库与状态契约
# ============================================================================

MOCK_USER_DB = {
    "USR_888": {"name": "张三", "role": "管理员", "status": "ACTIVE"},
    "USR_999": {"name": "李四", "role": "普通用户", "status": "ACTIVE"}
}


class ToolInterceptPracticeState(TypedDict):
    """客服与工具调用状态契约"""
    messages: Annotated[List[BaseMessage], operator.add]
    logs: Annotated[List[str], operator.add]


# ============================================================================
# 节点逻辑与图编排 (TODO 练习)
# ============================================================================

def practice_agent_node(state: ToolInterceptPracticeState) -> Dict[str, Any]:
    """节点 1：Agent 生成带错误参数的工具调用消息"""
    print("[Practice] Agent 生成工具调用...")
    # 模拟大模型生成了错误的 user_id: 'WRONG_ID'
    faulty_tool_call = {
        "name": "fetch_user_profile",
        "args": {"user_id": "WRONG_ID"},
        "id": "call_prac_1234"
    }
    ai_message = AIMessage(content="查询用户资料", tool_calls=[faulty_tool_call])
    return {
        "messages": [ai_message],
        "logs": [f"Agent generated tool_call for user_id='WRONG_ID'"]
    }


def practice_tool_node(state: ToolInterceptPracticeState) -> Dict[str, Any]:
    """节点 2：Tool 提取工具参数并查询数据库"""
    # TODO 1.1: 提取最新的 AIMessage 及 tool_calls[0] 中的 user_id 与 id
    # TODO 1.2: 根据 user_id 检索 MOCK_USER_DB，如果检索到返回成功 ToolMessage，否则返回失败 ToolMessage
    raise NotImplementedError("TODO: 请实现 practice_tool_node 逻辑")


def build_practice_graph():
    """构建带 tools 阻断的练习 StateGraph"""
    # TODO 1.3: 构建 StateGraph，注册 "agent" 与 "tools" 节点
    # TODO 1.4: 绑定 MemorySaver 并在 compile 时配置在 "tools" 节点前挂起阻断 (interrupt_before=["tools"])
    raise NotImplementedError("TODO: 请实现 build_practice_graph 逻辑")


# ============================================================================
# 调试主入口 (带有友好的 TODO 拦截)
# ============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("🚀 Day 72 工具拦截与原位重写练习入口")
    print("=" * 60)
    
    try:
        app = build_practice_graph()
        config = {"configurable": {"thread_id": "prac_thread_72"}}
        
        # 1. 启动运行
        init_state = {
            "messages": [HumanMessage(content="查一下 USR_888 资料")],
            "logs": ["Start session"]
        }
        app.invoke(init_state, config)
        
        # 2. 检查挂起
        snapshot = app.get_state(config)
        print(f"✅ 挂起成功，当前待执行节点: {snapshot.next}")
        
        # 3. 练习原位重写并解冻...
        last_ai_msg = snapshot.values["messages"][-1]
        print(f"当前生成的错误入参: {last_ai_msg.tool_calls[0]['args']}")
        
    except NotImplementedError as e:
        print(f"💡 [TODO 提示] 练习未完成: {e}")
    except Exception as e:
        print(f"❌ 运行报错: {e}")
