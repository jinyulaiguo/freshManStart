"""
MiniAgent Framework v1.0 — AgentState 增强版状态容器

设计方案：
1. 设计意图：
   从 Day31 的 AgentState 重构而来，大幅增强状态追踪能力。
   Day31 的 AgentState 只有 messages 和 steps 两个字段，无法支持：
   - Token 消费与费用追踪（usage / cost）
   - Observation 历史独立存储（observation_history）
   - 工具调用历史追踪（tool_history）
   - 任务终止原因记录（finish_reason）
   - 快照/回滚的自包含方法（snapshot / rollback）

2. 类与函数结构：
   - AgentState: 增强版状态容器
     - messages: 完整消息历史流（用于 LLM API 调用）
     - step: 当前循环步数
     - tool_history: 工具调用历史记录列表
     - observation_history: Observation 对象历史列表
     - snapshots: deepcopy 快照栈（供 rollback 使用）
     - retry_count: 当前累计重试次数
     - finish_reason: 终止原因字符串
     - usage: 累计 Token 消费字典
     - cost: 累计美元费用
     - metadata: 扩展元数据
     - snapshot(): 深拷贝自身并压入快照栈
     - rollback(): 弹出快照栈顶并恢复状态
     - to_summary(): 返回可序列化的状态摘要字典

3. 数据流流向：
   - Runner.run() 初始化 AgentState 并调用 reset()
   - 每轮循环开始前 state.snapshot() 备份
   - Reducer 的各 append_* 方法将消息/Observation 注入 state
   - 异常发生时 state.rollback() 恢复到上一个安全快照
   - 任务结束后 state.to_summary() 序列化输出日志
"""
from __future__ import annotations

import copy
from typing import Any

from ..schema.observation import Observation


