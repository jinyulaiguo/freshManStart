"""
节点 6/8：高危人工升舱网关节点

===================================================================================
模块设计方案 (Architectural Design)
===================================================================================
设计意图：
   本节点处理两类升舱入口：
   1. CRITICAL 直接升舱：分诊严重性为 CRITICAL，直接跳过自动修复流程
   2. 补丁重试耗尽升舱：patch_retry_count >= 2 且 validation_verdict == FAIL

   节点职责：
   - 构建结构化 Jira 工单 Payload（包含所有诊断信息）
   - 生成人工专席处置通知
   - 不调用 LLM（确保升舱路径的低延迟与高可靠性）
===================================================================================
"""

import time
import json
from datetime import datetime, timezone
from langchain_core.messages import AIMessage
from cve_pipeline.state import CVETriageState


def human_escalation_node(state: CVETriageState) -> dict:
    """高危人工升舱网关节点。

    构建结构化 Jira 工单 Payload，记录升舱原因、漏洞信息、补丁尝试记录，
    并生成人工专席处置通知。不调用 LLM，确保升舱路径低延迟高可靠。

    Args:
        state: 当前全局 CVETriageState 快照。

    Returns:
        包含结构化升舱 Payload 的 messages 增量更新字典。
    """
    node_start_ts = time.time()

    severity = state.get("severity", "UNKNOWN")
    cve_id = state.get("cve_id", "UNKNOWN")
    vulnerability_type = state.get("vulnerability_type", "Unknown")
    affected_component = state.get("affected_component", "Unknown")
    tenant_id = state.get("tenant_id", "UNKNOWN")
    request_trace_id = state.get("request_trace_id", "N/A")
    patch_retry_count = state.get("patch_retry_count", 0)
    validation_verdict = state.get("validation_verdict", "PENDING")
    validation_findings = state.get("validation_findings", [])
    generated_patch_code = state.get("generated_patch_code", "")
    risk_score = state.get("risk_score", 0.0)

    # 判断升舱原因
    if severity == "CRITICAL":
        escalation_reason = "CRITICAL_SEVERITY_DIRECT_ESCALATION"
        escalation_desc = f"漏洞严重性等级为 CRITICAL（CVSS {risk_score:.1f}），系统策略要求强制人工专席处置"
        priority = "P0_CRITICAL"
    else:
        escalation_reason = "PATCH_RETRY_EXHAUSTED"
        escalation_desc = f"补丁自动修复流程连续 {patch_retry_count} 次验证失败，超出最大重试阈值（2次），触发人工介入"
        priority = "P1_HIGH"

    # 构建 Jira 工单 Payload
    jira_ticket = {
        "ticket_type": "SECURITY_INCIDENT",
        "priority": priority,
        "title": f"[{severity}] {vulnerability_type} 漏洞 in {affected_component} — {cve_id}",
        "tenant_id": tenant_id,
        "trace_id": request_trace_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "escalation_reason": escalation_reason,
        "escalation_description": escalation_desc,
        "vulnerability_details": {
            "severity": severity,
            "cve_id": cve_id,
            "type": vulnerability_type,
            "component": affected_component,
            "cvss_score": risk_score,
        },
        "auto_remediation_attempt": {
            "total_patch_iterations": patch_retry_count,
            "last_validation_verdict": validation_verdict,
            "validation_findings": validation_findings,
            "last_patch_code_snippet": generated_patch_code[:500] + "..." if len(generated_patch_code) > 500 else generated_patch_code,
        },
        "required_actions": [
            "立即通知首席安全工程师（CSE）进行人工代码审查",
            f"将 {affected_component} 临时下线或启用降级模式",
            "在 24h 内提交安全补丁并经人工代码评审",
            "记录 SLA 违规事件（若为 CRITICAL）",
        ],
        "sla_requirement": "P0: 4小时内响应 | P1: 8小时内响应",
    }

    latency_ms = round((time.time() - node_start_ts) * 1000, 2)

    status_msg = (
        f"[人工升舱网关 🚨 | TraceID: {request_trace_id}]\n"
        f"升舱原因: {escalation_reason}\n"
        f"优先级: {priority}\n"
        f"工单摘要: {jira_ticket['title']}\n"
        f"必要行动:\n" + "\n".join(f"  • {a}" for a in jira_ticket["required_actions"]) +
        f"\n\n工单 Payload（JSON）:\n```json\n{json.dumps(jira_ticket, ensure_ascii=False, indent=2)}\n```"
    )

    return {
        "messages": [AIMessage(content=status_msg)],
        "node_latency_log": [{
            "node": "human_escalation",
            "latency_ms": latency_ms,
            "tokens_used": 0,
            "escalation_reason": escalation_reason,
            "priority": priority,
        }],
    }
