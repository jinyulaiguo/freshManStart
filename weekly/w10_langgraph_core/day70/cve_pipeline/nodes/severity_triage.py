"""
节点 2/8：LLM 严重性分诊节点

===================================================================================
模块设计方案 (Architectural Design)
===================================================================================
设计意图：
   本节点是 Pipeline 的核心智能决策枢纽。调用真实 LLM API，对通过安全净化的
   漏洞描述执行结构化分析，输出四级严重性评估结果，驱动后续条件路由 R2 进行
   三路分流。

   分诊逻辑依据 CVSS v3.1 评分体系：
   - CRITICAL (9.0-10.0)：远程代码执行、未授权完全控制等
   - HIGH     (7.0-8.9)：SQL 注入、认证绕过、特权提升等
   - MEDIUM   (4.0-6.9)：跨站脚本、信息泄露、拒绝服务等
   - LOW      (0.1-3.9)：配置错误、低危信息暴露等

节点接口：
   - 真实 LLM API 调用（JSON Mode）
   - 输入：state["raw_input"], state["injection_detection_report"]
   - 输出更新字段：
       severity, cve_id, affected_component, vulnerability_type
       messages, total_llm_tokens, node_latency_log

降级策略：
   LLM 输出解析失败时，默认降级为 MEDIUM，确保 Pipeline 不因分诊节点异常中断。
===================================================================================
"""

import time
import asyncio
from langchain_core.messages import AIMessage
from cve_pipeline.state import CVETriageState
from cve_pipeline.llm_client import CVELLMClient, LLMParseError, LLMRequestError

_TRIAGE_SYSTEM_PROMPT = """你是一名资深 CVE 漏洞安全分析师，专精于 CVSS v3.1 评分体系。
用户将提交一段漏洞描述文本。你必须严格按以下 JSON 格式输出分析结果，不得输出任何其他内容：

{
  "severity": "<CRITICAL|HIGH|MEDIUM|LOW>",
  "cve_id": "<识别到的CVE编号，若无则填 UNKNOWN>",
  "vulnerability_type": "<漏洞类型，如 SQLi/XSS/RCE/SSRF/LFI/IDOR/XXE/CSRF/BufferOverflow/PrivilegeEscalation/AuthBypass/InformationDisclosure/Other>",
  "affected_component": "<受影响的组件或模块名称>",
  "risk_rationale": "<用一句话说明严重性评级依据>",
  "estimated_cvss_score": <0.0~10.0之间的浮点数>
}

严重性评级规则（CVSS v3.1）：
- CRITICAL: RCE、完全系统接管、未授权根访问，CVSS >= 9.0
- HIGH: SQLi含数据泄露、认证绕过、特权提升、SSRF内网穿透，CVSS 7.0-8.9
- MEDIUM: 反射型XSS、敏感信息泄露、路径遍历、DoS，CVSS 4.0-6.9
- LOW: 配置信息暴露、低危日志泄露、版本信息披露，CVSS 0.1-3.9"""


async def _async_severity_triage(state: CVETriageState) -> dict:
    """异步执行 LLM 严重性分诊的核心逻辑。"""
    node_start_ts = time.time()
    client = CVELLMClient()

    raw_input = state.get("raw_input", "")
    request_trace_id = state.get("request_trace_id", "N/A")

    user_prompt = f"""请对以下安全漏洞描述进行 CVSS v3.1 严重性分诊：

<vulnerability_description>
{raw_input}
</vulnerability_description>

请严格按照要求的 JSON 格式输出，不得包含任何 Markdown 代码块或额外说明。"""

    # 降级默认值
    severity = "MEDIUM"
    cve_id = "UNKNOWN"
    vulnerability_type = "Unknown"
    affected_component = "Unknown"
    risk_score = 5.0
    tokens_used = 0
    parse_error_msg = ""

    try:
        parsed, tokens_used = await client.classify(
            system_prompt=_TRIAGE_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.1,
            max_tokens=600,
        )
        severity = parsed.get("severity", "MEDIUM").upper()
        # 严重性枚举校验，防止 LLM 幻觉
        if severity not in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
            severity = "MEDIUM"
        cve_id = parsed.get("cve_id", "UNKNOWN")
        vulnerability_type = parsed.get("vulnerability_type", "Unknown")
        affected_component = parsed.get("affected_component", "Unknown")
        risk_score = float(parsed.get("estimated_cvss_score", 5.0))
        risk_score = max(0.0, min(10.0, risk_score))  # 边界值裁剪

    except (LLMParseError, LLMRequestError, KeyError, TypeError, ValueError) as e:
        parse_error_msg = f"[分诊节点降级] 解析异常: {type(e).__name__}: {e}，已降级为 MEDIUM"

    latency_ms = round((time.time() - node_start_ts) * 1000, 2)

    status_msg = (
        f"[严重性分诊节点 | TraceID: {request_trace_id}] "
        f"分诊完成 → 严重性: {severity} | 漏洞类型: {vulnerability_type} | "
        f"影响组件: {affected_component} | CVE: {cve_id} | "
        f"CVSS 评分: {risk_score:.1f} | 耗时: {latency_ms}ms"
        + (f"\n⚠️ {parse_error_msg}" if parse_error_msg else "")
    )

    return {
        "severity": severity,
        "cve_id": cve_id,
        "vulnerability_type": vulnerability_type,
        "affected_component": affected_component,
        "risk_score": risk_score,
        "messages": [AIMessage(content=status_msg)],
        "total_llm_tokens": tokens_used,
        "node_latency_log": [{
            "node": "severity_triage",
            "latency_ms": latency_ms,
            "tokens_used": tokens_used,
            "severity": severity,
            "cvss_score": risk_score,
        }],
    }


def _run_async_in_thread(coro_fn, *args, **kwargs):
    """安全地在可能存在 running event loop 的环境中执行 async 协程。"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(asyncio.run, coro_fn(*args, **kwargs))
            return future.result()
    else:
        return asyncio.run(coro_fn(*args, **kwargs))


def severity_triage_node(state: CVETriageState) -> dict:
    """LLM 严重性分诊节点（同步入口，线程安全防 Event Loop 冲突）。

    Args:
        state: 当前全局 CVETriageState 快照。

    Returns:
        包含 severity/cve_id/vulnerability_type/affected_component/risk_score
        以及 messages/total_llm_tokens/node_latency_log 的增量更新字典。
    """
    return _run_async_in_thread(_async_severity_triage, state)
