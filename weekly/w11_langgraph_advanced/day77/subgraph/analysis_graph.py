"""并行分析子图编排模块 (Day 77 物理隔离与 Barrier 汇聚)

设计方案与架构说明：
----------------------------------------------------------------
本模块组装并编译独立可运行的分析子图。
1. 拓扑扇出 (Fan-out)：
   - 从 START 同时分流触发 `validate` (纯逻辑校验), `summarize` (真实 LLM 2s 延时), `audit` (结构化审计)。
2. 屏障汇聚 (Fan-in Barrier Hub):
   - 三路 Worker 连接至 `merge` 节点。Superstep 必须冻结等待所有 Worker (包含 2s 耗时的 summarize) 完毕后解冻推进！
3. Schema 状态隔离：
   - 显式使用 `AnalysisSubState`。编译后的 compiled Graph 可直接作为 Node 挂载至主图。

拓扑架构：
----------
          ┌─► validate  ──┐
[START] ──┼─► summarize ──┼─► merge ──► [END]
          └─► audit     ──┘
"""

from typing import Dict, Any
from langgraph.graph import StateGraph, START, END

from weekly.w11_langgraph_advanced.day77.state.analysis_state import AnalysisSubState
from weekly.w11_langgraph_advanced.day77.subgraph.validate_node import validate_node
from weekly.w11_langgraph_advanced.day77.subgraph.summarize_node import summarize_node
from weekly.w11_langgraph_advanced.day77.subgraph.audit_node import audit_node


async def merge_node(state: AnalysisSubState) -> Dict[str, Any]:
    """子图汇聚节点：解冻屏障并汇总数据归约结果。"""
    val_rep = state.get("validation_report", "")
    sum_text = state.get("summary_text", "")
    aud_rec = state.get("audit_record", {})

    print(f"\n  [Subgraph Barrier Hub: Merge] 三路并发解冻！接收到两路报告与结构化审计:")
    print(f"    • 校验报告: {val_rep}")
    print(f"    • LLM 摘要: {sum_text}")
    print(f"    • 审计状态: {aud_rec.get('status') if aud_rec else 'None'}")

    return {
        "internal_trace": ["Barrier Hub merged all parallel worker outputs."]
    }


def build_analysis_subgraph():
    """构建并编译分析子图。
    
    Returns:
        CompiledStateGraph: 可独立运行或作为 Node 嵌入主图的 CompiledGraph。
    """
    builder = StateGraph(AnalysisSubState)

    # 1. 注册子图节点
    builder.add_node("validate", validate_node)
    builder.add_node("summarize", summarize_node)
    builder.add_node("audit", audit_node)
    builder.add_node("merge", merge_node)

    # 2. 拓扑扇出 (Fan-out)
    builder.add_edge(START, "validate")
    builder.add_edge(START, "summarize")
    builder.add_edge(START, "audit")

    # 3. 拓扑扇入 (Fan-in Barrier)
    builder.add_edge("validate", "merge")
    builder.add_edge("summarize", "merge")
    builder.add_edge("audit", "merge")

    # 4. 结束
    builder.add_edge("merge", END)

    return builder.compile()
