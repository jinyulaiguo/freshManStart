"""Day 74 练习模版：子图（Subgraph）状态隔离与并发子流程设计

说明：
本文件为学员练习专用模版。请根据规范完成其中的 TODO 核心逻辑。
目标：定义 ChildState 与 ParentState，构建独立的子图 ChildGraph 并作为节点嵌入 ParentGraph，验证状态隔离。
"""

import sys
from typing import Dict, Any, List, TypedDict
from typing_extensions import Annotated
import operator

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver


# ============================================================================
# 1. 契约定义
# ============================================================================

class ParentState(TypedDict):
    """主图状态"""
    query: str
    result: str
    main_logs: Annotated[List[str], operator.add]


class ChildState(TypedDict):
    """子图内部隔离状态"""
    query: str
    result: str
    sub_internal_temp: str  # 子图私有字段，不应泄漏到主图


# ============================================================================
# 2. 节点逻辑与图编排 (TODO 练习)
# ============================================================================

def child_process_node(state: ChildState) -> Dict[str, Any]:
    """子图节点：处理内部推理"""
    print(f"[Practice Child Node] 处理子查询: {state['query']}")
    return {
        "result": f"Processed: {state['query']}",
        "sub_internal_temp": "PRIVATE_DEBUG_DATA"
    }


def build_child_practice_graph():
    """构建子图"""
    # TODO 1.1: 构建 StateGraph(ChildState)，注册 child_process_node 节点，连接 START 到 END，并 compile
    raise NotImplementedError("TODO: 请实现 build_child_practice_graph 逻辑")


def parent_start_node(state: ParentState) -> Dict[str, Any]:
    """主图节点 1"""
    print(f"[Practice Parent Node 1] 启动主工作流: {state['query']}")
    return {"main_logs": ["Parent workflow started"]}


def build_parent_practice_graph():
    """构建包含子图的主图"""
    # TODO 1.2: 实例化子图 child_app = build_child_practice_graph()
    # TODO 1.3: 构建 StateGraph(ParentState)
    # TODO 1.4: 注册节点 "start_node", "subgraph_node" (绑定 child_app)
    # TODO 1.5: 连线并绑定 MemorySaver compile 返回
    raise NotImplementedError("TODO: 请实现 build_parent_practice_graph 逻辑")


# ============================================================================
# 调试主入口 (带有友好的 TODO 拦截)
# ============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("🚀 Day 74 子图状态隔离练习入口")
    print("=" * 60)
    
    try:
        parent_app = build_parent_practice_graph()
        config = {"configurable": {"thread_id": "prac_sub_01"}}
        
        init_state = {
            "query": "Hello Subgraph",
            "result": "",
            "main_logs": []
        }
        output = parent_app.invoke(init_state, config)
        print(f"✅ 执行成功，主图最终 result: {output.get('result')}")
        print(f"子图私有字段是否隔离: {'sub_internal_temp' not in output}")
        
    except NotImplementedError as e:
        print(f"💡 [TODO 提示] 练习未完成: {e}")
    except Exception as e:
        print(f"❌ 运行报错: {e}")
