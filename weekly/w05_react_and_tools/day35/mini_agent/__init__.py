"""
MiniAgent Framework v1.0 — 框架顶层包初始化

提供统一的对外 API 入口，用户只需：
    from mini_agent import ReActAgentRunner, tool, EventBus, JSONStepLogger
"""
from .agent.event_bus import EventBus
from .agent.registry import ToolRegistry, tool
from .agent.runner import ReActAgentRunner
from .logger.json_logger import JSONStepLogger
from .schema.exception import (
    AgentException,
    FatalException,
    RetryExceededException,
    StepOverflowException,
    StuckException,
    TimeoutException,
    ToolException,
    ValidationException,
)

__version__ = "1.0.0"
__author__ = "MiniAgent Framework"

__all__ = [
    # 核心入口
    "ReActAgentRunner",
    "ToolRegistry",
    "tool",
    # 可观测性
    "EventBus",
    "JSONStepLogger",
    # 异常体系
    "AgentException",
    "ToolException",
    "ValidationException",
    "RetryExceededException",
    "StuckException",
    "StepOverflowException",
    "TimeoutException",
    "FatalException",
]
