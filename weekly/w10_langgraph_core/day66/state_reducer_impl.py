"""
Day 66 核心实战：TypedDict 状态契约与 Reducer 归约机制 (State Reducers in LangGraph)

===================================================================================
设计方案说明 (Architecture & Design Specification)
===================================================================================
1. 模块设计意图：
   本模块旨在剖析 LangGraph 中 `TypedDict` 状态字段在节点更新时的合并与归约机制。
   通过对比默认浅覆盖模式、内置 `add_messages` 归约模式以及自定义滑动窗口/计数器 Reducer 模式，
   揭示在 Agent 系统多轮对话与状态演进过程中，如何通过数据归约器保障状态的一致性与存储有界性。

2. 关键结构与物理隔离：
   - 方案一【默认浅覆盖模式】：未声明 Reducer 的 TypedDict 状态，演示 Node 后写覆盖先写导致的上下文丢失问题。
   - 方案二【内置 `add_messages` 归约模式】：声明 `Annotated[list[BaseMessage], add_messages]`，演练消息自动追加、基于 ID 的原位更新与 `RemoveMessage` 物理擦除。
   - 方案三【自定义滑动窗口与计数器归约模式】：自定义 `sliding_window_reducer`（严格限制历史消息条数上限）与 `counter_sum_reducer`（处理数值字段递增），演示多字段自定义归约合并。

3. 数据流流向 (Dataflow):
   Input State Snapshot -> Node Function -> Return Partial State Update 
   -> LangGraph Engine Invokes Reducer(left_old_val, right_new_val)
   -> Global State Updated Snapshot -> Next Node / Final Output
===================================================================================
"""

import asyncio
import operator
from typing import TypedDict, Annotated, Sequence
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, RemoveMessage
from langgraph.graph import StateGraph, START, END, add_messages


# ===================================================================================
# 方案一：默认浅覆盖模式 (Default Overwrite Scheme) - 演示状态覆盖与上下文丢失痛点
# ===================================================================================

class DefaultOverwriteState(TypedDict):
    """
    默认浅覆盖状态契约。
    
    【注意】：messages 字段未附带任何 Annotated 归约器修饰。
    在 LangGraph 中，当节点返回 partial update 时，此字段会被完全物理覆盖。
    """
    messages: list[BaseMessage]
    step_count: int


async def overwrite_node_a(state: DefaultOverwriteState) -> dict:
    """节点 A：产生初始用户对话消息"""
    # 步骤 1: 返回包含第一条消息与步数 1 的 Partial Update
    return {
        "messages": [HumanMessage(content="你好，我想咨询退货流程")],
        "step_count": 1
    }


async def overwrite_node_b(state: DefaultOverwriteState) -> dict:
    """节点 B：产生客服回复消息，企图追加回复"""
    # 步骤 2: 返回包含回复消息与步数 2 的 Partial Update
    # 由于没有 Reducer，此处的 messages 会物理覆盖之前的 [HumanMessage]
    return {
        "messages": [AIMessage(content="您好，请提供您的订单编号")],
        "step_count": 2
    }


def build_default_overwrite_graph():
    """构建浅覆盖机制演示图"""
    builder = StateGraph(DefaultOverwriteState)
    builder.add_node("node_a", overwrite_node_a)
    builder.add_node("node_b", overwrite_node_b)
    
    builder.add_edge(START, "node_a")
    builder.add_edge("node_a", "node_b")
    builder.add_edge("node_b", END)
    
    return builder.compile()


# ===================================================================================
# 方案二：内置 `add_messages` 归约模式 (Built-in `add_messages` Reducer Scheme)
# ===================================================================================

class BuiltinReducerState(TypedDict):
    """
    内置归约状态契约。
    
    【核心配置】：使用 Annotated[list[BaseMessage], add_messages]
    使得 LangGraph 引擎在处理 messages 更新时自动使用 add_messages 函数进行追加与去重。
    """
    messages: Annotated[list[BaseMessage], add_messages]


async def builtin_node_initial(state: BuiltinReducerState) -> dict:
    """节点 1：提问与初步答复，固定消息 ID 以备后续更新"""
    # 步骤 1: 产生带固定 ID 的 AIMessage 方便后续演示 ID 原位更新
    msg1 = HumanMessage(content="查询航班 CZ3101", id="usr_msg_1")
    msg2 = AIMessage(content="正在查询航班 CZ3101...", id="ai_msg_temp")
    return {"messages": [msg1, msg2]}


