"""
OpsChat CLI - 统一流式客户端契约 (protocols.py)

=========================================
设计方案说明
=========================================
1. 设计意图：
   通过 Python 的 typing.Protocol 提供大模型流式调用客户端的静态类型契约。
   这使得 FallbackController 能够与具体的厂商模型适配器完全解耦，能够无缝插拔不同的流式客户端适配层。

2. 类与函数结构：
   - StreamingLLMClient (Protocol):
     - model_name (str): 模型名称属性。
     - stream_generate (method): 异步生成器方法，用于向外部流式产出 StreamChunk。

3. 关键数据流流向：
   `外部组件 (如 FallbackController)` -> `调用 stream_generate(messages)`
   -> `逐个接收返回的 StreamChunk 异步生成器对象`
=========================================
"""

from typing import Protocol, List, Dict, Any, Optional, AsyncGenerator, runtime_checkable
from weekly.w03_llm_and_api.project.models import StreamChunk

@runtime_checkable
class StreamingLLMClient(Protocol):
    """
    支持流式文本生成的大模型客户端统一契约类型。
    """
    model_name: str

    async def stream_generate(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        **kwargs: Any
    ) -> AsyncGenerator[StreamChunk, None]:
        """
        统一的流式文本生成契约方法。
        
        Args:
            messages: 符合 ChatML 规范的多轮对话消息列表。
            temperature: 采样温度控制。
            max_tokens: 最大生成 Token 限制。
            **kwargs: 额外的模型私有参数。
            
        Returns:
            逐块产生 StreamChunk 的异步生成器。
            
        Raises:
            LLMError: 统一异常体系下的子类异常。
        """
        ...
