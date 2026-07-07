"""
MiniAgent Framework v1.0 — StateReducer 状态归约器

设计方案：
1. 设计意图：
   Day29-34 的实现中，状态归约逻辑（将 Observation 追加到 messages、更新 usage 等）
   散落在 Runner 的 run() 方法中，导致 Runner 代码臃肿、职责不单一。
   
   独立的 StateReducer 将所有"如何更新 AgentState"的逻辑收拢为一组纯函数（静态方法），
   使 Runner 只需做：
     reducer.append_observation(state, obs)
   而不需要知道 Observation → messages 的具体转换规则。

   以后 Memory Compression / Context Window 管理 / Summary 摘要等功能，
   全部在 StateReducer 中实现，不影响 Runner 的主循环代码。

2. 类与函数结构（全部为静态方法，无需实例化）：
   - StateReducer.append_assistant_message(state, thought, action, params): 追加 assistant 消息
   - StateReducer.append_observation(state, obs): 追加单个 Observation
   - StateReducer.append_error_boundary(state, tool_name, error): 追加 Error-Boundary 自愈提示
   - StateReducer.merge_parallel_observations(state, observations): 批量归约并行 Observation 列表
   - StateReducer.update_usage(state, usage_delta, cost): 累加 Token 消费与费用
   - StateReducer.set_finish(state, reason, final_reply): 设置终止状态

3. 数据流流向：
   Runner 决策循环中：
   - LLM 输出解析后 → append_assistant_message
   - 单工具执行后 → append_observation
   - 工具报错时 → append_error_boundary（触发 Self-Correction）
   - 并行工具完成后 → merge_parallel_observations
   - LLM 响应含 usage 时 → update_usage
   - 检测到 Finish 或异常终止时 → set_finish
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..schema.message import (
    build_assistant_message,
    build_error_boundary_prompt,
    build_tool_message,
)

if TYPE_CHECKING:
    from .state import AgentState
    from ..schema.observation import Observation


class StateReducer:
    """
    Agent 状态归约器（State Reducer）。

    将所有"如何更新 AgentState"的逻辑收拢为一组静态方法（纯函数风格），
    使 Runner 主循环专注于流程编排，不承担具体的消息构建和状态更新逻辑。

    未来扩展方向：
    - 在 append_observation 中加入 Context Window 裁剪逻辑
    - 在 merge_parallel_observations 中加入 Memory 压缩摘要
    - 所有扩展均不影响 Runner 的调用接口
    """

    @staticmethod
    def append_assistant_message(
        state: "AgentState",
        thought: str,
        action: str,
        params: dict,
        tool_calls_raw: list | None = None,
    ) -> None:
        """
        将 LLM 本轮的推理决策作为 assistant 消息追加到状态消息流。

        Args:
            state: 当前 AgentState 实例（原地修改）。
            thought: LLM 输出的 Thought 推理文本。
            action: LLM 决定调用的工具名（或 "Finish"）。
            params: LLM 传递的工具参数字典。
            tool_calls_raw: 可选，原始 OpenAI tool_calls 结构（供消息格式化使用）。
        """
        msg = build_assistant_message(
            thought=thought,
            action=action,
            params=params,
            tool_calls_raw=tool_calls_raw,
        )
        state.messages.append(msg)

    @staticmethod
    def append_observation(
        state: "AgentState",
        observation: "Observation",
    ) -> None:
        """
        将单个 Observation 归约追加到状态消息流和 observation_history。

        同时记录工具调用历史（tool_history），保持状态的完整可追溯性。

        Args:
            state: 当前 AgentState 实例（原地修改）。
            observation: Dispatcher 返回的 Observation 对象。
        """
        # 1. 将 Observation 转换为 OpenAI tool 消息格式并追加到消息流
        tool_msg = build_tool_message(observation)
        state.messages.append(tool_msg)
        # 2. 追加到 observation 历史（独立存储，供 Logger 和 Memory 模块使用）
        state.observation_history.append(observation)

    @staticmethod
    def append_error_boundary(
        state: "AgentState",
        tool_name: str,
        error_message: str,
    ) -> None:
        """
        将工具执行失败的错误信息规整为 Error-Boundary 自愈反思引导文本，
        作为伪 tool 消息追加到状态消息流，触发 LLM 的 Self-Correction 机制。

        追加的消息格式：role=tool（伪工具消息），content 为格式化的错误反思引导。
        使用 tool role 是为了与 LLM 的历史 Context 保持一致（看起来像是工具返回了一个错误）。

        Args:
            state: 当前 AgentState 实例（原地修改）。
            tool_name: 调用失败的工具函数名称。
            error_message: 捕获的异常错误描述文本。
        """
        # 生成 Error-Boundary Prompt 文本
        error_prompt = build_error_boundary_prompt(
            tool_name=tool_name,
            error_message=error_message,
        )
        # 包装为 tool role 消息追加到消息流（LLM 会将其视为工具执行返回的错误反馈）
        state.messages.append({
            "role": "tool",
            "tool_call_id": f"error_{tool_name}_{state.step}",
            "name": tool_name,
            "content": error_prompt,
        })

    @staticmethod
    def merge_parallel_observations(
        state: "AgentState",
        observations: list["Observation"],
    ) -> None:
        """
        批量归约并行执行的多个 Observation 列表到状态消息流。

        保证 Observation 按原始 tool_calls 顺序追加（与 Dispatcher.execute_parallel
        返回的列表顺序一致），确保消息流与 LLM 的 tool_call_id 关联顺序匹配。

        Args:
            state: 当前 AgentState 实例（原地修改）。
            observations: Dispatcher.execute_parallel 返回的 Observation 列表。
        """
        for obs in observations:
            StateReducer.append_observation(state, obs)

    @staticmethod
    def update_usage(
        state: "AgentState",
        prompt_tokens: int,
        completion_tokens: int,
        cost: float = 0.0,
    ) -> None:
        """
        累加 LLM API 调用的 Token 消费统计和费用到 AgentState。

        每次 LLM API 调用返回后调用，持续累积整个任务的 Token 总消耗。

        Args:
            state: 当前 AgentState 实例（原地修改）。
            prompt_tokens: 本次 API 调用消耗的 Prompt Token 数。
            completion_tokens: 本次 API 调用生成的 Completion Token 数。
            cost: 本次调用的美元费用（可选，默认 0）。
        """
        state.add_usage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost=cost,
        )

    @staticmethod
    def set_finish(
        state: "AgentState",
        reason: str,
        final_reply: str | None = None,
    ) -> None:
        """
        设置 AgentState 的终止状态。

        Args:
            state: 当前 AgentState 实例（原地修改）。
            reason: 终止原因（"success" / "max_steps" / "stuck" / "retry_exceeded" / "fatal"）。
            final_reply: 可选，任务成功时 LLM 生成的最终回复文本。
        """
        state.finish_reason = reason
        if final_reply:
            state.metadata["final_reply"] = final_reply
