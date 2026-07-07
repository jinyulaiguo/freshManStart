"""MiniAgent Framework v1.0 — tools 子包初始化

导入工具模块会自动触发 @tool 装饰器注册，将三个工具注册到全局 ToolRegistry。
"""
from .calculator import calculator
from .search import web_search
from .weather import get_weather

__all__ = ["get_weather", "calculator", "web_search"]
