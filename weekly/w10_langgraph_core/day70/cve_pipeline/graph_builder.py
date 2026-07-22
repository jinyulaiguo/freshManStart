"""
CVE Triage Pipeline — 图拓扑构建与编译装配

===================================================================================
模块设计方案 (Architectural Design)
===================================================================================
设计意图：
   本模块是整个系统的"积木拼装墙"。遵循自底向上原则，将已独立测试的
   8 个业务节点、3 组路由函数通过 LangGraph StateGraph API 声明式拼装为
   完整的有向图拓扑，并绑定 MemorySaver 检查点器后编译输出 CompiledGraph。

   本模块不承担任何业务逻辑或算法实现——所有决策均委托给节点与路由函数。

图拓扑结构（有向边声明顺序）：
   START → input_sanitizer
   input_sanitizer →[R1 条件边]→ block_response | severity_triage
   severity_triage →[R2 条件边]→ human_escalation | cve_knowledge_retriever | compliance_reporter
   cve_knowledge_retriever → code_patch_generator
   code_patch_generator → static_analysis_validator
   static_analysis_validator →[R3 条件边]→ compliance_reporter | code_patch_generator | human_escalation
   human_escalation → compliance_reporter
   compliance_reporter → END
   block_response → END

全局 recursion_limit 策略：
   在 invoke 时传入 config={"recursion_limit": 15}，由 MultiDimensionalCircuitBreaker
   统一管理。图构建时不硬编码此值，确保灵活配置。
===================================================================================
"""

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from cve_pipeline.state import CVETriageState
from cve_pipeline.nodes.input_sanitizer import input_sanitizer_node
from cve_pipeline.nodes.severity_triage import severity_triage_node
from cve_pipeline.nodes.cve_retriever import cve_retriever_node
from cve_pipeline.nodes.patch_generator import patch_generator_node
from cve_pipeline.nodes.static_validator import static_validator_node
from cve_pipeline.nodes.human_escalation import human_escalation_node
from cve_pipeline.nodes.compliance_reporter import compliance_reporter_node
from cve_pipeline.nodes.block_response import block_response_node
from cve_pipeline.routers.safety_router import route_after_sanitizer
from cve_pipeline.routers.triage_router import route_after_triage
from cve_pipeline.routers.validation_router import route_after_validation


def build_cve_triage_graph(checkpointer: MemorySaver | None = None):
    """构建并编译 CVE 分诊与自动修复 Pipeline 图拓扑。

    本函数是整个系统的唯一图装配入口，执行以下步骤：
    1. 实例化 StateGraph(CVETriageState)
    2. 注册 8 个业务节点
    3. 声明 START → input_sanitizer 静态入口边
    4. 挂载 3 组条件路由边（R1/R2/R3）
    5. 声明其余静态有向边（普通边）
    6. 声明 END 出口边
    7. 绑定 checkpointer 并 compile()

    Args:
        checkpointer: LangGraph Checkpointer 实例（通常为 MemorySaver）。
                      传入 None 时编译无持久化版本（用于单元测试）。

    Returns:
        编译后的 CompiledGraph 实例，符合 Runnable 协议。
    """
    # ── Step 1: 声明有向图构建器，绑定全局 State 契约 ──
    workflow = StateGraph(CVETriageState)

    # ── Step 2: 注册 8 个业务节点 ──
    workflow.add_node("input_sanitizer", input_sanitizer_node)
    workflow.add_node("severity_triage", severity_triage_node)
    workflow.add_node("cve_knowledge_retriever", cve_retriever_node)
    workflow.add_node("code_patch_generator", patch_generator_node)
    workflow.add_node("static_analysis_validator", static_validator_node)
    workflow.add_node("human_escalation", human_escalation_node)
    workflow.add_node("compliance_reporter", compliance_reporter_node)
    workflow.add_node("block_response", block_response_node)

    # ── Step 3: 声明 START 静态入口边 ──
    workflow.add_edge(START, "input_sanitizer")

    # ── Step 4: 挂载 R1 条件路由边（安全过滤分流）──
    workflow.add_conditional_edges(
        source="input_sanitizer",
        path=route_after_sanitizer,
        path_map={
            "block_response": "block_response",
            "severity_triage": "severity_triage",
        },
    )

    # ── Step 5: 挂载 R2 条件路由边（严重性三级分流）──
    workflow.add_conditional_edges(
        source="severity_triage",
        path=route_after_triage,
        path_map={
            "human_escalation": "human_escalation",
            "cve_knowledge_retriever": "cve_knowledge_retriever",
            "compliance_reporter": "compliance_reporter",
        },
    )

    # ── Step 6: 知识检索 → 补丁生成（静态有向边）──
    workflow.add_edge("cve_knowledge_retriever", "code_patch_generator")

    # ── Step 7: 补丁生成 → 静态分析验证（静态有向边）──
    workflow.add_edge("code_patch_generator", "static_analysis_validator")

    # ── Step 8: 挂载 R3 条件路由边（验证结果三路路由，含反馈环路）──
    workflow.add_conditional_edges(
        source="static_analysis_validator",
        path=route_after_validation,
        path_map={
            "compliance_reporter": "compliance_reporter",
            "code_patch_generator": "code_patch_generator",   # ← 反馈环路
            "human_escalation": "human_escalation",
        },
    )

    # ── Step 9: 人工升舱 → 合规报告（静态有向边，升舱后仍签发报告）──
    workflow.add_edge("human_escalation", "compliance_reporter")

    # ── Step 10: 声明两个 END 出口边 ──
    workflow.add_edge("compliance_reporter", END)
    workflow.add_edge("block_response", END)

    # ── Step 11: 绑定 Checkpointer 并编译 ──
    return workflow.compile(checkpointer=checkpointer)
