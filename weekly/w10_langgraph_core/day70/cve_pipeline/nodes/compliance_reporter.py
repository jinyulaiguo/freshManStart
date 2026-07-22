"""
节点 7/8：LLM 合规报告签发节点

===================================================================================
模块设计方案 (Architectural Design)
===================================================================================
设计意图：
   本节点是 Pipeline 的终态汇聚节点，负责整合全流程上下文，调用 LLM 生成符合
   ISO 27001 / NIST 框架规范的安全合规分析报告。

   报告内容覆盖：
   - 漏洞概览（严重性/类型/影响范围）
   - 自动化修复执行记录（补丁迭代过程、验证结论）
   - 合规框架映射（CWE/OWASP Top 10 关联）
   - 短期/中期/长期修复建议
   - 量化风险评分与处置 SLA 建议
===================================================================================
"""

import time
import asyncio
from langchain_core.messages import AIMessage
from cve_pipeline.state import CVETriageState
from cve_pipeline.llm_client import CVELLMClient, LLMRequestError

_REPORTER_SYSTEM_PROMPT = """你是一名 ISO 27001 / NIST Cybersecurity Framework 认证的安全合规顾问。
你的任务是根据 CVE 漏洞分诊与自动修复的完整执行记录，生成一份标准化的安全合规分析报告。

报告格式要求（使用 Markdown）：
# 安全漏洞分析合规报告

## 一、漏洞概览
[填写漏洞基本信息]

## 二、严重性评估
[CVSS 评分与风险分级说明]

## 三、自动化修复执行记录
[Pipeline 执行过程摘要]

## 四、合规框架映射
[CWE 编号 + OWASP Top 10 分类 + NIST CSF 控制项]

## 五、修复建议（优先级排序）
[分短期/中期/长期三个维度]

## 六、处置 SLA 与后续行动
[基于严重性给出明确的 SLA 要求和下一步行动清单]

报告必须专业、简洁，使用安全领域标准术语。"""


async def _async_compliance_report(state: CVETriageState) -> dict:
    """异步执行合规报告生成的核心逻辑。"""
    node_start_ts = time.time()
    client = CVELLMClient()

    severity = state.get("severity", "UNKNOWN")
    cve_id = state.get("cve_id", "UNKNOWN")
    vulnerability_type = state.get("vulnerability_type", "Unknown")
    affected_component = state.get("affected_component", "Unknown")
    risk_score = state.get("risk_score", 0.0)
    remediation_strategies = state.get("remediation_strategies", [])
    patch_retry_count = state.get("patch_retry_count", 0)
    validation_verdict = state.get("validation_verdict", "PENDING")
    tenant_id = state.get("tenant_id", "UNKNOWN")
    request_trace_id = state.get("request_trace_id", "N/A")
    total_tokens_so_far = state.get("total_llm_tokens", 0)
    node_latency_log = state.get("node_latency_log", [])
    raw_input = state.get("raw_input", "")

    # 统计 Pipeline 执行摘要
    executed_nodes = [entry.get("node", "unknown") for entry in node_latency_log]
    total_latency_ms = sum(entry.get("latency_ms", 0) for entry in node_latency_log)

    strategies_text = "\n".join(f"  - {s}" for s in remediation_strategies[:3])

    user_prompt = f"""请基于以下 CVE 漏洞分诊与自动修复 Pipeline 执行记录，生成完整的安全合规报告：

## Pipeline 执行摘要
- 租户 ID: {tenant_id}
- 请求 TraceID: {request_trace_id}
- 总执行节点数: {len(executed_nodes)} 个
- 总执行延迟: {total_latency_ms:.1f}ms
- 累计 LLM Token 消耗: {total_tokens_so_far} tokens

## 漏洞信息
- 原始描述: {raw_input[:200]}...
- 严重性等级: {severity} (CVSS {risk_score:.1f})
- 漏洞类型: {vulnerability_type}
- 受影响组件: {affected_component}
- CVE 编号: {cve_id}

## 自动化修复结果
- 补丁生成迭代次数: {patch_retry_count} 轮
- 最终验证结论: {validation_verdict}
- 推荐修复策略:
{strategies_text}

请生成完整的 Markdown 格式合规报告。"""

    report_text = ""
    tokens_used = 0

    try:
        report_text, tokens_used = await client.generate(
            system_prompt=_REPORTER_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.3,
            max_tokens=2000,
        )
    except LLMRequestError as e:
        report_text = (
            f"# 安全漏洞分析合规报告（降级版本）\n\n"
            f"**注意**：LLM 报告生成服务暂时不可用（{e}），以下为自动汇总的基础信息：\n\n"
            f"- 严重性：{severity} | CVE：{cve_id} | 类型：{vulnerability_type}\n"
            f"- 受影响组件：{affected_component} | CVSS：{risk_score:.1f}\n"
            f"- 修复验证：{validation_verdict}（{patch_retry_count} 轮迭代）\n"
            f"- 修复策略：{'; '.join(remediation_strategies[:2])}\n"
        )

    latency_ms = round((time.time() - node_start_ts) * 1000, 2)

    status_msg = (
        f"[合规报告签发节点 📋 | TraceID: {request_trace_id}] "
        f"报告签发完成 → 报告长度: {len(report_text)} 字符 | "
        f"耗时: {latency_ms}ms | Pipeline 总延迟: {total_latency_ms + latency_ms:.1f}ms"
    )

    return {
        "compliance_report": report_text,
        "messages": [AIMessage(content=status_msg)],
        "total_llm_tokens": tokens_used,
        "node_latency_log": [{
            "node": "compliance_reporter",
            "latency_ms": latency_ms,
            "tokens_used": tokens_used,
            "report_length": len(report_text),
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


def compliance_reporter_node(state: CVETriageState) -> dict:
    """LLM 合规报告签发节点（同步入口，线程安全防 Event Loop 冲突）。

    Args:
        state: 当前全局 CVETriageState 快照。

    Returns:
        包含 compliance_report 及可观测字段的增量更新字典。
    """
    return _run_async_in_thread(_async_compliance_report, state)
