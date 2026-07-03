"""
设计方案：
- 设计意图：实现 `ToolCallbackProtocol` 接口，提供一个向标准日志管道输出生命周期事件的 Trace 控制台与审计输出实现。在发生异常时，利用 `traceback` 模块序列化完整的包装级与底层因果级异常调用栈，保证错误的第一现场不丢失。
- 类与函数结构：
  - `ConsoleTracer` 类：接收 logger 实例进行日志托管，包含对 `on_tool_start`, `on_tool_success`, `on_tool_error` 契约方法的具体实现。
- 关键数据流向：
  - 调度引擎生命周期触发现场 -> 传入参数信息 -> 拼接高亮友好格式 -> 通过 `logger` 对象写入控制台和日志文件。
"""

import logging
import traceback
from typing import Optional

class ConsoleTracer:
    """可观测性 Trace 实现，隐式契约继承于 ToolCallbackProtocol"""
    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger("tool_runner.callbacks")

    def on_tool_start(self, trace_id: str, tool_name: str, raw_args: str) -> None:
        self.logger.info(
            f" [Start] Tool '{tool_name}' triggered. "
            f"TraceID: {trace_id} | RawArgs: {raw_args}"
        )

    def on_tool_success(self, trace_id: str, tool_name: str, result: str, duration: float) -> None:
        self.logger.info(
            f" [Success] Tool '{tool_name}' completed. "
            f"TraceID: {trace_id} | Duration: {duration:.4f}s | Result: {result}"
        )

    def on_tool_error(self, trace_id: str, tool_name: str, error: Exception, duration: float) -> None:
        # 格式化完整的底层异常链条堆栈
        tb_lines = traceback.format_exception(type(error), error, error.__traceback__)
        tb_text = "".join(tb_lines).strip()
        
        self.logger.error(
            f" [Error] Tool '{tool_name}' crashed! "
            f"TraceID: {trace_id} | Duration: {duration:.4f}s | Error: {str(error)}\n"
            f"------------- 异常调用链追踪堆栈 -------------\n"
            f"{tb_text}\n"
            f"--------------------------------------------"
        )
