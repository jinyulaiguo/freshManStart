"""
MiniAgent Framework v1.0 — ToolDispatcher 工具调度器

设计方案：
1. 设计意图：
   将 Day32 的 dispatch_tool 方法和 Day33 的 execute_parallel_tools 方法
   从 MiniReActEngine 中物理分离，封装为独立的 ToolDispatcher 类。
   
   职责边界：
   - 只负责：从 ToolRegistry 获取工具、Pydantic 参数校验、反射执行、计时、异常包装为 Observation
   - 不负责：死循环检测（StuckDetector 的事）
   - 不负责：状态归约（StateReducer 的事）
   - 不负责：重试管理（RetryManager 的事）
   
   对比 Day32/33 的变化：
   - 执行结果统一返回 Observation 对象而非裸字符串
   - 支持超时守卫（asyncio.wait_for）
   - 发布 EventBus 事件（on_tool_start / on_tool_end）

2. 类与函数结构：
   - ToolDispatcher: 工具调度器
     - __init__(registry, event_bus, tool_timeout): 初始化
     - dispatch(tool_name, raw_params, call_id): 单工具调度（含校验/计时/异常隔离）
     - execute_parallel(tool_calls): 并行调度多个工具（asyncio.gather）
     - _execute_single(call_id, action, params): 单工具执行包装（异常隔离）

3. 数据流流向：
   - Runner 检测到 LLM 下发 tool_calls 后，调用 execute_parallel(tool_calls)
   - execute_parallel 将每个 tool_call 转换为 _execute_single 协程
   - asyncio.gather 并发执行所有协程，return_exceptions=True
   - _execute_single 内部调用 dispatch，dispatch 执行 Pydantic 校验 + 反射调用
   - 所有工具返回 Observation 对象（成功或失败），收集为列表
   - Runner 将 Observation 列表传给 StateReducer.merge_parallel_observations()
"""
from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

from ..schema.exception import TimeoutException, ToolException, ValidationException
from ..schema.observation import Observation

if TYPE_CHECKING:
    from .event_bus import EventBus
    from .registry import ToolRegistry


