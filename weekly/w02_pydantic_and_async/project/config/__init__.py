"""
设计方案：
- 设计意图：将 config 模块标识为一个 Python 包，并暴露配置加载类及单例获取方法。
- 类与函数结构：无类，提供包导出声明。
- 关键数据流向：无数据流向。
"""

from .settings import AppSettings

__all__ = ["AppSettings"]
