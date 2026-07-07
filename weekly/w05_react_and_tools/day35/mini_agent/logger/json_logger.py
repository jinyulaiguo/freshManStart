"""
MiniAgent Framework v1.0 — JSONStepLogger 结构化步骤日志记录器

设计方案：
1. 设计意图：
   工业级 Agent 系统的可观测性要求：每一步的状态转移、工具入参、
   Observation 返回、Token 消耗都以统一的结构化 JSON 格式输出，
   方便 Debug、Replay 和监控系统接入。

   通过订阅 EventBus 的事件，Logger 完全解耦于 Runner，
   Runner 只需发布事件，Logger 自动响应记录。

2. 输出格式（每步 JSON 示例）：
   {
       "event": "on_tool_end",
       "step": 2,
       "thought": "查询天气",
       "tool": "get_weather",
       "arguments": {"city": "杭州"},
       "observation": "杭州今日晴天，温度 25℃",
       "status": "success",
       "latency_ms": 123.4,
       "prompt_tokens": 321,
       "completion_tokens": 67,
       "cost_usd": 0.0021
   }

3. 数据流流向：
   EventBus.publish("on_tool_end", payload) → JSONStepLogger.on_tool_end(payload)
   → json.dumps 序列化 → print 输出到 stdout
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..agent.event_bus import EventBus
    from ..schema.observation import Observation


class JSONStepLogger:
    """
    结构化 JSON 步骤日志记录器。

    通过 EventBus 订阅 Agent 运行期的关键事件，将每一步的执行信息
    以标准 JSON 格式输出到 stdout，支持日志收集、问题追踪和执行重放。

    输出到 stdout 的每行均为合法的 JSON 对象字符串，方便管道（pipeline）
    处理或日志收集系统（如 Logstash）实时解析。
    """

    def __init__(self, event_bus: "EventBus | None" = None) -> None:
        """
        初始化日志记录器，自动订阅 EventBus 的关键事件。

        Args:
            event_bus: 可选的事件总线实例。若提供，则自动注册所有事件 Handler。
                       若为 None，Logger 仍可手动调用 log_step 方法。
        """
        self.event_bus = event_bus
        # 跨事件缓冲区：缓存同一步骤中不同事件的数据，用于拼装完整的步骤日志
        self._step_buffer: dict[int, dict[str, Any]] = {}

        if event_bus:
            self._register_handlers()

    def _register_handlers(self) -> None:
        """向 EventBus 注册所有事件 Handler。"""
        bus = self.event_bus
        bus.subscribe("on_step_start", self._on_step_start)
        bus.subscribe("on_llm_end", self._on_llm_end)
        bus.subscribe("on_tool_start", self._on_tool_start)
        bus.subscribe("on_tool_end", self._on_tool_end)
        bus.subscribe("on_retry", self._on_retry)
        bus.subscribe("on_error", self._on_error)
        bus.subscribe("on_stuck", self._on_stuck)
        bus.subscribe("on_finish", self._on_finish)

    def _emit(self, data: dict[str, Any]) -> None:
        """
        将数据字典序列化为单行 JSON 字符串并输出到 stdout。

        Args:
            data: 要输出的日志数据字典。
        """
        print(json.dumps(data, ensure_ascii=False, default=str))

    def log_step(self, step_data: dict[str, Any]) -> None:
        """
        手动记录一条步骤日志（不依赖 EventBus 时使用）。

        Args:
            step_data: 步骤数据字典，应包含 event / step 等核心字段。
        """
        self._emit(step_data)

    # ==================== EventBus Handler 实现 ====================

    def _on_step_start(self, payload: dict) -> None:
        """每轮决策循环开始事件处理。"""
        step = payload.get("step", 0)
        # 初始化此步骤的缓冲区
        self._step_buffer[step] = {"step": step}
        self._emit({
            "event": "on_step_start",
            "step": step,
        })

    def _on_llm_end(self, payload: dict) -> None:
        """LLM API 调用完成事件处理。"""
        step = payload.get("step", 0)
        # 缓存此步骤的 LLM 响应信息
        if step in self._step_buffer:
            self._step_buffer[step].update({
                "thought": payload.get("thought", ""),
                "action": payload.get("action", ""),
                "prompt_tokens": payload.get("prompt_tokens", 0),
                "completion_tokens": payload.get("completion_tokens", 0),
                "cost_usd": payload.get("cost", 0.0),
                "llm_latency_ms": payload.get("latency_ms", 0.0),
            })
        self._emit({
            "event": "on_llm_end",
            "step": step,
            "thought": payload.get("thought", ""),
            "action": payload.get("action", ""),
            "prompt_tokens": payload.get("prompt_tokens", 0),
            "completion_tokens": payload.get("completion_tokens", 0),
            "cost_usd": payload.get("cost", 0.0),
            "llm_latency_ms": round(payload.get("latency_ms", 0.0), 2),
        })

    def _on_tool_start(self, payload: dict) -> None:
        """工具执行开始事件处理。"""
        self._emit({
            "event": "on_tool_start",
            "step": payload.get("step", 0),
            "tool": payload.get("tool_name", ""),
            "call_id": payload.get("call_id", ""),
            "arguments": payload.get("params", {}),
        })

    def _on_tool_end(self, payload: dict) -> None:
        """工具执行完成事件处理（含完整步骤信息的聚合日志）。"""
        step = payload.get("step", 0)
        obs: "Observation | None" = payload.get("observation")

        # 从 Observation 提取信息
        obs_content = str(obs.content) if obs else ""
        obs_status = obs.status.value if obs else "unknown"
        obs_latency = obs.latency_ms if obs else 0.0
        obs_tool = obs.tool_name if obs else payload.get("tool_name", "")
        obs_call_id = obs.tool_call_id if obs else payload.get("call_id", "")

        # 获取缓冲的 LLM 信息
        buf = self._step_buffer.get(step, {})

        # 输出完整的步骤聚合日志
        self._emit({
            "event": "on_tool_end",
            "step": step,
            "thought": buf.get("thought", ""),
            "tool": obs_tool,
            "call_id": obs_call_id,
            "observation": obs_content,
            "status": obs_status,
            "tool_latency_ms": round(obs_latency, 2),
            "prompt_tokens": buf.get("prompt_tokens", 0),
            "completion_tokens": buf.get("completion_tokens", 0),
            "cost_usd": buf.get("cost_usd", 0.0),
        })

    def _on_retry(self, payload: dict) -> None:
        """Self-Correction 自愈重试事件处理。"""
        self._emit({
            "event": "on_retry",
            "step": payload.get("step", 0),
            "tool": payload.get("tool_name", ""),
            "error": payload.get("error", ""),
            "retry_count": payload.get("retry_count", 0),
        })

    def _on_error(self, payload: dict) -> None:
        """异常捕获事件处理。"""
        self._emit({
            "event": "on_error",
            "step": payload.get("step", 0),
            "error_type": payload.get("error_type", ""),
            "error_message": payload.get("error_message", ""),
        })

    def _on_stuck(self, payload: dict) -> None:
        """死循环拦截事件处理。"""
        self._emit({
            "event": "on_stuck",
            "step": payload.get("step", 0),
            "action": payload.get("action", ""),
            "hash": payload.get("hash", ""),
            "window_size": payload.get("window_size", 0),
        })

    def _on_finish(self, payload: dict) -> None:
        """任务完成事件处理（含最终摘要）。"""
        self._emit({
            "event": "on_finish",
            "finish_reason": payload.get("finish_reason", ""),
            "final_reply": payload.get("final_reply", ""),
            "summary": payload.get("summary", {}),
        })
