"""
设计方案：
- 设计意图：使用 TypedDict 作为强类型状态容器，借助 Annotated 和专门的 Reducer 函数提供纯函数式的增量状态归约更新（State Reduction）。这种设计模式在多协程并发写入、状态回滚或链路追踪时能确保数据流的确定性和可预测性。
- 类与函数结构：
  - `merge_messages(old, new)` 函数：Reducer，将新日志列表合并入旧日志列表。
  - `merge_tool_results(old, new)` 函数：Reducer，将新产生的工具结果键值对归约并入历史结果字典。
  - `RunnerState` 状态契约（TypedDict）：定义调度器运行过程中的全局状态结构，并用 `Annotated` 显式标注每个复杂类型的归约更新机制。
- 关键数据流向：
  - 工具开始/结束/失败 -> 提取数据事件 -> 调用对应的 Reducer 纯函数合并老状态与新变化 -> 生成并替换为新的 `RunnerState` 状态副本。
"""

from typing import Annotated, Dict, List, TypedDict

def merge_messages(old_messages: List[str], new_messages: List[str]) -> List[str]:
    """
    状态归约逻辑：将新生成的运行时日志列表合并至旧日志列表中。
    """
    if not isinstance(old_messages, list) or not isinstance(new_messages, list):
        raise TypeError("Reducer inputs for messages must be lists of strings.")
    return old_messages + new_messages

def merge_tool_results(old_results: Dict[str, str], new_results: Dict[str, str]) -> Dict[str, str]:
    """
    状态归约逻辑：将当前步骤产生的工具执行结果并入总的结果字典中。
    """
    if not isinstance(old_results, dict) or not isinstance(new_results, dict):
        raise TypeError("Reducer inputs for tool_results must be dictionaries.")
    
    # 浅拷贝合并，防止直接修改引发的副作用
    merged = old_results.copy()
    merged.update(new_results)
    return merged

class RunnerState(TypedDict):
    """
    工具调度引擎的生命周期全局状态契约（基于 Day 8 Annotated + TypedDict 状态归约模式）
    """
    current_tool: str
    total_steps: int
    success_count: int
    error_count: int
    messages: Annotated[List[str], merge_messages]
    tool_results: Annotated[Dict[str, str], merge_tool_results]