async def builtin_node_update_id(state: BuiltinReducerState) -> dict:
    """节点 2：通过同名 ID 更新先前物理处于临时状态的消息内容"""
    # 步骤 2: 返回同名 id="ai_msg_temp" 的更新版 AIMessage
    # add_messages 会在历史记录中找到该 ID 并将内容更新为最新结果，而非盲目追加
    updated_msg = AIMessage(content="航班 CZ3101 状态：准点，起飞时间 14:30", id="ai_msg_temp")
    return {"messages": [updated_msg]}


async def builtin_node_cleanup(state: BuiltinReducerState) -> dict:
    """节点 3：使用 RemoveMessage 原生实体擦除历史临时消息"""
    # 步骤 3: 使用 RemoveMessage 指定 id 擦除已过期的消息
    return {"messages": [RemoveMessage(id="usr_msg_1")]}


def build_builtin_reducer_graph():
    """构建内置 add_messages 归约演示图"""
    builder = StateGraph(BuiltinReducerState)
    builder.add_node("node_initial", builtin_node_initial)
    builder.add_node("node_update_id", builtin_node_update_id)
    builder.add_node("node_cleanup", builtin_node_cleanup)
    
    builder.add_edge(START, "node_initial")
    builder.add_edge("node_initial", "node_update_id")
    builder.add_edge("node_update_id", "node_cleanup")
    builder.add_edge("node_cleanup", END)
    
    return builder.compile()


# ===================================================================================
# 方案三：自定义滑动窗口与计数器归约模式 (Custom Reducers Scheme)
# ===================================================================================

def sliding_window_messages_reducer(
    left: list[BaseMessage] | None, 
    right: list[BaseMessage] | None,
    max_window: int = 3
) -> list[BaseMessage]:
    """
    自定义滑动窗口消息归约器。
    
    入参：
        left: 当前全局 State 中的既有消息列表
        right: 节点返回的增量消息列表
        max_window: 最多保留的消息总数上限
    返回值：
        融合并做超长裁剪后的最新消息列表
    """
    left_list = left or []
    right_list = right or []
    
    # 1. 使用底层 add_messages 融合合并与 ID 去重
    combined = add_messages(left_list, right_list)
    
    # 2. 物理裁剪：若超出窗口上限，仅保留尾部最新 max_window 条消息
    if len(combined) > max_window:
        return combined[-max_window:]
    return combined


def counter_sum_reducer(left: int | None, right: int | None) -> int:
    """
    自定义数值累加归约器。
    
    入参：
        left: 现有累积数值
        right: 节点增量数值
    返回值：
        两者求和的结果
    """
    return (left or 0) + (right or 0)


class CustomReducerState(TypedDict):
    """
    自定义归约状态契约。
    
    包含：
    1. messages: 带有最大 3 条滑动窗口限额的自定义消息归约器
    2. total_tokens: 使用 operator.add / 自定义累加器计算累加消耗
    """
    messages: Annotated[list[BaseMessage], lambda l, r: sliding_window_messages_reducer(l, r, max_window=3)]
    total_tokens: Annotated[int, counter_sum_reducer]


async def custom_node_1(state: CustomReducerState) -> dict:
    """节点 1：写入 2 条消息，消耗 100 tokens"""
    return {
        "messages": [
            HumanMessage(content="问题 1"),
            AIMessage(content="回答 1")
        ],
        "total_tokens": 100
    }


async def custom_node_2(state: CustomReducerState) -> dict:
    """节点 2：写入 2 条消息，消耗 150 tokens (此时累计 4 条，应触发滑动窗口截断保留最新 3 条)"""
    return {
        "messages": [
            HumanMessage(content="问题 2"),
            AIMessage(content="回答 2")
        ],
        "total_tokens": 150
    }


def build_custom_reducer_graph():
    """构建自定义归约演示图"""
    builder = StateGraph(CustomReducerState)
    builder.add_node("custom_node_1", custom_node_1)
    builder.add_node("custom_node_2", custom_node_2)
    
    builder.add_edge(START, "custom_node_1")
    builder.add_edge("custom_node_1", "custom_node_2")
    builder.add_edge("custom_node_2", END)
    
    return builder.compile()


