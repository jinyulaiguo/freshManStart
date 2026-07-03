"""
设计方案：
- 设计意图：暴露回调模块，供调度引擎引用。
- 类与函数结构：包导出声明。
- 关键数据流向：无。
"""

from .base import ToolCallbackProtocol
from .console_tracer import ConsoleTracer

__all__ = ["ToolCallbackProtocol", "ConsoleTracer"]
