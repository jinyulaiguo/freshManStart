"""子图结构化审计节点 (Day 77 物理隔离)

设计方案与架构说明：
----------------------------------------------------------------
本节点负责生成符合安全规范的子图结构化审计对象。
审计字典写入 `state.audit_record` 私有字段，不会泄漏至主图状态。

数据流：
--------
Input (generated_sql, risk_level) -> 结构化字典 -> 写入 state.audit_record
"""

import time
from typing import Dict, Any
from weekly.w11_langgraph_advanced.day77.state.analysis_state import AnalysisSubState


async def audit_node(state: AnalysisSubState) -> Dict[str, Any]:
    """子图节点：生成内部结构化审计日志。"""
    sql = state.get("generated_sql", "")
    risk = state.get("risk_level", "unknown")

    print(f"  [Subgraph Worker: Audit] 生成结构化安全审计日志...")

    record = {
        "timestamp": time.time(),
        "operator": "SQL_AGENT_SUBGRAPH_AUDITOR",
        "target_sql": sql,
        "risk_level": risk,
        "status": "AUDITED_AND_VERIFIED"
    }

    return {
        "audit_record": record,
        "internal_trace": [f"Audit record created for SQL: '{sql}'"]
    }
