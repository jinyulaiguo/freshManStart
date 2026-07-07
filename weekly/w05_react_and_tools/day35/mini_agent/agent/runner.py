"""
MiniAgent Framework v1.0 — ReActAgentRunner 主控制循环

设计方案：
1. 设计意图：
   Runner 是整个 Framework 的"拼装积木墙"，只负责流程编排和生命周期管理，
   不承担任何具体算法实现。对比 Day31-34 的单文件引擎：

   Day34 的 MiniReActEngine.run() 方法承担了：工具调度、状态归约、
   Error-Boundary 构建、JSON 解析、消息格式化 — 这违反了单一职责原则。

   Day35 的 ReActAgentRunner.run() 只承担：
   - while 主循环控制
   - 调用各微引擎（Dispatcher / Reducer / StuckDetector / RetryManager）
   - 在关键节点发布 EventBus 事件
   - 异常路由（可自愈 → Self-Correction，不可自愈 → 回滚终止）
   - 返回最终 AgentState

2. 类与函数结构：
   - ReActAgentRunner
     - __init__(registry, max_steps, max_retries, stuck_window, event_bus): 初始化
     - run(user_message): 公开入口，返回 AgentState
     - _call_llm(state): 构建 API 消息 → 调用 LLM → 更新 usage → 返回 LLMResponse
     - _should_finish(parsed): 判断是否命中 Finish 终止协议
     - _rollback(state, reason): 执行状态回滚并设置 finish_reason

3. 完整控制流：
   run(user_message)
     │
     ├── 初始化 AgentState / StuckDetector / RetryManager
     │
     └── while state.step < max_steps:
           │
           ├── state.snapshot()                     # 每轮开始前备份
           ├── state.step += 1
           ├── event_bus.publish(on_step_start)
           │
           ├── _call_llm(state)                     # 调用 LLM
           │   └── format_messages_for_api()
           │   └── AgentLLMClient.chat()
           │   └── StateReducer.update_usage()
           │   └── parse_json() → thought/action/params
           │
           ├── StateReducer.append_assistant_message()
           │
           ├── if _should_finish(parsed):            # 命中 Finish 终止
           │   └── StateReducer.set_finish("success")
           │   └── event_bus.publish(on_finish)
           │   └── return state
           │
           ├── for each tool_call: StuckDetector.check_and_push()  # 死循环检测
           │
           ├── Dispatcher.execute_parallel(tool_calls)  # 并发执行工具
           │
           ├── for each obs in observations:
           │   ├── if obs.is_success():
           │   │   └── StateReducer.append_observation()
           │   │   └── RetryManager.reset()
           │   │
           │   └── else (obs.is_error()):            # 工具失败 → Self-Correction
           │       ├── RetryManager.can_retry() ?
           │       │   ├── True:  record_retry() + append_error_boundary()
           │       │   └── False: raise RetryExceededException
           │       └── event_bus.publish(on_retry)
           │
           └── event_bus.publish(on_step_end)
     │
     └── 超出 max_steps → StepOverflowException → _rollback → return state
"""
from __future__ import annotations

import time
from typing import Any

from .dispatcher import ToolDispatcher
from .event_bus import (
    EVENT_ERROR,
    EVENT_FINISH,
    EVENT_LLM_END,
    EVENT_LLM_START,
    EVENT_RETRY,
    EVENT_STEP_END,
    EVENT_STEP_START,
    EVENT_STUCK,
    EventBus,
)
from .reducer import StateReducer
from .registry import ToolRegistry
from .retry import RetryManager
from .state import AgentState
from .stuck import StuckDetector
from ..llm.openai_client import AgentLLMClient
from ..schema.exception import (
    FatalException,
    RetryExceededException,
    StepOverflowException,
    StuckException,
)
from ..schema.message import build_system_prompt, format_messages_for_api


