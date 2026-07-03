"""
设计方案：
- 设计意图：使用 PEP 544 Protocol 鸭子类型契约定义工具的生命周期回调接口。它为调度引擎提供了一种低耦合、高度可插拔的可观测性通知网关。任何实现该接口的类均可作为旁路监控、追踪、日志记录或 UI 推送器注入调度引擎。
- 类与函数结构：
  - `ToolCallbackProtocol` 接口（Protocol）：声明了工具生命周期中的三个关键挂钩（Hooks）：
    - `on_tool_start`: 工具启动前回调。
    - `on_tool_success`: 工具正常结束并返回结果后回调。
    - `on_tool_error`: 工具抛出异常崩溃时回调。
- 关键数据流向：
  - 调度引擎运行节点 -> 收集上下文数据（trace_id, tool_name, 参数/结果/异常） -> 触发绑定的回调接口方法进行旁路记录。
"""

from typing import Protocol, Any

class ToolCallbackProtocol(Protocol):
    """工具生命周期可观测性回调契约"""
    def on_tool_start(self, trace_id: str, tool_name: str, raw_args: str) -> None:
        """当工具开始被解析和调度时触发"""
        ...

    def on_tool_success(self, trace_id: str, tool_name: str, result: str, duration: float) -> None:
        """当工具成功执行并获得有效返回值时触发"""
        ...

    def on_tool_error(self, trace_id: str, tool_name: str, error: Exception, duration: float) -> None:
        """当工具在校验或网络/CPU 执行过程中崩溃并引发异常时触发"""
        ...
