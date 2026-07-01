"""
Day 8 状态管理器：从“函数式更新”演进为“类型反射引擎”的设计方案

一、设计意图与演进对比 (Design Intent & Evolution)
在编写复杂的 Agent 系统时，状态（State）通常经历以下两种更新方案的演进：

1. 传统/初级方案 (传统函数式流转)
   - 对应方法：`update_tool()`, `add_message()`
   - 设计思想：纯手写业务更新逻辑，通过特化的辅助函数在内部进行状态字典的 `.copy()` 并返回。
   - 局限性：状态变更逻辑（如 `messages` 追加的同时伴随 `steps` 加 1）与具体函数强绑定，极易产生隐式副作用；字段增多时，辅助函数过度膨胀。

2. 现代/反射方案 (面向对象反射引擎)
   - 对应类/方法：`StateTracker` 类, `AgentState` 契约, `merge_messages()` 归约器
   - 设计思想：通过统一的 `update()` 方法为唯一入口，利用运行时类型反射（Reflection）解析属性的 `Annotated` 元数据，将字段自动路由（Auto-wire）给对应的 `Reducer`（如 `merge_messages`）执行归约。
   - 优势：高通用性、单一职责原则。各个字段的更新策略独立定义，且在入口处提供未定义字段校验（防御性编程）。

二、代码范畴与归属关系 (Scopes & Categorization)
1. 传统更新方案范畴 (Traditional Paradigm)
   ├── update_tool: 接收状态和工具名称，直接拷贝覆盖 current_tool。
   └── add_message: 接收状态和消息，追加消息并硬编码 steps 加 1 副作用。

2. 反射引擎方案范畴 (Reflection OOP Paradigm)
   ├── AgentState (TypedDict): 类型契约，在编译/静态期约束结构。
   ├── merge_messages (Reducer): 绑定的消息追加归约函数。
   └── StateTracker (Engine): 反射解析器与数据网关，包含：
       ├── _parse_schema: 运行时反射引擎（利用 hints 解析 Annotated）。
       ├── update: 契约拦截与策略合并网关。
       └── state (property): 防篡改只读数据输出。
"""
from typing import TypedDict, List, Annotated, Dict, Any, Type, get_type_hints, get_origin, get_args


# =========================================================================
# 1. 传统函数式状态更新方案 (Traditional Functional Paradigm)
# =========================================================================

class AgentStateTraditional(TypedDict):
    """
    传统方案的状态契约，仅作为普通字典的静态类型提示。
    """
    current_tool: str
    steps: int
    messages: List[str]


def merge_messages_traditional(old_messages: List[str], new_messages: List[str]) -> List[str]:
    """
    传统辅助合并函数：负责将新的消息列表合并到原有列表中。
    """
    if not isinstance(old_messages, list) or not isinstance(new_messages, list):
        raise TypeError("Reducer inputs must be list types.")
    return old_messages + new_messages


def add_message(state: AgentStateTraditional, new_msg: str) -> AgentStateTraditional:
    """
    向现有状态中添加一条新消息，并使步骤数 steps 加 1（伴随强耦合的 steps 自增副作用）。
    """
    new_state = state.copy()
    new_state["steps"] += 1
    new_state["messages"] = merge_messages_traditional(new_state["messages"], [new_msg])
    return new_state


def update_tool(state: AgentStateTraditional, tool_name: str) -> AgentStateTraditional:
    """
    更新当前执行的工具名称。
    """
    new_state = state.copy()
    new_state["current_tool"] = tool_name
    return new_state


# =========================================================================
# 2. 类型反射状态追踪引擎方案 (Reflection OOP Paradigm)
# =========================================================================

def merge_messages(old_messages: List[str], new_messages: List[str]) -> List[str]:
    """
    归约器：负责在状态更新时，将新的消息安全地追加到原有的消息列表末尾。
    并且进行运行时类型防错校验。
    """
    if not isinstance(old_messages, list) or not isinstance(new_messages, list):
        raise TypeError("Reducer inputs must be list types.")
    return old_messages + new_messages


