"""
MiniAgent Framework v1.0 — 统一异常层级体系

设计方案：
1. 设计意图：
   构建一套统一的、可区分优先级的 Agent 异常层级树，使 Runner 主控制环能够
   根据异常类型做差异化处理（可自愈、可回滚、不可恢复），而非用宽泛的 Exception
   捕获所有错误导致信息丢失。

2. 异常层级树：
   AgentException（基类）
   ├── ToolException          — 工具函数内部运行时报错（可自愈，触发 Self-Correction）
   ├── ValidationException    — Pydantic 参数契约校验失败（可自愈，触发 Error-Boundary）
   ├── RetryExceededException — 重试预算耗尽（不可继续自愈，安全终止）
   ├── StuckException         — 死循环哈希拦截触发（不可恢复，强制终止）
   ├── StepOverflowException  — 步数溢出强拦截（非错误，正常超出预算的终止）
   ├── TimeoutException       — 工具执行超时（可自愈，触发降级处理）
   └── FatalException         — 不可恢复的致命错误（立即向上传播，终止整个 Runner）

3. 数据流流向：
   - 各微引擎模块（Dispatcher、RetryManager、StuckDetector 等）只抛出对应子类
   - Runner 的 try-except 链只需对齐子类类型，无需解析 message 字符串
   - FatalException 不会被 Runner 捕获，直接向上传播给调用方
"""


class AgentException(Exception):
    """
    MiniAgent Framework 异常基类。

    所有 Framework 内部异常均继承自此类，方便调用方通过一个 except
    捕获所有 Framework 级别的异常，同时保留子类区分能力。

    Attributes:
        message: 人类可读的错误描述。
        context: 附加上下文信息字典（用于日志与 Debug）。
    """

    def __init__(self, message: str, context: dict | None = None) -> None:
        """
        初始化 AgentException。

        Args:
            message: 人类可读的错误描述文字。
            context: 可选的附加上下文信息字典（如步骤数、工具名等）。
        """
        super().__init__(message)
        self.message = message
        self.context: dict = context or {}

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(message={self.message!r}, context={self.context})"


class ToolException(AgentException):
    """
    工具函数内部运行时报错。

    触发时机：工具函数（weather / calculator / search 等）在 await 执行期间
    抛出未被工具自身捕获的异常（如网络超时、业务逻辑断言失败等）。

    处理策略：Runner 捕获后触发 Self-Correction，将错误信息规整为
    Error-Boundary Prompt 喂回大模型，允许模型在下一轮反思并修正参数。

    Args:
        tool_name: 触发异常的工具函数名称。
        original_error: 原始底层异常对象。
    """

    def __init__(self, tool_name: str, original_error: Exception) -> None:
        message = f"工具 '{tool_name}' 执行失败: {original_error}"
        super().__init__(message, context={"tool_name": tool_name})
        self.tool_name = tool_name
        self.original_error = original_error


class ValidationException(AgentException):
    """
    Pydantic 参数契约校验失败。

    触发时机：Dispatcher 在执行工具前，利用 ToolRegistry 中动态构建的
    Pydantic 模型对 LLM 输出的原始参数进行校验时校验不通过（如类型不匹配、
    必填字段缺失等）。

    处理策略：与 ToolException 相同，触发 Self-Correction 反思环。

    Args:
        tool_name: 参数校验失败的目标工具名称。
        validation_error: Pydantic 校验抛出的原始错误字符串。
    """

    def __init__(self, tool_name: str, validation_error: str) -> None:
        message = f"工具 '{tool_name}' 参数契约校验拦截失败: {validation_error}"
        super().__init__(message, context={"tool_name": tool_name})
        self.tool_name = tool_name
        self.validation_error = validation_error


