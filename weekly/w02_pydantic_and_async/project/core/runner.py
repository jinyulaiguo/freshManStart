"""
设计方案：
- 设计意图：构建系统的主控制中枢和调度引擎 `AsyncToolRunner`。它接收外部 JSON 请求，协调 Pydantic 数据验证网关，提供支持指数退避的重试机制，整合生命周期回调可观测系统，并应用纯函数 Reducer 模式归约更新内部状态契约。
- 类与函数结构：
  - `AsyncToolRunner` 类：
    - `__init__(settings, registry, callback)`: 依赖注入初始化，构建初始 `RunnerState`。
    - `run_tool(tool_name, raw_json)`: 单工具调度核心流。
    - `run_batch(requests)`: 批量任务异步非阻塞并发执行（`asyncio.gather`）。
    - `__call__` 与 `__repr__`: 魔法方法，增强易用性与调试可视化。
- 关键数据流向：
  - JSON 参数 + 工具名 -> `run_tool()` -> Pydantic 校验反序列化 -> 注入动态 `@retry` 装饰器 -> 异步/并发执行核心工具 -> 触发 `on_tool_success` / `on_tool_error` 旁路回调 -> 通过 Reducer 归约更新 `self._state` -> 最终输出结果或抛出因果链异常。
"""

import asyncio
import time
import uuid
from typing import Any, Dict, List, Optional
from weekly.w02_pydantic_and_async.project.config.settings import AppSettings
from weekly.w02_pydantic_and_async.project.core.registry import ToolRegistry
from weekly.w02_pydantic_and_async.project.core.retry import retry
from weekly.w02_pydantic_and_async.project.exceptions.base import (
    BaseProjectError,
    ToolValidationError,
    ToolExecutionError,
    APIConnectionError,
)
from weekly.w02_pydantic_and_async.project.models.state import (
    RunnerState,
    merge_messages,
    merge_tool_results,
)
from weekly.w02_pydantic_and_async.project.callbacks.base import ToolCallbackProtocol