class AgentState:
    """
    Agent 运行时状态容器（增强版）。

    存储 Agent 在整个生命周期中的所有运行时状态，支持深拷贝快照和回滚，
    是整个 Framework 的"数据脊梁"，所有微引擎模块均通过操作此对象来
    完成状态的读取与更新。

    Attributes:
        messages: 完整消息历史流，包含 user / assistant / tool 三种角色的消息字典列表。
        step: 当前主循环已执行的步数。
        tool_history: 工具调用记录列表，每项记录 {tool_name, params, step, call_id}。
        observation_history: Observation 对象列表，按时间先后顺序记录所有工具执行结果。
        snapshots: deepcopy 快照栈，用于 rollback 恢复到上一个安全状态。
        retry_count: 记录当前关联的 RetryManager 重试次数（由 Reducer 更新）。
        finish_reason: 任务终止原因（"success" / "max_steps" / "stuck" / "retry_exceeded" / "fatal"）。
        usage: 累计 Token 消费字典 {"prompt_tokens": int, "completion_tokens": int, "total_tokens": int}。
        cost: 累计 API 调用美元费用总额。
        metadata: 扩展元数据字典，预留用于未来 Multi-Agent 场景的跨 Agent 状态传递。
    """

    def __init__(
        self,
        initial_message: str,
        metadata: dict | None = None,
    ) -> None:
        """
        初始化 AgentState，以用户输入消息作为起点。

        Args:
            initial_message: 用户输入的原始问题/指令文本。
            metadata: 可选的初始扩展元数据字典（如 session_id、user_id 等）。
        """
        # 消息流：初始包含用户的第一条输入
        self.messages: list[dict[str, Any]] = [
            {"role": "user", "content": initial_message}
        ]
        # 执行步数计数器
        self.step: int = 0
        # 工具调用历史记录
        self.tool_history: list[dict[str, Any]] = []
        # Observation 对象历史
        self.observation_history: list[Observation] = []
        # 重试计数（镜像 RetryManager 的 retry_count，供 Logger 记录）
        self.retry_count: int = 0
        # 任务终止原因（None 表示任务仍在进行中）
        self.finish_reason: str | None = None
        # Token 消费统计（累加值）
        self.usage: dict[str, int] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
        # 累计费用（美元）
        self.cost: float = 0.0
        # 扩展元数据
        self.metadata: dict[str, Any] = metadata or {}
        # deepcopy 快照栈（存储每轮循环开始前的完整状态备份，作为框架内部状态，在此沉底定义）
        self.snapshots: list["AgentState"] = []

    def snapshot(self) -> None:
        """
        深拷贝当前状态并压入快照栈。

        每轮主循环迭代开始前调用，确保在本轮发生异常时可以回滚
        到本轮开始前的健康状态。

        实现细节：
        - 临时清空自身的 snapshots 栈，避免 deepcopy 时发生深层递归或快照无限放大。
        - 整体执行 copy.deepcopy(self)，以单次调用保证所有成员属性（包括未来新增字段）的深拷贝隔离。
        - 恢复原对象和快照对象的 snapshots 引用。
        """
        # 1. 临时存出当前快照栈引用，并就地重置为空列表
        temp_snapshots = self.snapshots
        self.snapshots = []

        # 2. 对当前状态对象执行一键 deepcopy（拷贝所有其它状态属性）
        snap = copy.deepcopy(self)

        # 3. 恢复原对象的快照栈引用
        self.snapshots = temp_snapshots

        # 4. 将新生成的健康快照对象压入原快照栈
        self.snapshots.append(snap)

    def rollback(self) -> bool:
        """
        从快照栈弹出最近一次健康快照，并恢复当前状态。

        在主循环捕获不可自愈的异常时调用，将状态恢复到异常发生前的最后一个
        安全检查点，防止污染状态传递给调用方。

        Returns:
            True 表示回滚成功，False 表示快照栈为空无法回滚。
        """
        if not self.snapshots:
            return False

        # 弹出快照栈顶（最近一次备份）
        snap = self.snapshots.pop()

        # 恢复所有核心状态字段（不恢复 snapshots 列表本身，保留剩余快照）
        self.messages = snap.messages
        self.step = snap.step
        self.tool_history = snap.tool_history
        self.observation_history = snap.observation_history
        self.retry_count = snap.retry_count
        self.finish_reason = snap.finish_reason
        self.usage = snap.usage
        self.cost = snap.cost
        self.metadata = snap.metadata
        return True

    def add_tool_call_record(
        self,
        tool_name: str,
        params: dict,
        call_id: str,
    ) -> None:
        """
        向工具调用历史中追加一条记录。

        Args:
            tool_name: 被调用的工具名称。
            params: LLM 传递的原始参数字典。
            call_id: 工具调用唯一 ID（tool_call_id）。
        """
        self.tool_history.append({
            "step": self.step,
            "call_id": call_id,
            "tool_name": tool_name,
            "params": params,
        })

    def add_usage(self, prompt_tokens: int, completion_tokens: int, cost: float = 0.0) -> None:
        """
        累加 Token 消费统计和费用。

        Args:
            prompt_tokens: 本次 LLM 调用消耗的 Prompt Token 数。
            completion_tokens: 本次 LLM 调用生成的 Completion Token 数。
            cost: 本次调用的美元费用（可选，默认 0）。
        """
        self.usage["prompt_tokens"] += prompt_tokens
        self.usage["completion_tokens"] += completion_tokens
        self.usage["total_tokens"] += (prompt_tokens + completion_tokens)
        self.cost += cost

    def to_summary(self) -> dict[str, Any]:
        """
        返回可序列化的状态摘要字典（用于最终日志输出）。

        返回的字典只包含核心摘要信息，不含完整消息历史（消息历史可能很长）。

        Returns:
            包含步数、工具调用数、Token 统计、费用和终止原因的摘要字典。
        """
        return {
            "total_steps": self.step,
            "total_tool_calls": len(self.tool_history),
            "total_observations": len(self.observation_history),
            "retry_count": self.retry_count,
            "finish_reason": self.finish_reason,
            "usage": self.usage,
            "total_cost_usd": round(self.cost, 6),
            "metadata": self.metadata,
        }
