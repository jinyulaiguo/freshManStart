"""
OpsChat CLI - 统一异常定义 (exceptions.py)

=========================================
设计方案说明
=========================================
1. 设计意图：
   在大模型调用中，不同厂商 SDK 会抛出不同的私有网络或接口异常（例如 openai.APIStatusError）。
   本模块提供一套统一的、高内聚的适配层异常模型，使上层调用者（如 FallbackController 和 CLI 主循环）
   能免于耦合具体的 SDK 异常，便于实现优雅降级与异常日志记录。

2. 类与函数结构：
   - LLMError (Exception): 适配层标准异常基类。
   - LLMAPIError (LLMError): 模型服务端接口返回非 200 响应错误。
   - LLMConnectionError (LLMError): 网络断连、解析失败或客户端请求超时。

3. 关键数据流流向：
   `底册特定适配器` -> `捕获原生异常 (openai.APIError / httpx.HTTPError)` 
   -> `包装为 LLMAPIError 或 LLMConnectionError` -> `抛出给 FallbackController`
=========================================
"""

class LLMError(Exception):
    """
    大模型适配层标准异常基类。
    """
    pass


class LLMAPIError(LLMError):
    """
    大模型服务端 API 返回非 200 状态码时的异常。
    """
    def __init__(self, status_code: int, message: str):
        super().__init__(f"LLM API Error (Status {status_code}): {message}")
        self.status_code = status_code
        self.message = message


class LLMConnectionError(LLMError):
    """
    大模型客户端在网络握手、网络传输超时或连接被重置时的底层连接异常。
    """
    pass
