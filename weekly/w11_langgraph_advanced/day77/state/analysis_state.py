"""子图 AnalysisSubState 状态契约定义 (Day 77 并行安全 Reducer 设计)

设计方案与架构说明：
----------------------------------------------------------------
本模块定义独立于主图的并发分析子图状态契约。
1. 并发安全 Reducer:
   - 为子图内部过程追踪日志 `internal_trace` 添加 `Annotated[List[str], operator.add]` 并发追加规约器。
   - 解决三路 Fan-out 并行节点 (validate, summarize, audit) 同时向该 key 写入时引发的 LangGraph `InvalidUpdateError` 竞态冲突。
2. 状态隔离原则 (State Isolation):
   - 包含子图私有内部字段 `internal_trace` 与 `audit_record`，避免污染主图状态。

数据流：
--------
MainGraph -> [Input Mapping] -> ChildGraph (validate, summarize, audit 并行) -> [Output Mapping] -> MainGraph
"""

import operator
from typing import Annotated, List, Dict, Any, Optional
from typing_extensions import TypedDict


class AnalysisSubState(TypedDict):
    """并行分析子图状态契约。
    
    Attributes:
        execution_result: SQL 执行数据行 (主图输入)
        generated_sql: 执行的 SQL 语句 (主图输入)
        risk_level: 风控等级 (主图输入)
        validation_report: 数据校验报告 (子图输出写回主图)
        summary_text: 真实 LLM 生成的数据自然语言摘要 (子图输出写回主图)
        internal_trace: 子图私有过程追踪日志 (并发安全追加 Reducer)
        audit_record: 子图私有结构化审计字典 (隔离不泄漏)
    """
    execution_result: Optional[List[Dict[str, Any]]]
    generated_sql: Optional[str]
    risk_level: str
    validation_report: Optional[str]
    summary_text: Optional[str]
    internal_trace: Annotated[List[str], operator.add]
    audit_record: Optional[Dict[str, Any]]
