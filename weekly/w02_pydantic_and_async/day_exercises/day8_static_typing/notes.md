# Day 8：静态类型注解与 TypedDict

本节重点关注如何使用类型注解来确保我们的 Agent 内部状态机是类型安全的。我们将重点掌握 `TypedDict` 与 `Annotated` 的用法。

---

## 📖 核心概念讲解

### 1. 为什么需要静态类型注解？
Python 是动态语言，但是在编写复杂的 Agent 系统时，类型模糊容易导致很多严重的 bug（如拼错字典键名、传入了非法的参数类型等）。
使用类型注解可以：
* 让 IDE 提供极其精准的代码自动补全。
* 在运行前通过静态代码分析工具（如 `mypy`）找出潜在的类型错误。

### 2. TypedDict：字典的类型契约
传统的 Python `dict` 是松散的，我们可以随意读写任意 key。而在 Agent 状态流转中，我们需要确保字典的 Key 结构完全固定。
```python
from typing import TypedDict, List

class AgentState(TypedDict):
    current_tool: str
    steps: int
    messages: List[str]
```
* **注意**：`TypedDict` 在运行时只是一个普通的 `dict`，类型检查完全发生于**静态检查阶段（mypy 或 IDE）**。它不会在运行时拦截不匹配的输入（这是 Pydantic 的工作）。

### 3. Annotated：类型与元数据的绑定
`Annotated` 允许我们在声明类型的外部，附加上任意的元数据（Metadata）。这些元数据不会影响类型检查本身，但是可以被运行时框架（如 LangGraph 的状态归约机制）提取并处理。
```python
from typing import Annotated, List

# 声明一个类型，并附带合并逻辑（Reducer）元数据
StateMessages = Annotated[List[str], merge_messages_function]
```
