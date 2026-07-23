"""主图 SQLAgentState 状态契约定义 (Day 77 企业级实战)

设计方案与架构说明：
----------------------------------------------------------------
本模块定义主 SQL Agent 图状态契约。
1. 消息链与通道规约：
   - `messages`: 使用 `add_messages` 规约器，处理对话上下文与 ToolCall。
   - `error_log` / `audit_trail`: 使用 `operator.add` 声明强类型追加规约器（Reducer），
     避免并发子节点合并时发生覆盖覆盖掉日志。
2. 风险与审批语义：
   - `risk_level`: 区分 "safe" (自动放行), "sensitive" (触发 interrupt 人工审批), "blocked" (直接阻断拦截)。
   - `approval_status`: 记录人工审核状态 ("pending", "approved", "rejected", "edited")。

数据流与生命周期：
------------------
Input Query -> [generated_sql] -> [risk_level + risk_analysis] -> (HITL 审批) -> [execution_result] -> [audit_trail]
"""

import operator
from typing import Annotated, Literal, Optional, List, Dict, Any
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage


class SQLAgentState(TypedDict):
    """SQL Agent 主图状态契约。
    
    Attributes:
        messages: 对话消息队列 (带 add_messages 规约)
        generated_sql: LLM 生成的 SQL 字符串
        sql_params: SQL 绑定参数字典
        risk_level: 风控等级 ("safe", "sensitive", "blocked")
        risk_analysis: 规则初筛 + LLM 语义风险分析文本
        approval_status: 人工审批状态 ("pending", "approved", "rejected", "edited")
        execution_result: PostgreSQL 执行返回的结果数据列表
        error_log: 运行异常与报错日志链 (追加 Reducer)
        audit_trail: 全流程安全审计日志链 (追加 Reducer)
    """
    messages: Annotated[List[BaseMessage], add_messages]
    generated_sql: Optional[str]
    sql_params: Optional[Dict[str, Any]]
    risk_level: Literal["safe", "sensitive", "blocked"]
    risk_analysis: Optional[str]
    approval_status: Optional[Literal["pending", "approved", "rejected", "edited"]]
    execution_result: Optional[List[Dict[str, Any]]]
    error_log: Annotated[List[str], operator.add]
    audit_trail: Annotated[List[str], operator.add]
