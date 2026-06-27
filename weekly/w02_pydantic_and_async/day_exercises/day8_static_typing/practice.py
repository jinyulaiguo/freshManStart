from typing import TypedDict, List, Annotated

# 1. 定义消息归约函数 (Reducer)
# 该函数接受旧的消息列表和新的消息，返回合并后的新消息列表
def merge_messages(old_messages: List[str], new_messages: List[str]) -> List[str]:
    """
    归约器：负责在状态机更新时，将新的消息安全地追加到原有的消息列表末尾。
    """
    # TODO: 实现合并逻辑，将新消息追加到旧消息列表中并返回
    return old_messages + new_messages


# 2. 用 TypedDict 定义 AgentState 状态契约
class AgentState(TypedDict):
    """
    Agent 的状态契约，定义了在调度器中流转的全局数据结构。
    """
    # current_tool: 当前执行的工具名称 (str)
    # steps: 当前已运行的步骤数 (int)
    # messages: 使用 Annotated 包装的 List[str]，并附带元数据 merge_messages 归约器
    # TODO: 完成字段定义
    current_tool: str
    steps: int
    messages: Annotated[List[str], merge_messages]


# 3. 编写类型安全的辅助函数
def add_message(state: AgentState, new_msg: str) -> AgentState:
    """
    向现有状态中添加一条新消息，并使步骤数 steps 加 1。
    要求：必须保证类型安全，不能破坏 TypedDict 的契约。
    """
    # TODO: 实现该函数并返回更新后的 state
    # 提示：由于 TypedDict 在运行时只是普通的 dict，可以使用浅拷贝来避免副作用
    new_state = state.copy()
    new_state["steps"] += 1
    # 调用 reducer 合并状态
    new_state["messages"] = merge_messages(new_state["messages"], [new_msg])
    return new_state


def update_tool(state: AgentState, tool_name: str) -> AgentState:
    """
    更新当前执行的工具名称。
    """
    # TODO: 实现该函数
    new_state = state.copy()
    new_state["current_tool"] = tool_name
    return new_state


if __name__ == "__main__":
    # 4. 测试你的实现
    initial_state: AgentState = {
        "current_tool": "none",
        "steps": 0,
        "messages": ["System Initialized."]
    }

    print("初始状态:", initial_state)
    
    # 模拟更新工具
    state_after_tool = update_tool(initial_state, "calculator")
    print("更新工具后:", state_after_tool)
    
    # 模拟添加日志消息
    final_state = add_message(state_after_tool, "Called tool: calculator with arg x=1")
    print("最终状态:", final_state)
