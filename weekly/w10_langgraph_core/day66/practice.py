"""
Day 66 默写与代码实践：TypedDict 状态契约与 Reducer 归约机制 (Practice Template)

===================================================================================
设计方案说明 (Architecture & Design Specification)
===================================================================================
1. 模块设计意图：
   本练习旨在帮助学员深入掌握 LangGraph 的状态归约（State Reducers）机制。
   学员将动手实现：
   - 方案一：重现无 Reducer 时的默认浅覆盖 BUG。
   - 方案二：配置内置 `add_messages` 归约器，完成消息追加、ID 覆盖与消息删除。
   - 方案三：手动实现自定义滑动窗口 `windowed_reducer` 与 Token 累加器。

2. 物理隔离规范：
   - 方案一：DefaultOverwriteState & default_overwrite_graph
   - 方案二：BuiltinReducerState & builtin_reducer_graph
   - 方案三：CustomReducerState & custom_reducer_graph

3. 数据流流向：
   State Snapshot -> Node Partial Update -> Reducer Merging -> Updated Snapshot
===================================================================================
"""

import asyncio
from typing import TypedDict, Annotated
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, RemoveMessage
from langgraph.graph import StateGraph, START, END, add_messages


# ===================================================================================
# 方案一：默认浅覆盖模式 (Default Overwrite) - 模拟覆盖 BUG
# ===================================================================================

class DefaultOverwriteState(TypedDict):
    """
    TODO: 声明不带 Annotated 归约器的默认浅覆盖状态
    包含字段：
      - messages: list[BaseMessage]
      - step_count: int
    """
    messages: list[BaseMessage]
    step_count: int


async def overwrite_node_a(state: DefaultOverwriteState) -> dict:
    """节点 A：产生初始对话"""
    # TODO: 返回包含第一条消息 (HumanMessage) 与 step_count=1 的字典
    raise NotImplementedError("TODO: 请实现 overwrite_node_a 节点返回")


async def overwrite_node_b(state: DefaultOverwriteState) -> dict:
    """节点 B：产生后续回复"""
    # TODO: 返回包含回复消息 (AIMessage) 与 step_count=2 的字典
    raise NotImplementedError("TODO: 请实现 overwrite_node_b 节点返回")


def build_default_overwrite_graph():
    """TODO: 组装 StateGraph 拓扑图并编译返回"""
    # TODO: 使用 StateGraph(DefaultOverwriteState) 添加 node_a, node_b 并完成连线
    raise NotImplementedError("TODO: 请实现 build_default_overwrite_graph")


# ===================================================================================
# 方案二：内置 `add_messages` 归约模式 (Built-in `add_messages` Reducer)
# ===================================================================================

class BuiltinReducerState(TypedDict):
    """
    TODO: 声明带有 `add_messages` 归约修饰的 TypedDict 状态
    包含字段：
      - messages: Annotated[list[BaseMessage], add_messages]
    """
    # TODO: 使用 typing.Annotated 绑定 add_messages
    messages: list[BaseMessage]  # 修改此处声明为 Annotated


async def builtin_node_initial(state: BuiltinReducerState) -> dict:
    """节点 1：产生第一条带 ID 的 HumanMessage 和临时 AIMessage"""
    # TODO: 返回包含两条带固定 id 的 Message 增量
    raise NotImplementedError("TODO: 请实现 builtin_node_initial")


async def builtin_node_update_id(state: BuiltinReducerState) -> dict:
    """节点 2：通过同名 ID 原位覆盖更新物理临时消息"""
    # TODO: 返回同名 ID 的更新版 AIMessage
    raise NotImplementedError("TODO: 请实现 builtin_node_update_id")


async def builtin_node_cleanup(state: BuiltinReducerState) -> dict:
    """节点 3：使用 RemoveMessage 擦除过期消息"""
    # TODO: 返回包含 RemoveMessage(id=...) 的字典
    raise NotImplementedError("TODO: 请实现 builtin_node_cleanup")


def build_builtin_reducer_graph():
    """TODO: 组装内置 Reducer 拓扑图"""
    raise NotImplementedError("TODO: 请实现 build_builtin_reducer_graph")


# ===================================================================================
# 方案三：自定义滑动窗口与计数器归约模式 (Custom Reducer Functions)
# ===================================================================================

def custom_sliding_window_reducer(
    left: list[BaseMessage] | None, 
    right: list[BaseMessage] | None, 
    max_window: int = 3
) -> list[BaseMessage]:
    """
    TODO: 实现自定义滑动窗口归约函数。
    
    要求：
    1. 若 left 或 right 为 None，处理为空列表。
    2. 使用 langgraph.graph.add_messages 融合 left 与 right。
    3. 若融合后的列表长度 > max_window，仅截取并返回尾部最新 max_window 条消息。
    """
    raise NotImplementedError("TODO: 请实现 custom_sliding_window_reducer")


def counter_sum_reducer(left: int | None, right: int | None) -> int:
    """
    TODO: 实现数值累加归约函数。
    返回 left 与 right 之和（自动处理 None 为 0）。
    """
    raise NotImplementedError("TODO: 请实现 counter_sum_reducer")


class CustomReducerState(TypedDict):
    """
    TODO: 声明使用自定义归约器的 TypedDict 状态
    包含字段：
      - messages: 使用 custom_sliding_window_reducer (max_window=3)
      - total_tokens: 使用 counter_sum_reducer
    """
    messages: list[BaseMessage]
    total_tokens: int


async def custom_node_1(state: CustomReducerState) -> dict:
    """节点 1：写入 2 条消息，total_tokens=100"""
    raise NotImplementedError("TODO: 请实现 custom_node_1")


async def custom_node_2(state: CustomReducerState) -> dict:
    """节点 2：写入 2 条消息，total_tokens=150"""
    raise NotImplementedError("TODO: 请实现 custom_node_2")


def build_custom_reducer_graph():
    """TODO: 组装自定义归约拓扑图"""
    raise NotImplementedError("TODO: 请实现 build_custom_reducer_graph")


# ===================================================================================
# 运行主入口与 TODO 拦截提示
# ===================================================================================

async def main():
    print("=" * 80)
    print("【Day 66 默写练习】：TypedDict 状态与 Reducer 归约机制")
    print("=" * 80)
    
    # 方案一测试
    print("\n>>> 调试方案一：浅覆盖模式...")
    try:
        app_1 = build_default_overwrite_graph()
        res_1 = await app_1.ainvoke({"messages": [], "step_count": 0})
        print(f"方案一运行结果 messages 长度: {len(res_1['messages'])}")
    except NotImplementedError as e:
        print(f"🚧 拦截 TODO: {e}")
        
    # 方案二测试
    print("\n>>> 调试方案二：内置 add_messages 归约模式...")
    try:
        app_2 = build_builtin_reducer_graph()
        res_2 = await app_2.ainvoke({"messages": []})
        print(f"方案二运行结果 messages 长度: {len(res_2['messages'])}")
    except NotImplementedError as e:
        print(f"🚧 拦截 TODO: {e}")

    # 方案三测试
    print("\n>>> 调试方案三：自定义滑动窗口与计数器归约...")
    try:
        app_3 = build_custom_reducer_graph()
        res_3 = await app_3.ainvoke({"messages": [], "total_tokens": 0})
        print(f"方案三运行结果 total_tokens: {res_3['total_tokens']}, messages 长度: {len(res_3['messages'])}")
    except NotImplementedError as e:
        print(f"🚧 拦截 TODO: {e}")


if __name__ == "__main__":
    asyncio.run(main())
