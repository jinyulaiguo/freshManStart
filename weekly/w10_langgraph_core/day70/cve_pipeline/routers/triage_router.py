"""R2：严重性分诊路由函数"""
from typing import Literal
from cve_pipeline.state import CVETriageState


def route_after_triage(
    state: CVETriageState,
) -> Literal["human_escalation", "cve_knowledge_retriever", "compliance_reporter"]:
    """R2 严重性分诊路由：根据 severity 字段实现三路分流。

    路由逻辑（基于 CVSS v3.1 分级策略）：
      CRITICAL  →  "human_escalation"（强制人工专席处置，跳过自动修复）
      HIGH      →  "cve_knowledge_retriever"（启动自动修复 Pipeline）
      MEDIUM    →  "cve_knowledge_retriever"（启动自动修复 Pipeline）
      LOW       →  "compliance_reporter"（直接签发低风险合规报告）
      其他/未知  →  "cve_knowledge_retriever"（保守策略：按 HIGH 处理）

    Args:
        state: 当前全局 CVETriageState 快照。

    Returns:
        下一跳节点名称字符串，作为 path_map 的查找键。
    """
    severity = state.get("severity", "MEDIUM").upper()

    if severity == "CRITICAL":
        return "human_escalation"
    elif severity == "LOW":
        return "compliance_reporter"
    else:
        # HIGH / MEDIUM / UNKNOWN 均进入自动修复路径
        return "cve_knowledge_retriever"
