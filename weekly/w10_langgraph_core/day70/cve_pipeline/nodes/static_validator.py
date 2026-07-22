"""
节点 5/8：LLM 静态分析验证节点

===================================================================================
模块设计方案 (Architectural Design)
===================================================================================
设计意图：
   本节点是 Pipeline 反馈环路的质量门控节点。对 patch_generator 生成的补丁代码
   执行安全性审查，判断补丁是否真正修复了原始漏洞，以及是否引入了新的安全风险。

   验证结论驱动路由函数 R3 的三路决策：
   - PASS：补丁通过全部安全检查 → 流转至 compliance_reporter
   - FAIL（retries < 2）：补丁存在问题 → 将 findings 注入并回流至 patch_generator
   - FAIL（retries >= 2）：多次重试仍失败 → 升舱至 human_escalation

节点接口：
   - 真实 LLM API 调用（JSON Mode）
   - 输入：generated_patch_code, vulnerability_type, patch_retry_count
   - 输出更新字段：
       validation_verdict, validation_findings
       messages, total_llm_tokens, node_latency_log
===================================================================================
"""

import time
import asyncio
from langchain_core.messages import AIMessage
from cve_pipeline.state import CVETriageState
from cve_pipeline.llm_client import CVELLMClient, LLMParseError, LLMRequestError

_VALIDATOR_SYSTEM_PROMPT = """你是一名专业的 Python 安全代码审查工程师，专注于安全漏洞修复代码的质量审查。
你将收到一段 Python 补丁代码，需要对其执行多维度安全审查。

请严格按照以下 JSON 格式输出审查结论，不得包含任何 Markdown 代码块：
{
  "verdict": "<PASS|FAIL|PARTIAL>",
  "overall_assessment": "整体评估描述（1-2句话）",
  "checks": {
    "fixes_original_vulnerability": true,
    "no_new_vulnerabilities": true,
    "has_input_validation": true,
    "has_proper_exception_handling": true,
    "follows_secure_coding_standards": true
  },
  "findings": [
    "具体发现的问题1（若无则为空列表）",
    "具体发现的问题2"
  ],
  "security_score": <0-100的整数，100表示完全安全>
}

判定规则：
- PASS: 所有 checks 均为 true，findings 为空，security_score >= 80
- PARTIAL: 大部分 checks 通过但存在次要问题，security_score 60-79
- FAIL: 存在关键 check 失败或高危问题，security_score < 60"""


async def _async_static_validate(state: CVETriageState) -> dict:
    """异步执行 LLM 静态分析验证的核心逻辑。"""
    node_start_ts = time.time()
    client = CVELLMClient()

    patch_code = state.get("generated_patch_code", "")
    vulnerability_type = state.get("vulnerability_type", "Unknown")
    patch_retry_count = state.get("patch_retry_count", 0)
    request_trace_id = state.get("request_trace_id", "N/A")

    # 补丁代码为空时直接判定 FAIL
    if not patch_code or len(patch_code.strip()) < 50:
        latency_ms = round((time.time() - node_start_ts) * 1000, 2)
        return {
            "validation_verdict": "FAIL",
            "validation_findings": ["补丁代码为空或过短，无法执行有效验证"],
            "messages": [AIMessage(content=f"[静态分析验证节点 | TraceID: {request_trace_id}] ❌ 补丁代码无效，直接判定 FAIL")],
            "total_llm_tokens": 0,
            "node_latency_log": [{"node": "static_analysis_validator", "latency_ms": latency_ms, "tokens_used": 0, "verdict": "FAIL"}],
        }

    user_prompt = f"""请对以下 Python 补丁代码进行安全审查：

原始漏洞类型: {vulnerability_type}
本次是第 {patch_retry_count} 轮补丁（0=首次，>0=重试修正）

<patch_code>
{patch_code[:3000]}
</patch_code>

请全面审查该补丁是否正确修复了 {vulnerability_type} 漏洞，并输出 JSON 格式审查报告。"""

    # 降级默认值
    verdict = "FAIL"
    findings: list[str] = ["LLM 验证服务暂时不可用，保守判定为 FAIL"]
    security_score = 0
    tokens_used = 0

    try:
        parsed, tokens_used = await client.classify(
            system_prompt=_VALIDATOR_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.1,
            max_tokens=800,
        )
        if isinstance(parsed, dict):
            verdict = parsed.get("verdict", "FAIL").upper()
            if verdict not in ("PASS", "FAIL", "PARTIAL"):
                verdict = "FAIL"
            findings = parsed.get("findings", [])
            if not isinstance(findings, list):
                findings = [str(findings)]
            security_score = int(parsed.get("security_score", 0))
            # PARTIAL 视为 FAIL 以触发重试逻辑（严格质量门控）
            if verdict == "PARTIAL":
                verdict = "FAIL"
                if not findings:
                    findings = ["补丁部分修复，存在次要安全问题，需进一步改进"]

    except (LLMParseError, LLMRequestError, KeyError, TypeError, ValueError) as e:
        findings = [f"静态验证解析失败: {type(e).__name__}，保守判定为 FAIL"]

    latency_ms = round((time.time() - node_start_ts) * 1000, 2)

    verdict_icon = "✅" if verdict == "PASS" else "❌"
    status_msg = (
        f"[静态分析验证节点 {verdict_icon} | TraceID: {request_trace_id}] "
        f"验证结论: {verdict} | 安全评分: {security_score}/100 | "
        f"发现问题: {len(findings)} 条 | 重试轮次: {patch_retry_count} | 耗时: {latency_ms}ms"
        + (f"\n问题摘要: {findings[0]}" if findings else "")
    )

    return {
        "validation_verdict": verdict,
        "validation_findings": findings,
        "messages": [AIMessage(content=status_msg)],
        "total_llm_tokens": tokens_used,
        "node_latency_log": [{
            "node": "static_analysis_validator",
            "latency_ms": latency_ms,
            "tokens_used": tokens_used,
            "verdict": verdict,
            "security_score": security_score,
            "findings_count": len(findings),
        }],
    }


def _run_async_in_thread(coro_fn, *args, **kwargs):
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


def static_validator_node(state: CVETriageState) -> dict:
    """LLM 静态分析验证节点（同步入口，线程安全防 Event Loop 冲突）。

    Args:
        state: 当前全局 CVETriageState 快照。

    Returns:
        包含 validation_verdict/validation_findings 及可观测字段的增量更新字典。
    """
    return _run_async_in_thread(_async_static_validate, state)
