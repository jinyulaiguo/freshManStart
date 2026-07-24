"""
==============================================================================
LLM Reliability Adapter - 归一化事件协议契约 (contracts/events.py)
==============================================================================

设计方案说明：
1. 设计意图 (Design Intent)：
   屏蔽底关不同的大模型 Provider（OpenAI / DeepSeek / Ollama / Claude）返回格式差异，
   将流式增量（Streaming Chunks）、Tool Calling 指令、结构化提取结果以及异常统一归一化为标准的 AgentEvent。
2. 类与函数结构 (Class Structure)：
   - `EventType`: 事件类型枚举 (TEXT_DELTA, TOOL_CALL, STRUCTURED_OUTPUT, ERROR, THINKING_DELTA)。
   - `AgentEvent`: 标准事件 Payload 容器。
3. 关键数据流 (Data Flow)：
   - LLM Driver 接收 Raw Output ➔ 映射转换为 AgentEvent 序列 ➔ 供上层 Event Loop / State Runtime 消费。
4. 核心用例考量 (Test Case Intent)：
   - 验证事件序列可被无缝 JSON 序列化与反序列化，确保跨进程 / 网络传输不丢失数据。
==============================================================================
"""

import time
import uuid
from enum import Enum
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class EventType(str, Enum):
    """Agent 事件类型枚举"""
    THINKING_DELTA = "thinking_delta"    # 深度思考/CoT 流式增量片段 (如 <think> 内部)
    TEXT_DELTA = "text_delta"            # 正文流式增量片段
    TOOL_CALL = "tool_call"              # 结构化工具调用指令
    STRUCTURED_OUTPUT = "structured"     # 最终通过 Validator 校验的结构化数据
    ERROR = "error"                      # 运行时异常事件


class AgentEvent(BaseModel):
    """
    统一归一化 Agent 事件契约模型
    """
    event_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="全局唯一事件 ID"
    )
    
    type: EventType = Field(
        ...,
        description="事件类型分类"
    )
    
    timestamp: float = Field(
        default_factory=time.time,
        description="事件产生时的 Unix 时间戳"
    )
    
    payload: Dict[str, Any] = Field(
        default_factory=dict,
        description="事件载荷数据 (如 content, tool_name, arguments, error_detail 等)"
    )
    
    metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="可选的追踪元数据 (如 run_id, node_id, model_name 等)"
    )

    def to_dict(self) -> Dict[str, Any]:
        """将事件转换为字典格式"""
        return self.model_dump()