class AgentState(TypedDict):
    """
    Agent 的状态契约，定义了在调度器中流转的全局数据结构，并通过 Annotated 绑定了 Reducer。
    """
    current_tool: str
    steps: int
    messages: Annotated[List[str], merge_messages]


class StateTracker:
    """
    状态追踪引擎：负责在运行时解析类型契约，并在更新状态时自动应用归约逻辑。
    """
    def __init__(self, schema: Any, initial_state: Any):
        self._schema = schema
        self._reducers: Dict[str, Any] = {}
        self._expected_keys: List[str] = []
        
        # 反射解析契约
        self._parse_schema()
        
        # 初始化状态并校验
        self._state: Dict[str, Any] = {}
        self.update(initial_state)

    def _parse_schema(self) -> None:
        """
        利用运行时反射解析 schema 中的类型注解与 Annotated 绑定的元数据。
        """
        hints = get_type_hints(self._schema, include_extras=True)
        self._expected_keys = list(hints.keys())
        
        for key, hint in hints.items():
            origin = get_origin(hint)
            if origin is Annotated:
                args = get_args(hint)
                # 遍历元数据，寻找 Callable（即归约函数）
                for meta in args[1:]:
                    if callable(meta):
                        self._reducers[key] = meta
                        break

    @property
    def state(self) -> Dict[str, Any]:
        """
        获取当前状态的只读拷贝，防止外部绕过引擎篡改内部状态。
        """
        return self._state.copy()

    def update(self, new_data: Dict[str, Any]) -> None:
        """
        更新状态。如果字段定义了归约器，则进行增量归约；否则直接覆盖。
        """
        for key, value in new_data.items():
            # 契约拦截：防范未定义字段写入
            if key not in self._expected_keys:
                raise KeyError(f"Key '{key}' is not defined in the state schema.")
            
            # 状态合并：如果存在 Reducer 则增量合并，否则直接替换
            if key in self._reducers:
                old_val = self._state.get(key, [])
                reducer = self._reducers[key]
                self._state[key] = reducer(old_val, value)
            else:
                self._state[key] = value



if __name__ == "__main__":
    # =========================================================================
    # 对比演示：状态管理的两代演进与设计哲学差异
    # =========================================================================
    
    initial: AgentState = {
        "current_tool": "none",
        "steps": 0,
        "messages": ["System Initialized."]
    }

    # -------------------------------------------------------------------------
    # 【演进阶段 1】函数式辅助函数流转 (硬编码副作用)
    # 特点：每次修改都需要手写特化的辅助函数，且在 add_message 中硬编码了 steps += 1 的隐式副作用。
    # -------------------------------------------------------------------------
    print("=== 方式一：函数式辅助函数流转 ===")
    print("初始状态:", initial)
    
    state_after_tool = update_tool(initial, "calculator")
    print("更新工具后:", state_after_tool)
    
    # 此时 steps 隐式自增了 1
    final_state = add_message(state_after_tool, "Called tool: calculator with arg x=1")
    print("最终状态 (steps=1, 因为 add_message 内部硬编码了自增):", final_state)
    
    # -------------------------------------------------------------------------
    # 【演进阶段 2】面向对象状态追踪引擎 (类型驱动与单一职责)
    # 特点：统一 update 入口。每个字段的更新规则完全声明在 TypedDict 的 Annotated 中。
    #      遵循“单一职责”，除非显式更新或声明，否则不产生跨字段的隐式副作用（steps 不会自动自增）。
    # -------------------------------------------------------------------------
    print("\n=== 方式二：StateTracker 引擎自动路由 ===")
    tracker = StateTracker(AgentState, initial)
    
    # 1. 更新工具
    tracker.update({"current_tool": "calculator"})
    
    # 2. 仅更新消息（此时 steps 保持单一职责，不会产生自增副作用）
    tracker.update({"messages": ["Called tool: calculator with arg x=1"]})
    print("仅更新消息后的状态 (steps=0, 保持单一职责):", tracker.state)
    
    # 3. 如果需要同步更新步骤，应在节点逻辑中显式传递变更：
    # tracker.update({
    #     "messages": ["Called tool: calculator with arg x=1"],
    #     "steps": tracker.state["steps"] + 1
    # })

