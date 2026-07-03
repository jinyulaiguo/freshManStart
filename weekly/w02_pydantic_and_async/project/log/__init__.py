"""
设计方案：
- 设计意图：暴露日志模块的唯一入口函数 create_logger。
- 类与函数结构：包导出声明。
- 关键数据流向：无。
"""

from .factory import create_logger

__all__ = ["create_logger"]
