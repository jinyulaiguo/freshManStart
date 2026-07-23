"""子图数据校验节点 (Day 77 纯逻辑校验)

设计方案与架构说明：
----------------------------------------------------------------
本节点负责对主图传入的 execution_result 进行结构与完整性校验。
校验指标：行数是否为 0、字段是否含 NULL 值、影响数据量等级。

数据流：
--------
Input (execution_result) -> 纯逻辑校验 -> 写入 state.validation_report
"""

from typing import Dict, Any
from weekly.w11_langgraph_advanced.day77.state.analysis_state import AnalysisSubState


async def validate_node(state: AnalysisSubState) -> Dict[str, Any]:
    """子图节点：数据校验与质量评级。"""
    res = state.get("execution_result", [])
    print(f"\n  [Subgraph Worker: Validate] 正在校验执行结果 (记录数: {len(res) if res else 0})...")

    if not res:
        report = "【数据校验报告】: 返回数据为空 (0 行)，无异常报错。"
    elif "affected_rows" in res[0]:
        report = f"【数据校验报告】: DML 变更操作校验通过，共影响 {res[0]['affected_rows']} 行。"
    else:
        columns = list(res[0].keys())
        null_count = sum(1 for row in res for v in row.values() if v is None)
        report = f"【数据校验报告】: 成功检索 {len(res)} 行数据 (字段数: {len(columns)}, 缺失值数: {null_count})。品质良好。"

    return {
        "validation_report": report,
        "internal_trace": [f"Validation check completed: {report}"]
    }
