import operator
from typing import Annotated, Sequence, TypedDict, Any
from langchain_core.messages import BaseMessage

class ResearchAgentState(TypedDict):
    """
    研究助手的核心状态保险箱 (State Vault)。
    利用 Annotated 和 operator.add 实现消息队列的并发安全规约 (Reducers)。
    """
    messages: Annotated[Sequence[BaseMessage], operator.add]
    
    # 记录动态召回的工具列表，用于调试面板展示
    active_tools: list[str]
    
    # 全链路追踪 ID
    correlation_id: str
    
    # 发生异常时的结构化退避记录
    error_context: str | None