class ReActAgentRunner:
    """
    ReAct Agent 主控制循环（积木拼装思想）。

    Runner 只做流程编排，所有具体能力委托给独立的微引擎：
    - 工具调度 → ToolDispatcher
    - 状态归约 → StateReducer
    - 死循环检测 → StuckDetector
    - 重试管理 → RetryManager
    - 日志记录 → EventBus → JSONStepLogger

    以后新增 Workflow、Multi-Agent 等功能，只需替换或扩展对应的微引擎，
    Runner 的主循环代码无需改动。
    """

    def __init__(
        self,
        registry: ToolRegistry,
        max_steps: int = 8,
        max_retries: int = 3,
        stuck_window: int = 3,
        tool_timeout: float = 30.0,
        event_bus: EventBus | None = None,
    ) -> None:
        """
        初始化 ReActAgentRunner，注入所有依赖的微引擎实例。

        Args:
            registry: 工具注册中心（已完成工具注册）。
            max_steps: 主循环最大允许步数，超出抛出 StepOverflowException，默认 8。
            max_retries: 连续失败最大允许自愈重试次数，超出抛出 RetryExceededException，默认 3。
            stuck_window: 死循环检测滑动窗口大小（连续 N 次相同调用判定为死循环），默认 3。
            tool_timeout: 单个工具执行最大超时时间（秒），默认 30.0。
            event_bus: 可选的事件总线，若 None 则创建一个空的（Logger 可在外部订阅）。
        """
        self.registry = registry
        self.max_steps = max_steps
        self.max_retries = max_retries
        self.stuck_window = stuck_window

        # 初始化各微引擎实例
        self.event_bus: EventBus = event_bus or EventBus()
        self.llm_client = AgentLLMClient()
        self.dispatcher = ToolDispatcher(
            registry=registry,
            event_bus=self.event_bus,
            tool_timeout=tool_timeout,
        )

    async def run(self, user_message: str) -> AgentState:
        """
        执行 ReAct Agent 主控制循环，驱动整个 Agent 生命周期。

        这是唯一的公开入口方法。

        Args:
            user_message: 用户输入的原始问题/指令文本。

        Returns:
            最终的 AgentState（无论成功、超出步数还是其他异常终止）。
            调用方可通过 state.finish_reason 判断终止原因，
            通过 state.metadata["final_reply"] 获取最终答复。

        Raises:
            FatalException: 不可恢复的系统级错误（LLM API 连接失败等）。
        """
        # ── 1. 初始化 AgentState 和本轮任务专用的微引擎实例 ──
        state = AgentState(initial_message=user_message)
        stuck_detector = StuckDetector(window_size=self.stuck_window)
        retry_manager = RetryManager(max_retries=self.max_retries)

        # ── 2. 构建 System Prompt（动态包含所有已注册工具的 Schema 描述）──
        system_prompt = build_system_prompt(self.registry.get_all_schemas())

        print(f"\n{'='*60}")
        print(f"🚀 MiniAgent Framework v1.0 启动")
        print(f"   用户输入: {user_message[:80]}")
        print(f"   已注册工具: {self.registry.list_tools()}")
        print(f"   配置: max_steps={self.max_steps}, max_retries={self.max_retries}")
        print(f"{'='*60}")

        try:
            # ── 3. 主控制循环 ──
            while state.step < self.max_steps:

                # 3.1 每轮开始前深拷贝备份（确保可回滚）
                state.snapshot()

                # 3.2 步数递增
                state.step += 1
                current_step = state.step

                # 3.3 发布 on_step_start 事件
                self.event_bus.publish(EVENT_STEP_START, {
                    "step": current_step,
                    "messages_count": len(state.messages),
                })
                print(f"\n── Step {current_step} ──────────────────────────────────")

                # 3.4 调用 LLM 获取决策
                try:
                    llm_response = await self._call_llm(state, system_prompt, current_step)
                except Exception as e:
                    # LLM API 调用失败 → 致命错误，不可自愈
                    raise FatalException(reason="LLM API 调用失败", original_error=e)

                # 3.5 解析 LLM 输出的 JSON（thought / action / params）
                try:
                    parsed = llm_response.parse_json()
                except ValueError as e:
                    # JSON 格式错误 → 注入格式纠正提示，触发下一轮重试
                    print(f"   🚨 LLM 输出格式错误，注入纠正提示...")
                    StateReducer.append_error_boundary(
                        state,
                        tool_name="json_parser",
                        error_message=f"输出格式不合规：必须输出单个 JSON 对象。原始输出：{llm_response.content[:200]}",
                    )
                    continue

                thought = parsed.get("thought", "")
                action = parsed.get("action", "")
                params = parsed.get("params", {})
                tool_calls = parsed.get("tool_calls", [])  # 支持多工具并行调用格式

                print(f"   [Thought]: {thought}")
                print(f"   [Action] : {action}")
                if params:
                    print(f"   [Params] : {params}")

                # 3.6 将 LLM 决策追加到消息流
                StateReducer.append_assistant_message(state, thought, action, params)

                # 3.7 更新 usage
                StateReducer.update_usage(
                    state,
                    prompt_tokens=llm_response.prompt_tokens,
                    completion_tokens=llm_response.completion_tokens,
                    cost=llm_response.cost,
                )

                # 3.8 发布 on_llm_end 事件
                self.event_bus.publish(EVENT_LLM_END, {
                    "step": current_step,
                    "thought": thought,
                    "action": action,
                    "prompt_tokens": llm_response.prompt_tokens,
                    "completion_tokens": llm_response.completion_tokens,
                    "cost": llm_response.cost,
                    "latency_ms": llm_response.latency_ms,
                })

                # 3.9 判断是否命中 Finish 终止协议
                if self._should_finish(parsed):
                    final_reply = params.get("result", "任务已完成。")
                    print(f"\n   ✅ 命中终止协议，任务完成。")
                    print(f"   [Final Reply]: {final_reply}")
                    StateReducer.set_finish(state, reason="success", final_reply=final_reply)
                    self.event_bus.publish(EVENT_FINISH, {
                        "finish_reason": "success",
                        "final_reply": final_reply,
                        "summary": state.to_summary(),
                    })
                    return state

                # 3.10 规整 tool_calls（支持两种格式：单工具 action+params / 多工具 tool_calls 列表）
                if not tool_calls:
                    if action and action != "Finish":
                        # 单工具调用格式（Day34 兼容格式）
                        tool_calls = [{"id": f"call_{current_step}_0", "action": action, "params": params}]
                    else:
                        # 既没有 tool_calls 列表，也没有单工具调用且不是 Finish → 注入提示引导模型重新决策
                        print(f"   ⚠️  LLM 未给出有效的工具调用，注入引导提示...")
                        StateReducer.append_error_boundary(
                            state,
                            tool_name="routing",
                            error_message="你必须调用一个工具，或者在得到答案后输出 action='Finish'。",
                        )
                        continue

                # 3.11 死循环检测（对每个 tool_call 独立检测）
                try:
                    for tc in tool_calls:
                        stuck_detector.check_and_push(tc["action"], tc.get("params", {}))
                except StuckException as e:
                    print(f"\n   🚨 死循环拦截！{e.message}")
                    self.event_bus.publish(EVENT_STUCK, {
                        "step": current_step,
                        "action": e.action,
                        "hash": e.action_hash,
                        "window_size": e.window_size,
                    })
                    StateReducer.set_finish(state, reason="stuck")
                    self._rollback(state)
                    return state

                # 3.12 记录工具调用历史
                for tc in tool_calls:
                    state.add_tool_call_record(
                        tool_name=tc["action"],
                        params=tc.get("params", {}),
                        call_id=tc["id"],
                    )

                # 3.13 并发执行所有工具
                print(f"   [System] : 并发调度 {len(tool_calls)} 个工具...")
                observations = await self.dispatcher.execute_parallel(tool_calls, step=current_step)

                # 3.14 处理 Observation（成功归约，失败触发 Self-Correction）
                for obs in observations:
                    if obs.is_success():
                        # 工具执行成功：归约 Observation，重置重试计数器
                        StateReducer.append_observation(state, obs)
                        retry_manager.reset()
                        print(f"   [✅ Observation ({obs.tool_name})]: {obs.content[:120]}")
                    else:
                        # 工具执行失败：触发 Self-Correction 反思环
                        print(f"   [❌ Observation ({obs.tool_name})]: {obs.content[:120]}")
                        self.event_bus.publish(EVENT_RETRY, {
                            "step": current_step,
                            "tool_name": obs.tool_name,
                            "error": obs.content,
                            "retry_count": retry_manager.retry_count + 1,
                        })

                        if not retry_manager.can_retry():
                            # 重试预算耗尽 → 安全终止
                            raise RetryExceededException(
                                max_retries=self.max_retries,
                                retry_count=retry_manager.retry_count + 1,
                            )

                        retry_manager.record_retry()
                        state.retry_count = retry_manager.retry_count
                        # 注入 Error-Boundary Prompt，触发 LLM 下一轮反思纠错
                        StateReducer.append_error_boundary(
                            state,
                            tool_name=obs.tool_name,
                            error_message=obs.content,
                        )
                        await retry_manager.wait_backoff()

                # 3.15 发布 on_step_end 事件
                self.event_bus.publish(EVENT_STEP_END, {
                    "step": current_step,
                    "summary": state.to_summary(),
                })

            # ── 4. 超出 max_steps → 强拦截 ──
            raise StepOverflowException(max_steps=self.max_steps, current_step=state.step)

        except StepOverflowException as e:
            print(f"\n   🚨 步数溢出强拦截: {e.message}")
            self.event_bus.publish(EVENT_ERROR, {
                "step": state.step,
                "error_type": "StepOverflowException",
                "error_message": e.message,
            })
            StateReducer.set_finish(state, reason="max_steps")
            self._rollback(state)
            return state

        except RetryExceededException as e:
            print(f"\n   🚨 重试预算耗尽: {e.message}")
            self.event_bus.publish(EVENT_ERROR, {
                "step": state.step,
                "error_type": "RetryExceededException",
                "error_message": e.message,
            })
            StateReducer.set_finish(state, reason="retry_exceeded")
            self._rollback(state)
            return state

        except FatalException as e:
            print(f"\n   💀 致命错误（不可恢复）: {e.message}")
            self.event_bus.publish(EVENT_ERROR, {
                "step": state.step,
                "error_type": "FatalException",
                "error_message": e.message,
            })
            StateReducer.set_finish(state, reason="fatal")
            # FatalException 向上传播，不在 Runner 内吞掉
            raise

    async def _call_llm(
        self,
        state: AgentState,
        system_prompt: str,
        step: int,
    ):
        """
        构建 API 格式消息并调用 LLM，返回结构化 LLMResponse。

        Args:
            state: 当前 AgentState（读取 messages 构建 API 格式）。
            system_prompt: 已构建好的 System Prompt 字符串。
            step: 当前步数（用于事件 payload）。

        Returns:
            LLMResponse 对象（含 content / usage / cost / latency_ms）。
        """
        # 发布 on_llm_start 事件
        self.event_bus.publish(EVENT_LLM_START, {
            "step": step,
            "messages_count": len(state.messages),
        })

        # 将内部格式消息流规整为 OpenAI API 兼容格式
        api_messages = format_messages_for_api(
            state_messages=state.messages,
            system_prompt=system_prompt,
        )

        # 调用 LLM（通过 AgentLLMClient 封装，含计时/usage/cost）
        return await self.llm_client.chat(messages=api_messages)

    def _should_finish(self, parsed_output: dict) -> bool:
        """
        判断 LLM 决策是否命中 Finish 终止协议。

        Args:
            parsed_output: 从 LLM 输出 JSON 中解析出的字典。

        Returns:
            True 表示 Agent 已获得最终答案，应终止主循环。
        """
        return parsed_output.get("action", "").strip().lower() == "finish"

    def _rollback(self, state: AgentState) -> None:
        """
        执行 AgentState 快照回滚（恢复到本次异常步骤开始前的状态）。

        Args:
            state: 要执行回滚的 AgentState 实例（原地修改）。
        """
        success = state.rollback()
        if success:
            print(f"   🔄 状态已回滚至步骤 {state.step} 开始前的安全快照。")
        else:
            print(f"   ⚠️  快照栈为空，无法执行回滚（任务刚启动即失败）。")
