"""
设计方案：
- 设计意图：暴露异常层，方便外部模块一键导入所有自定义异常。
- 类与函数结构：包导出定义。
- 关键数据流向：无。
"""

from .base import (
    BaseProjectError,
    ConfigError,
    ToolRegistrationError,
    ToolValidationError,
    ToolExecutionError,
    APIConnectionError,
)

__all__ = [
    "BaseProjectError",
    "ConfigError",
    "ToolRegistrationError",
    "ToolValidationError",
    "ToolExecutionError",
    "APIConnectionError",
]
