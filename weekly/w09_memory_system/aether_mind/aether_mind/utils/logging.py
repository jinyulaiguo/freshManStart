"""
AetherMind Tracer & Logging Module
==================================

设计方案:
---------
本模块负责提供统一的结构化日志记录与异步请求 Trace 追踪能力。
使用 Python 标准 `logging` 模块进行基础控制台输出，并结合 `contextvars`
实现协程安全的 Request-scoped Trace 链收集器，用于记录 API 调用的耗时与轨迹，
以便于在 SSE 流中实时下发 trace 事件。

结构说明:
---------
- Logger 配置: 初始化控制台日志格式。
- TraceStep: 单步 Trace 节点的数据模型。
- TraceContext: 使用 ContextVar 管理的协程安全 Trace 链管理器。

数据流向:
---------
1. 请求到达时，FastAPI 中间件或主入口初始化 `TraceContext.new_trace()`。
2. 引擎在执行路由、检索、RAG、规划等操作时，调用 `TraceContext.add_step(step_name, content, duration_ms)`。
3. 收集到的 Steps 可以实时被迭代取出发送给 SSE 客户端，并持久化写入 SQLite/PostgreSQL 中的 `trace_log` 表。
"""

import logging
import time
from contextvars import ContextVar
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

# 初始化标准 Logger
logger = logging.getLogger("aether_mind")
logger.setLevel(logging.INFO)

# 避免重复添加 Handler
if not logger.handlers:
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    ch.setFormatter(formatter)
    logger.addHandler(ch)


class TraceStep(BaseModel):
    """
    单步 Trace 节点数据模型，记录执行步骤与相关度耗时。
    """
    step_name: str = Field(..., description="步骤名称，如 'router', 'retrieval'")
    content: str = Field(..., description="步骤详细审计日志")
    duration_ms: int = Field(default=0, description="执行耗时（毫秒）")
    timestamp: float = Field(default_factory=time.time, description="发生时的时间戳")


# 使用 ContextVar 实现多协程并发隔离的 Trace 链管理
_trace_store: ContextVar[List[TraceStep]] = ContextVar("trace_store")


class TraceContext:
    """
    协程安全的 Trace 链管理器。
    """

    @staticmethod
    def new_trace() -> None:
        """
        初始化当前请求/协程上下文的 Trace 链。
        """
        _trace_store.set([])

    @staticmethod
    def get_steps() -> List[TraceStep]:
        """
        获取当前上下文已收集的全部 Trace 步骤。

        Returns:
            List[TraceStep]: Trace 步骤列表。
        """
        try:
            return _trace_store.get()
        except LookupError:
            return []

    @classmethod
    def add_step(cls, step_name: str, content: str, duration_ms: int = 0) -> TraceStep:
        """
        向当前上下文追加一步 Trace，并记录日志。

        Args:
            step_name (str): 步骤类型。
            content (str): 执行详情。
            duration_ms (int): 执行耗时（毫秒）。

        Returns:
            TraceStep: 构造出的 Trace 步骤对象。
        """
        step = TraceStep(step_name=step_name, content=content, duration_ms=duration_ms)
        try:
            steps = _trace_store.get()
            steps.append(step)
            _trace_store.set(steps)
        except LookupError:
            # 如果不在 Trace 上下文中（如离线运行或测试），仅打出 Log 并不报错
            pass

        # 控制台结构化日志打出
        logger.info(f"[{step_name.upper()}] {content} (duration: {duration_ms}ms)")
        return step