class AsyncToolRunner:
    """批量与单工具异步调度引擎"""
    def __init__(
        self,
        settings: AppSettings,
        registry: ToolRegistry,
        callback: Optional[ToolCallbackProtocol] = None
    ):
        self._settings = settings
        self._registry = registry
        self._callback = callback
        
        from weekly.w02_pydantic_and_async.project.log.factory import create_logger
        self._logger = create_logger("core.runner", settings)

        # 基于 Day 8 TypedDict 约束初始化全局状态
        self._state: RunnerState = {
            "current_tool": "none",
            "total_steps": 0,
            "success_count": 0,
            "error_count": 0,
            "messages": ["调度引擎初始化成功。"],
            "tool_results": {}
        }

    @property
    def state(self) -> RunnerState:
        """获取当前引擎的状态副本"""
        return self._state.copy()

    async def run_tool(self, tool_name: str, raw_json: str) -> str:
        """
        单工具执行主逻辑。
        包含了参数拦截强校验、动态重试防网络抖动、异常因果链传递以及生命周期事件回调。
        """
        trace_id = str(uuid.uuid4())
        from weekly.w02_pydantic_and_async.project.exceptions.base import current_trace_id
        token = current_trace_id.set(trace_id)
        try:
            return await self._run_tool_inner(tool_name, raw_json, trace_id)
        finally:
            current_trace_id.reset(token)

    async def _run_tool_inner(self, tool_name: str, raw_json: str, trace_id: str) -> str:
        start_time = time.perf_counter()
        
        # 1. 更新局部基础状态，使用局部变量 local_step 锁定当前调用的专属步骤序号（解决并发状态竞争）
        self._state["total_steps"] += 1
        local_step = self._state["total_steps"]
        self._state["current_tool"] = tool_name

        # 2. 触发开始回调（防御性调用，确保回调崩溃不影响核心引擎）
        if self._callback:
            try:
                self._callback.on_tool_start(trace_id, tool_name, raw_json)
            except Exception as cb_err:
                self._logger.error(f"[Callback Error] on_tool_start 触发失败: {cb_err}")

        # 3. 提取工具实例
        try:
            tool = self._registry.get(tool_name)
        except BaseProjectError as e:
            # 补齐 trace_id 并抛出
            e.trace_id = trace_id
            duration = time.perf_counter() - start_time
            self._state["error_count"] += 1
            self._state["messages"] = merge_messages(
                self._state["messages"],
                [f"[Step {local_step}] 未注册工具 '{tool_name}' 运行失败."]
            )
            if self._callback:
                try:
                    self._callback.on_tool_error(trace_id, tool_name, e, duration)
                except Exception as cb_err:
                    self._logger.error(f"[Callback Error] on_tool_error 触发失败: {cb_err}")
            raise e

        # 4. Pydantic 参数反序列化拦截校验（静态/模型级校验）
        try:
            validated_args = tool.args_model.model_validate_json(raw_json)
        except Exception as e:
            duration = time.perf_counter() - start_time
            val_error = ToolValidationError(
                message=f"工具 '{tool_name}' 入参校验失败: {str(e)}",
                trace_id=trace_id
            )
            val_error.__cause__ = e
            
            # 更新状态
            self._state["error_count"] += 1
            self._state["messages"] = merge_messages(
                self._state["messages"],
                [f"[Step {local_step}] 工具 '{tool_name}' 参数强校验拦截失败."]
            )
            
            if self._callback:
                try:
                    self._callback.on_tool_error(trace_id, tool_name, val_error, duration)
                except Exception as cb_err:
                    self._logger.error(f"[Callback Error] on_tool_error 触发失败: {cb_err}")
            raise val_error from e

        # 5. 执行核心计算（对于 API 网络调用，动态包装 retry 指数退避重试装饰器）
        try:
            @retry(
                times=self._settings.max_retries,
                base_delay=self._settings.retry_base_delay,
                exceptions=(APIConnectionError,),
                logger=self._logger
            )
            async def run_with_retry_policy() -> str:
                return await tool._execute(validated_args)

            result = await run_with_retry_policy()
            duration = time.perf_counter() - start_time

            # 更新成功状态，利用 Reducer 进行状态更新
            self._state["success_count"] += 1
            self._state["messages"] = merge_messages(
                self._state["messages"],
                [f"[Step {local_step}] 工具 '{tool_name}' 执行成功."]
            )
            self._state["tool_results"] = merge_tool_results(
                self._state["tool_results"],
                {f"{tool_name}_step_{local_step}": result}
            )

            # 触发成功回调
            if self._callback:
                try:
                    self._callback.on_tool_success(trace_id, tool_name, result, duration)
                except Exception as cb_err:
                    self._logger.error(f"[Callback Error] on_tool_success 触发失败: {cb_err}")
            
            return result

        except Exception as original_err:
            duration = time.perf_counter() - start_time
            self._state["error_count"] += 1
            self._state["messages"] = merge_messages(
                self._state["messages"],
                [f"[Step {local_step}] 工具 '{tool_name}' 执行崩溃: {str(original_err)}"]
            )

            # 包装异常，建立因果链 raise ... from
            if isinstance(original_err, BaseProjectError):
                wrapped_err = original_err
                wrapped_err.trace_id = trace_id
            elif isinstance(original_err, ZeroDivisionError):
                wrapped_err = ToolExecutionError(
                    message=f"工具计算逻辑崩溃: {str(original_err)}",
                    trace_id=trace_id,
                    user_message="计算参数错误：发生除以零异常"
                )
                wrapped_err.__cause__ = original_err
            else:
                wrapped_err = ToolExecutionError(
                    message=f"工具运行未知内部错误: {str(original_err)}",
                    trace_id=trace_id
                )
                wrapped_err.__cause__ = original_err

            # 触发异常回调
            if self._callback:
                try:
                    self._callback.on_tool_error(trace_id, tool_name, wrapped_err, duration)
                except Exception as cb_err:
                    self._logger.error(f"[Callback Error] on_tool_error 触发失败: {cb_err}")
            
            raise wrapped_err from original_err

    async def run_batch(self, requests: List[Dict[str, str]]) -> List[Any]:
        """
        基于 Day 11 asyncio.gather 的并发批量执行引擎。
        使用 return_exceptions=True 阻断异常扩散，保证批量任务执行的独立性与隔离性。
        """
        self._logger.info(f"开始批量异步并发派发 {len(requests)} 个工具请求...")
        
        # 限制并发总数，虽然 gather 是并行的，但如果 settings 配置了 max_concurrent_tools，可以采用 asyncio.Semaphore 控制
        sem = asyncio.Semaphore(self._settings.max_concurrent_tools)

        async def sem_run(req: Dict[str, str]) -> Any:
            async with sem:
                name = req.get("name", "")
                args = req.get("args", "{}")
                try:
                    return await self.run_tool(name, args)
                except Exception as e:
                    # 返回异常实例，供调用方统计与排查
                    return e

        tasks = [sem_run(req) for req in requests]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        return list(results)

    async def __call__(self, tool_name: str, raw_json: str) -> str:
        """Day 4 __call__ 魔法方法，简化调用流"""
        return await self.run_tool(tool_name, raw_json)

    def __repr__(self) -> str:
        """Day 4 __repr__ 魔法方法"""
        return (
            f"<AsyncToolRunner total_steps={self._state['total_steps']} "
            f"success={self._state['success_count']} error={self._state['error_count']}>"
        )