class ToolDispatcher:
    """
    工具反射调度器。

    负责将 LLM 的工具调用决策（tool_name + raw_params）转化为对
    本地 Python 异步函数的实际执行，包含 Pydantic 参数校验、计时、
    超时守卫和异常包装，并以统一的 Observation 对象返回执行结果。

    并行执行时通过 asyncio.gather 实现非阻塞并发，单个工具失败不
    影响其他工具的正常执行（异常隔离）。
    """

    def __init__(
        self,
        registry: "ToolRegistry",
        event_bus: "EventBus | None" = None,
        tool_timeout: float = 30.0,
    ) -> None:
        """
        初始化工具调度器。

        Args:
            registry: 工具注册中心，提供工具函数和 Pydantic 校验模型。
            event_bus: 可选的事件总线，若提供则在工具执行前后发布事件。
            tool_timeout: 单个工具执行的最大允许时间（秒），默认 30 秒。
                         超时后抛出 TimeoutException（可触发 Self-Correction）。
        """
        self.registry = registry
        self.event_bus = event_bus
        self.tool_timeout = tool_timeout

    async def dispatch(
        self,
        tool_name: str,
        raw_params: dict[str, Any],
        call_id: str,
        step: int = 0,
    ) -> Observation:
        """
        单工具调度：Pydantic 参数校验 → 反射解包执行 → 计时 → 返回 Observation。

        执行流程：
        1. 检查工具是否在 Registry 中注册
        2. 从 Registry 获取 Pydantic 校验模型，对 raw_params 执行强类型校验
        3. 发布 on_tool_start 事件
        4. 反射解包校验后的参数，在超时守卫内 await 执行工具协程
        5. 计算执行耗时 latency_ms
        6. 发布 on_tool_end 事件
        7. 返回成功或失败的 Observation 对象

        Args:
            tool_name: 要调用的工具函数名称。
            raw_params: LLM 输出的原始参数字典（未经校验）。
            call_id: 工具调用的唯一标识（来自 LLM 的 tool_call_id）。
            step: 当前执行步数（用于事件 payload）。

        Returns:
            Observation 对象（无论成功或失败均返回，不抛出异常）。

        Raises:
            ToolException: 工具函数在执行期发生内部异常时抛出（由调用方决定是否 Self-Correction）。
            ValidationException: Pydantic 参数校验失败时抛出（由调用方决定是否 Self-Correction）。
            TimeoutException: 工具执行超时时抛出。
            KeyError: 工具名称未注册时抛出（FatalException 由 Runner 捕获）。
        """
        # 1. 检查工具是否已注册
        if tool_name not in self.registry:
            raise KeyError(
                f"工具 '{tool_name}' 未在注册中心注册。已注册工具：{self.registry.list_tools()}"
            )

        func = self.registry.get_tool_func(tool_name)
        model = self.registry.get_tool_model(tool_name)

        # 2. Pydantic 参数契约校验（自动类型转换 + 必填字段检查 + 默认值补全）
        try:
            validated_data = model(**raw_params)
        except Exception as e:
            raise ValidationException(tool_name=tool_name, validation_error=str(e))

        clean_args = validated_data.model_dump()

        # 3. 发布 on_tool_start 事件
        if self.event_bus:
            self.event_bus.publish("on_tool_start", {
                "step": step,
                "tool_name": tool_name,
                "call_id": call_id,
                "params": clean_args,
            })

        # 4. 在超时守卫内执行工具（计时开始）
        start_ts = time.monotonic()
        try:
            result = await asyncio.wait_for(
                func(**clean_args),
                timeout=self.tool_timeout,
            )
        except asyncio.TimeoutError:
            latency_ms = (time.monotonic() - start_ts) * 1000
            raise TimeoutException(tool_name=tool_name, timeout_seconds=self.tool_timeout)
        except Exception as e:
            latency_ms = (time.monotonic() - start_ts) * 1000
            raise ToolException(tool_name=tool_name, original_error=e)

        latency_ms = (time.monotonic() - start_ts) * 1000

        # 5. 构建成功 Observation
        obs = Observation.from_success(
            tool_call_id=call_id,
            tool_name=tool_name,
            content=str(result),
            latency_ms=latency_ms,
        )

        # 6. 发布 on_tool_end 事件
        if self.event_bus:
            self.event_bus.publish("on_tool_end", {
                "step": step,
                "tool_name": tool_name,
                "call_id": call_id,
                "observation": obs,
            })

        return obs

    async def _execute_single(
        self,
        call_id: str,
        tool_name: str,
        params: dict[str, Any],
        step: int = 0,
    ) -> Observation:
        """
        单工具执行包装器（异常隔离版）。

        就地捕获 dispatch 可能抛出的所有异常，将其转换为 status=error 的
        Observation 返回，而不向上传播，实现并行执行场景下的局部故障隔离。

        Args:
            call_id: 工具调用唯一 ID。
            tool_name: 工具函数名称。
            params: 工具调用的原始参数字典。
            step: 当前执行步数。

        Returns:
            无论执行成功或失败，均返回 Observation 对象（不抛出任何异常）。
        """
        start_ts = time.monotonic()
        try:
            return await self.dispatch(
                tool_name=tool_name,
                raw_params=params,
                call_id=call_id,
                step=step,
            )
        except Exception as e:
            latency_ms = (time.monotonic() - start_ts) * 1000
            return Observation.from_error(
                tool_call_id=call_id,
                tool_name=tool_name,
                error=e,
                latency_ms=latency_ms,
            )

    async def execute_parallel(
        self,
        tool_calls: list[dict[str, Any]],
        step: int = 0,
    ) -> list[Observation]:
        """
        并行非阻塞工具调度入口。

        将多个 tool_calls 转换为独立的 _execute_single 协程任务，
        通过 asyncio.gather 并发拉起，总执行时间取决于最慢的单个工具（T_max 机制）。
        单个工具失败不影响其他工具的正常执行（异常隔离）。

        Args:
            tool_calls: LLM 下发的并行工具调用列表，每项需包含：
                        {"id": str, "action": str, "params": dict}
            step: 当前执行步数。

        Returns:
            按原始输入顺序排列的 Observation 列表（与 tool_calls 一一对应）。
        """
        # 1. 为每个 tool_call 创建独立的异常隔离协程任务
        tasks = [
            self._execute_single(
                call_id=call["id"],
                tool_name=call["action"],
                params=call.get("params", {}),
                step=step,
            )
            for call in tool_calls
        ]

        # 2. asyncio.gather 并发执行：return_exceptions=True 确保单个协程崩溃不影响整体
        # 注意：由于 _execute_single 内部已捕获所有异常，此处 return_exceptions=True 是双重保险
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 3. 处理极端情况：如果 gather 返回了异常对象（理论上不应发生），转换为 error Observation
        final_observations: list[Observation] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                # 极端异常情况（_execute_single 内部的防护网被突破）
                call = tool_calls[i]
                final_observations.append(
                    Observation.from_error(
                        tool_call_id=call["id"],
                        tool_name=call["action"],
                        error=result,
                    )
                )
            else:
                final_observations.append(result)

        return final_observations