class RetryExceededException(AgentException):
    """
    重试预算耗尽，无法继续自愈。

    触发时机：RetryManager 检测到当前累计重试次数已达到 max_retries 上限，
    但工具调用仍然持续失败，无法自愈。

    处理策略：Runner 捕获后不再触发 Self-Correction，将 finish_reason
    设置为 "retry_exceeded" 并安全终止，返回当前已归约的 AgentState。

    Args:
        max_retries: 允许的最大重试次数。
        retry_count: 实际消耗的重试次数。
    """

    def __init__(self, max_retries: int, retry_count: int) -> None:
        message = f"重试预算耗尽：已累计重试 {retry_count} 次，超出最大限制 {max_retries} 次"
        super().__init__(message, context={"max_retries": max_retries, "retry_count": retry_count})
        self.max_retries = max_retries
        self.retry_count = retry_count


class StuckException(AgentException):
    """
    死循环哈希拦截触发，Agent 陷入重复动作的死循环。

    触发时机：StuckDetector 检测到在滑动窗口内，LLM 连续生成了 N 次
    相同的 Action + Arguments 组合（MD5 哈希完全一致）。

    处理策略：Runner 捕获后立即强制终止，不再允许继续执行，
    将 finish_reason 设置为 "stuck" 并执行状态回滚。

    Args:
        action: 触发死循环的工具名称。
        action_hash: 触发拦截的 MD5 哈希值。
        window_size: 滑动窗口大小。
    """

    def __init__(self, action: str, action_hash: str, window_size: int) -> None:
        message = (
            f"Agent 死循环拦截：连续 {window_size} 次请求相同 Action '{action}'，"
            f"入参哈希完全一致 (Hash: {action_hash})"
        )
        super().__init__(message, context={"action": action, "action_hash": action_hash})
        self.action = action
        self.action_hash = action_hash
        self.window_size = window_size


class StepOverflowException(AgentException):
    """
    执行步数溢出强拦截。

    触发时机：Runner 主控制循环步数计数器超过 max_steps 限制，
    但 Agent 尚未达成 Finish 终止协议。

    处理策略：非错误性终止，将 finish_reason 设置为 "max_steps_exceeded"，
    执行快照回滚并安全退出。

    Args:
        max_steps: 最大步数限制。
        current_step: 触发时的实际步数。
    """

    def __init__(self, max_steps: int, current_step: int) -> None:
        message = f"步数溢出强拦截：执行步数 {current_step} 超出最大限制 {max_steps} 步，任务未闭环"
        super().__init__(message, context={"max_steps": max_steps, "current_step": current_step})
        self.max_steps = max_steps
        self.current_step = current_step


class TimeoutException(AgentException):
    """
    工具执行超时。

    触发时机：单个工具执行时间超过预设的 timeout_seconds 限制（
    通过 asyncio.wait_for 实现超时守卫）。

    处理策略：与 ToolException 相同，触发 Self-Correction 降级处理，
    引导模型在下一轮决策中选择不同的工具或跳过该步骤。

    Args:
        tool_name: 触发超时的工具名称。
        timeout_seconds: 设置的超时秒数。
    """

    def __init__(self, tool_name: str, timeout_seconds: float) -> None:
        message = f"工具 '{tool_name}' 执行超时（超出 {timeout_seconds}s 限制）"
        super().__init__(message, context={"tool_name": tool_name, "timeout_seconds": timeout_seconds})
        self.tool_name = tool_name
        self.timeout_seconds = timeout_seconds


class FatalException(AgentException):
    """
    不可恢复的致命错误。

    触发时机：LLM API 连接失败、Registry 损坏、环境变量缺失等
    不属于可自愈范畴的系统级严重错误。

    处理策略：Runner 不捕获此异常，直接向上传播给调用方，
    调用方应终止整个 Agent 任务并记录严重错误日志。

    Args:
        reason: 致命错误的具体原因描述。
        original_error: 原始底层系统异常对象（可选）。
    """

    def __init__(self, reason: str, original_error: Exception | None = None) -> None:
        message = f"致命系统错误（不可恢复）: {reason}"
        if original_error:
            message += f" | 底层异常: {original_error}"
        super().__init__(message, context={"reason": reason})
        self.reason = reason
        self.original_error = original_error
