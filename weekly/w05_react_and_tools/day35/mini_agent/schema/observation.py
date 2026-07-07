"""
MiniAgent Framework v1.0 — Observation 统一数据模型

设计方案：
1. 设计意图：
   在 Day29-34 的实现中，工具执行结果以裸字符串或非结构化 dict 传递，
   导致 Runner 需要硬编码字段名才能访问状态/延迟等元数据。
   本模块定义统一的 Observation 数据模型，使 Dispatcher → Reducer → Logger
   的全链路都面向同一个结构化对象，消除字段名魔法字符串。

2. 类与函数结构：
   - ObservationStatus: 枚举值，success / error 两种状态。
   - Observation: 基于 Pydantic BaseModel 的结构化工具执行结果容器。

3. 数据流流向：
   - Dispatcher._execute_single_tool() 执行工具后构建 Observation 对象
   - Dispatcher.execute_parallel() 收集所有 Observation 列表
   - StateReducer.merge_parallel_observations() 将 Observation 列表批量归约进 AgentState
   - JSONStepLogger.log_step() 从 Observation 读取所有字段并序列化输出
   - 状态归约时调用 Observation.to_openai_tool_message() 转换为 OpenAI 格式消息
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ObservationStatus(str, Enum):
    """
    Observation 状态枚举。

    继承 str 以支持 JSON 序列化时直接输出字符串值（而非枚举对象），
    方便 Logger 直接 json.dumps 输出而不需要特殊处理。
    """
    SUCCESS = "success"
    ERROR = "error"


class Observation(BaseModel):
    """
    工具执行结果的统一数据模型。

    Dispatcher 执行任意工具后，无论成功或失败，均封装为此模型返回，
    使下游的 Reducer / Logger 面向统一接口编程，彻底消除裸字符串传递。

    Attributes:
        tool_call_id: 大模型下发的工具调用唯一标识，用于与 assistant 消息中的 tool_calls 关联。
        tool_name: 被调用的工具函数名称。
        status: 执行状态，"success" 或 "error"。
        content: 工具执行的文本结果（成功时）或错误描述（失败时）。
        latency_ms: 工具执行耗时，单位毫秒。
        error_type: 异常类型名称，仅在 status == "error" 时填充（如 "ValidationException"）。
        metadata: 扩展元数据字典，预留用于未来 Graph / Multi-Agent 场景传递附加信息。
    """

    # --- 必填字段 ---
    tool_call_id: str = Field(..., description="关联 tool_calls 中的唯一调用 ID")
    tool_name: str = Field(..., description="被调用的工具函数名称")
    status: ObservationStatus = Field(..., description="执行状态: success 或 error")
    content: str = Field(..., description="工具执行文本结果或错误描述")

    # --- 选填字段（含默认值）---
    latency_ms: float = Field(default=0.0, description="工具执行耗时（毫秒）")
    error_type: str | None = Field(default=None, description="异常类型名称（仅 error 时填充）")
    metadata: dict[str, Any] = Field(default_factory=dict, description="扩展元数据字典")

    def to_openai_tool_message(self) -> dict[str, str]:
        """
        将 Observation 转换为符合 OpenAI 规范的 role=tool 消息字典。

        OpenAI API 要求在 tool_calls 后续的消息中，每个工具结果消息必须包含：
        - role: "tool"
        - tool_call_id: 与 assistant.tool_calls[i].id 完全对应
        - content: 工具执行结果文本

        Returns:
            符合 OpenAI API 格式规范的消息字典，可直接追加到 messages 列表。
        """
        return {
            "role": "tool",
            "tool_call_id": self.tool_call_id,
            "name": self.tool_name,
            "content": self.content,
        }

    def is_success(self) -> bool:
        """
        判断工具执行是否成功。

        Returns:
            True 表示执行成功，False 表示执行失败。
        """
        return self.status == ObservationStatus.SUCCESS

    @classmethod
    def from_success(
        cls,
        tool_call_id: str,
        tool_name: str,
        content: str,
        latency_ms: float = 0.0,
        metadata: dict | None = None,
    ) -> "Observation":
        """
        工厂方法：从成功执行结果快速构建 Observation。

        Args:
            tool_call_id: 工具调用唯一 ID。
            tool_name: 工具函数名称。
            content: 工具执行的文本结果。
            latency_ms: 执行耗时（毫秒）。
            metadata: 可选扩展元数据。

        Returns:
            status=success 的 Observation 实例。
        """
        return cls(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            status=ObservationStatus.SUCCESS,
            content=content,
            latency_ms=latency_ms,
            metadata=metadata or {},
        )

    @classmethod
    def from_error(
        cls,
        tool_call_id: str,
        tool_name: str,
        error: Exception,
        latency_ms: float = 0.0,
    ) -> "Observation":
        """
        工厂方法：从执行异常快速构建 Observation（用于异常隔离）。

        Args:
            tool_call_id: 工具调用唯一 ID。
            tool_name: 工具函数名称。
            error: 捕获到的底层异常对象。
            latency_ms: 执行耗时（毫秒）。

        Returns:
            status=error 的 Observation 实例，content 为格式化后的错误描述。
        """
        return cls(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            status=ObservationStatus.ERROR,
            content=f"Error executing tool '{tool_name}': {error}",
            latency_ms=latency_ms,
            error_type=type(error).__name__,
        )