# ===================================================================================
# 运行主入口与断言验证
# ===================================================================================

async def main():
    print("=" * 80)
    print("【Day 66 实战演练】：TypedDict 状态与 Reducer 归约机制验证")
    print("=" * 80)
    
    # -------------------------------------------------------------------------------
    # 1. 验证浅覆盖模式 (Overriding Failure)
    # -------------------------------------------------------------------------------
    print("\n>>> [1/3] 验证方案一：默认浅覆盖模式 (Default Overwrite)...")
    app_default = build_default_overwrite_graph()
    res_default = await app_default.ainvoke({"messages": [], "step_count": 0})
    
    print(f"最终 messages 数量: {len(res_default['messages'])}")
    print(f"最终消息内容: {[m.content for m in res_default['messages']]}")
    
    # 断言证明：节点 A 的 "你好，我想咨询退货流程" 已经被节点 B 物理覆盖！仅剩 1 条消息！
    assert len(res_default["messages"]) == 1, "浅覆盖模式下应该只剩最后一条消息"
    assert res_default["messages"][0].content == "您好，请提供您的订单编号"
    print("✅ [验证成功]: 成功重现浅覆盖导致的历史消息丢失痛点！")

    # -------------------------------------------------------------------------------
    # 2. 验证内置 add_messages 归约模式 (Append, Update ID & RemoveMessage)
    # -------------------------------------------------------------------------------
    print("\n>>> [2/3] 验证方案二：内置 add_messages 归约模式...")
    app_builtin = build_builtin_reducer_graph()
    res_builtin = await app_builtin.ainvoke({"messages": []})
    
    print(f"最终 messages 数量: {len(res_builtin['messages'])}")
    print(f"最终消息明细:")
    for idx, msg in enumerate(res_builtin["messages"]):
        print(f"  [{idx+1}] ID={msg.id} | Type={type(msg).__name__} | Content={msg.content}")
        
    # 断言验证：
    # 1. usr_msg_1 在节点 3 被 RemoveMessage(id="usr_msg_1") 擦除
    # 2. ai_msg_temp 被节点 2 原位覆盖为最新准点信息
    assert len(res_builtin["messages"]) == 1, "擦除后应仅留存一条更新后的 AI 消息"
    assert res_builtin["messages"][0].id == "ai_msg_temp"
    assert "准点" in res_builtin["messages"][0].content
    print("✅ [验证成功]: add_messages 成功完成 ID 原位更新与 RemoveMessage 擦除！")

    # -------------------------------------------------------------------------------
    # 3. 验证自定义滑动窗口与计数器归约模式 (Custom Reducers)
    # -------------------------------------------------------------------------------
    print("\n>>> [3/3] 验证方案三：自定义滑动窗口与计数器归约模式...")
    app_custom = build_custom_reducer_graph()
    res_custom = await app_custom.ainvoke({"messages": [], "total_tokens": 0})
    
    print(f"最终 total_tokens 累计值: {res_custom['total_tokens']}")
    print(f"最终 messages (窗口上限 max_window=3) 数量: {len(res_custom['messages'])}")
    print(f"截断后的留存消息: {[m.content for m in res_custom['messages']]}")
    
    # 断言验证：
    # 1. total_tokens 应为 100 + 150 = 250
    # 2. 消息原先一共产生 4 条("问题1", "回答1", "问题2", "回答2")，经 max_window=3 截断后只剩后 3 条
    assert res_custom["total_tokens"] == 250, "Total tokens 应该被求和累加为 250"
    assert len(res_custom["messages"]) == 3, "消息列表应被裁剪为最新 3 条"
    assert res_custom["messages"][0].content == "回答 1"
    assert res_custom["messages"][1].content == "问题 2"
    assert res_custom["messages"][2].content == "回答 2"
    print("✅ [验证成功]: 自定义滑动窗口与 Token 累加归约器完全符合期望！")
    
    print("\n" + "=" * 80)
    print("🎉 Day 66 所有三套状态归约机制验证完毕，全部通过！")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
