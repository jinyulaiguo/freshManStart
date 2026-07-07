"""
MiniAgent Framework v1.0 — RetryManager 重试预算管理器

设计方案：
1. 设计意图：
   Day29-34 的实现中没有独立的重试管理器，工具报错后是否继续反思完全依赖
   max_steps 的步数约束，无法精确控制"允许失败并自愈几次"这个维度。
   
   独立的 RetryManager 解决的工程痛点：
   - 区分"步数用尽"和"重试用尽"两种不同的终止原因
   - 为每次工具报错提供可配置的指数退避延迟（防止频繁失败轰炸 LLM）
   - 工具成功后 reset()，使重试预算只计算"连续失败"次数而非累计失败次数
   - 独立可测试，不与 Runner 主循环逻辑耦合

2. 类与函数结构：
   - RetryManager: 重试预算管理器
     - __init__(max_retries, backoff_base): 初始化最大重试次数和退避基数
     - can_retry(): 检查是否还有重试预算
     - record_retry(): 消费一次重试预算
     - reset(): 重置计数器（工具成功时调用）
     - retry_count: 属性，当前累计重试次数
     - backoff_delay: 属性，当前应等待的退避延迟时间（秒）

3. 数据流流向：
   - Runner 捕获 ToolException / ValidationException 时：
     1. 检查 can_retry() → False 则抛出 RetryExceededException
     2. record_retry() 消费预算
     3. await asyncio.sleep(backoff_delay) 等待退避
     4. 调用 StateReducer.append_error_boundary() 注入自愈反思 Prompt
   - 工具执行成功时：reset() 重置连续失败计数器
"""
from __future__ import annotations

import asyncio

from ..schema.exception import RetryExceededException


class RetryManager:
    """
    工具调用重试预算管理器。

    管理 Agent 在工具执行失败时的自愈重试能力，提供精确的重试次数控制
    和指数退避延迟策略，防止大模型在工具持续报错时无限循环尝试。

    重试策略：
        - 每次工具报错消耗一次重试预算
        - 预算耗尽时抛出 RetryExceededException，触发任务安全终止
        - 工具执行成功时重置计数器（只计连续失败，不计累计失败）
        - 指数退避：第 N 次重试前等待 backoff_base * (2 ** (N-1)) 秒

    配合关系：
        - Runner 在 ToolException / ValidationException 分支调用此类
        - StepOverflowException 与 RetryExceededException 相互独立（不同维度）
        - max_steps 控制"总决策轮数"，max_retries 控制"连续失败允许自愈几次"
    """

    def __init__(self, max_retries: int = 3, backoff_base: float = 0.5) -> None:
        """
        初始化重试预算管理器。

        Args:
            max_retries: 最大连续失败重试次数（达到后抛出 RetryExceededException），
                         默认为 3。设置为 0 表示不允许任何重试。
            backoff_base: 指数退避的基础延迟时间（秒），默认为 0.5 秒。
                         第 1 次重试等待 0.5s，第 2 次等待 1.0s，第 3 次等待 2.0s。
        """
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        # 内部连续重试计数器（工具成功时 reset()）
        self._retry_count: int = 0

    @property
    def retry_count(self) -> int:
        """
        当前累计连续重试次数（只读属性）。

        Returns:
            当前已消耗的重试次数。
        """
        return self._retry_count

    @property
    def backoff_delay(self) -> float:
        """
        根据当前重试次数计算本次应等待的退避延迟时间（指数退避策略）。

        退避公式：backoff_base * (2 ** (_retry_count - 1))

        Returns:
            本次重试前应等待的秒数。第 0 次重试（第 1 次失败时）等待 backoff_base 秒。
        """
        if self._retry_count <= 0:
            return 0.0
        return self.backoff_base * (2 ** (self._retry_count - 1))

    def can_retry(self) -> bool:
        """
        检查当前是否还有剩余的重试预算。

        Runner 在捕获工具异常后，应先调用此方法判断是否允许自愈，
        若返回 False，则抛出 RetryExceededException 终止任务。

        Returns:
            True 表示仍有预算可继续重试，False 表示预算耗尽。
        """
        return self._retry_count < self.max_retries

    def record_retry(self) -> None:
        """
        消耗一次重试预算，并检查是否超出上限。

        在确认 can_retry() 为 True 后调用，消耗一次预算并递增计数器。
        若消耗后已超出限制，抛出 RetryExceededException。

        Raises:
            RetryExceededException: 消耗本次预算后已超出 max_retries 时抛出。
        """
        self._retry_count += 1
        if self._retry_count > self.max_retries:
            raise RetryExceededException(
                max_retries=self.max_retries,
                retry_count=self._retry_count,
            )

    def reset(self) -> None:
        """
        重置重试计数器（工具执行成功时调用）。

        连续失败计数器只在工具执行成功时归零，下一次失败将从 0 重新开始计数。
        这意味着 max_retries 限制的是"连续"失败次数，而非整个任务的累计失败次数。
        """
        self._retry_count = 0

    async def wait_backoff(self) -> None:
        """
        异步等待当前退避延迟时间（非阻塞）。

        在 record_retry() 之后调用，等待指数退避延迟后再继续主循环。
        使用 asyncio.sleep 确保不阻塞事件循环中其他协程的运行。

        如果 backoff_delay == 0（首次或已 reset），直接返回不等待。
        """
        delay = self.backoff_delay
        if delay > 0:
            await asyncio.sleep(delay)
