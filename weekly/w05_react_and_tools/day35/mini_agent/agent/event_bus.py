"""
MiniAgent Framework v1.0 — EventBus 事件总线 [BONUS ★★★★★]

设计方案：
1. 设计意图：
   现代 Agent 框架（LangGraph、OpenAI Agents SDK）的共同设计思路：
   Runner 不直接打印日志，而是在关键节点发布事件，Logger / Monitor / UI / Trace
   各自订阅所需事件，与 Runner 解耦。
   
   这是一个同步的 Pub/Sub 实现（Publisher/Subscriber 发布订阅模式），
   支持多个 Handler 订阅同一个事件，发布时顺序触发所有 Handler。

   为什么是同步而非异步？
   - Logger 的 IO 操作（stdout 输出）极快，无需异步
   - 同步调用简化了 Runner 的事件发布代码（无需 await）
   - 若需要异步 Handler，可在 Handler 内部使用 asyncio.create_task 自行调度

2. 预定义事件类型：
   on_step_start    — 每轮决策循环开始（payload: step, state_summary）
   on_llm_start     — LLM API 调用开始（payload: step, messages_count）
   on_llm_end       — LLM API 调用结束（payload: step, thought, action, latency_ms, usage）
   on_tool_start    — 单个工具执行开始（payload: step, tool_name, call_id, params）
   on_tool_end      — 单个工具执行结束（payload: step, tool_name, observation）
   on_retry         — 触发 Self-Correction 自愈重试（payload: step, tool_name, error, retry_count）
   on_error         — 捕获到异常（payload: step, error_type, error_message）
   on_stuck         — 死循环拦截触发（payload: step, action, hash）
   on_step_end      — 每轮决策循环结束（payload: step, state_summary）
   on_finish        — 任务完成（payload: finish_reason, state_summary）

3. 数据流流向：
   Runner.run() → 在每个关键节点调用 event_bus.publish(event_type, payload)
   EventBus.publish() → 顺序触发所有订阅了该事件类型的 Handler
   JSONStepLogger → 在 __init__ 中通过 event_bus.subscribe() 订阅所有事件
"""
from __future__ import annotations

from typing import Any, Callable

# ==================== 预定义事件类型常量 ====================
EVENT_STEP_START = "on_step_start"
EVENT_LLM_START = "on_llm_start"
EVENT_LLM_END = "on_llm_end"
EVENT_TOOL_START = "on_tool_start"
EVENT_TOOL_END = "on_tool_end"
EVENT_RETRY = "on_retry"
EVENT_ERROR = "on_error"
EVENT_STUCK = "on_stuck"
EVENT_STEP_END = "on_step_end"
EVENT_FINISH = "on_finish"


class EventBus:
    """
    轻量级同步事件总线（Pub/Sub 发布订阅模式）。

    Runner 在关键节点发布事件（publish），Logger / Monitor / UI 等组件
    通过 subscribe 注册回调函数（Handler），实现 Runner 与可观测性组件的完全解耦。

    设计特点：
    - 同一事件支持多个 Handler 订阅（按订阅顺序顺序触发）
    - Handler 抛出的异常被静默捕获（不影响 Runner 主流程）
    - 支持通配符订阅（event_type="*" 订阅所有事件）
    - 线程安全：Handler 列表在发布时快照，避免迭代时修改

    典型使用场景：
        event_bus = EventBus()

        # Logger 订阅所有工具执行完成事件
        event_bus.subscribe(EVENT_TOOL_END, logger.on_tool_end)

        # Runner 在工具执行完成后发布事件
        event_bus.publish(EVENT_TOOL_END, {
            "step": 2,
            "tool_name": "get_weather",
            "observation": observation
        })
    """

    def __init__(self) -> None:
        """初始化事件总线，创建空的事件 → Handler 映射字典。"""
        # 内部存储：{event_type: [handler1, handler2, ...]}
        self._handlers: dict[str, list[Callable[[dict], None]]] = {}
        # 通配符订阅列表（订阅所有事件类型的 Handler）
        self._wildcard_handlers: list[Callable[[str, dict], None]] = []

    def subscribe(
        self,
        event_type: str,
        handler: Callable[[dict], None],
    ) -> None:
        """
        订阅指定事件类型，注册回调 Handler 函数。

        同一个事件类型可以注册多个 Handler，发布时按注册顺序依次触发。

        Args:
            event_type: 事件类型字符串（使用预定义常量，如 EVENT_LLM_END）。
            handler: 回调函数，签名为 (payload: dict) -> None。
                     payload 内容由发布者定义，不同事件类型的 payload 结构不同。
        """
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)

    def subscribe_all(
        self,
        handler: Callable[[str, dict], None],
    ) -> None:
        """
        订阅所有事件类型（通配符订阅）。

        用于需要接收所有事件的组件（如全量事件记录器、调试追踪器）。

        Args:
            handler: 通配符回调函数，签名为 (event_type: str, payload: dict) -> None。
        """
        self._wildcard_handlers.append(handler)

    def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        """
        发布事件，触发所有订阅了该事件类型的 Handler。

        Handler 的异常被静默捕获并打印（不影响 Runner 主流程）。
        发布时对 Handler 列表进行快照（list()），支持 Handler 内部修改订阅而不影响当前发布迭代。

        Args:
            event_type: 事件类型字符串。
            payload: 事件载荷字典（包含事件相关的上下文数据）。
        """
        # 1. 触发精确订阅的 Handler
        handlers_snapshot = list(self._handlers.get(event_type, []))
        for handler in handlers_snapshot:
            try:
                handler(payload)
            except Exception as e:
                # 静默捕获 Handler 异常，不影响 Runner 主流程
                # 使用 print 而非 Logger 防止循环依赖
                print(f"[EventBus] Handler 执行异常（已静默忽略）: {e}")

        # 2. 触发通配符 Handler
        wildcard_snapshot = list(self._wildcard_handlers)
        for handler in wildcard_snapshot:
            try:
                handler(event_type, payload)
            except Exception as e:
                print(f"[EventBus] 通配符 Handler 执行异常（已静默忽略）: {e}")

    def unsubscribe(
        self,
        event_type: str,
        handler: Callable[[dict], None],
    ) -> bool:
        """
        取消订阅指定事件类型的某个 Handler。

        Args:
            event_type: 事件类型字符串。
            handler: 要取消的 Handler 函数对象（必须与 subscribe 时传入的是同一个对象）。

        Returns:
            True 表示取消成功，False 表示该 Handler 未在订阅列表中。
        """
        if event_type in self._handlers and handler in self._handlers[event_type]:
            self._handlers[event_type].remove(handler)
            return True
        return False

    def clear(self, event_type: str | None = None) -> None:
        """
        清空 Handler 订阅。

        Args:
            event_type: 若提供，则只清空该事件类型的订阅；若为 None，则清空所有订阅。
        """
        if event_type is not None:
            self._handlers.pop(event_type, None)
        else:
            self._handlers.clear()
            self._wildcard_handlers.clear()

    def subscriber_count(self, event_type: str) -> int:
        """
        返回指定事件类型的当前订阅者数量。

        Args:
            event_type: 事件类型字符串。

        Returns:
            该事件类型已注册的 Handler 数量。
        """
        return len(self._handlers.get(event_type, []))
