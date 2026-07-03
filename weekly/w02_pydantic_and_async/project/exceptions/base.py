"""
设计方案：
- 设计意图：构建高可观测性的异常分层体系，将系统异常与业务错误通过 error_code 进行区分，附带全局追踪的 trace_id 确保能在高并发环境下进行全链路排查，并且对面向用户的提示进行脱敏。
- 类与函数结构：
  - `BaseProjectError` 类：顶层基类，包含 error_code、trace_id 以及 user_message。
  - `ConfigError` 类：配置相关异常。
  - `ToolRegistrationError` 类：工具注册反射异常。
  - `ToolValidationError` 类：工具入参 Pydantic 静态与模型级校验拦截。
  - `ToolExecutionError` 类：工具运行时业务逻辑崩溃异常。
  - `APIConnectionError` 类：子异常，代表外部真实 API 网络超时或连接不可达。
- 关键数据流向：
  - 底层原生/库异常（如 `ValueError`, `httpx.ConnectError`） -> `try-except` 捕获 -> 提取上下文元数据 -> 实例化对应的自定义包装异常并通过 `raise ... from ...` 串联原始堆栈。
"""

import contextvars
import uuid
from typing import Optional

# 线程与协程安全的全局追踪 ID 容器 (Day 13 可观测性工程)
current_trace_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("current_trace_id", default=None)

class BaseProjectError(Exception):
    """项目自定义业务层与系统层异常基类"""
    def __init__(
        self,
        message: str,
        error_code: int = 50000,
        trace_id: Optional[str] = None,
        user_message: str = "系统执行异常，请稍后重试"
    ):
        # 1. 优先采用显式传入的 trace_id，其次采用 contextvar 容器中的 trace_id，最后生成全新 UUID
        ctx_trace_id = current_trace_id.get()
        self.trace_id = trace_id or ctx_trace_id or str(uuid.uuid4())
        
        # 2. 将包含有效 TraceID 的格式化字符串传递给 Exception 基类，防止出现 [TraceID: N/A]
        super().__init__(f"[ErrCode: {error_code}][TraceID: {self.trace_id}] {message}")
        self.message = message
        self.error_code = error_code
        self.user_message = user_message

class ConfigError(BaseProjectError):
    """配置加载与解析相关错误"""
    def __init__(self, message: str, trace_id: Optional[str] = None):
        super().__init__(
            message=message,
            error_code=40001,
            trace_id=trace_id,
            user_message="配置项缺失或格式非法，请检查系统环境"
        )

class ToolRegistrationError(BaseProjectError):
    """工具注册与自动扫描反射阶段发生的错误"""
    def __init__(self, message: str, trace_id: Optional[str] = None):
        super().__init__(
            message=message,
            error_code=40002,
            trace_id=trace_id,
            user_message="调度引擎初始化工具集失败，服务不可用"
        )

class ToolValidationError(BaseProjectError):
    """外部输入参数 Pydantic 反序列化或字段拦截失败"""
    def __init__(self, message: str, trace_id: Optional[str] = None):
        super().__init__(
            message=message,
            error_code=40003,
            trace_id=trace_id,
            user_message="请求参数验证不通过，请检查入参格式"
        )

class ToolExecutionError(BaseProjectError):
    """工具核心计算或网络通信逻辑执行阶段抛出的异常"""
    def __init__(
        self,
        message: str,
        trace_id: Optional[str] = None,
        user_message: str = "外部工具运行出错",
        error_code: int = 50001
    ):
        super().__init__(
            message=message,
            error_code=error_code,
            trace_id=trace_id,
            user_message=user_message
        )

class APIConnectionError(ToolExecutionError):
    """外部真实 API 连接超时或服务网络抖动故障"""
    def __init__(self, message: str, trace_id: Optional[str] = None):
        super().__init__(
            message=message,
            trace_id=trace_id,
            user_message="网络连接故障，外部天气或汇率查询服务暂时不可达",
            error_code=50002
        )
