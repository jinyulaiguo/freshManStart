"""
节点 8/8：安全违规拦截终止节点

===================================================================================
节点接口：
   - 输入：injection_detection_report
   - 输出：messages（拦截通知 AIMessage），node_latency_log
   - 不调用 LLM，不产生任何外部 I/O
===================================================================================
"""

import time
from langchain_core.messages import AIMessage
from cve_pipeline.state import CVETriageState


def block_response_node(state: CVETriageState) -> dict:
    """安全违规拦截终止节点。

    当输入净化节点检测到 Prompt 注入或危险命令时触发，生成标准化拦截通知
    并安全终止 Pipeline，不产生任何 LLM 调用或外部 I/O。

    Args:
        state: 当前全局 CVETriageState 快照。

    Returns:
        包含拦截通知 AIMessage 的增量更新字典。
    """
    node_start_ts = time.time()

    detection_report = state.get("injection_detection_report", "")
    tenant_id = state.get("tenant_id", "UNKNOWN")
    request_trace_id = state.get("request_trace_id", "N/A")

    block_message = (
        f"[安全拦截网关 🛡️ | TraceID: {request_trace_id} | 租户: {tenant_id}]\n\n"
        f"⚠️ 请求已被安全系统拦截，Pipeline 终止执行。\n\n"
        f"拦截原因：\n{detection_report}\n\n"
        f"处置建议：\n"
        f"  • 请确认输入内容不包含任何指令覆盖、角色劫持或系统命令注入\n"
        f"  • 如您认为此次拦截为误判，请联系安全团队提交人工审核申请\n"
        f"  • 本次请求已记录至安全审计日志，TraceID: {request_trace_id}"
    )

    latency_ms = round((time.time() - node_start_ts) * 1000, 2)

    return {
        "messages": [AIMessage(content=block_message)],
        "node_latency_log": [{
            "node": "block_response",
            "latency_ms": latency_ms,
            "tokens_used": 0,
            "reason": "SECURITY_POLICY_VIOLATION",
        }],
    }
