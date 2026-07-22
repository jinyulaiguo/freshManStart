"""
节点 3/8：CVE 知识库检索节点

===================================================================================
模块设计方案 (Architectural Design)
===================================================================================
设计意图：
   本节点基于分诊结果（漏洞类型、受影响组件、严重性），调用 LLM 模拟知识库检索，
   返回相关 CVE 条目与修复策略列表。在生产场景中，此节点应集成 NVD API / OSV.dev
   / Qdrant 向量召回；在教学场景中通过 LLM 基于其训练知识生成真实感强的 CVE 条目。

节点接口：
   - 真实 LLM API 调用（JSON Mode）
   - 输入：severity, vulnerability_type, affected_component, cve_id
   - 输出更新字段：
       retrieved_cve_entries, remediation_strategies
       messages, total_llm_tokens, node_latency_log
===================================================================================
"""

import time
import asyncio
from langchain_core.messages import AIMessage
from cve_pipeline.state import CVETriageState
from cve_pipeline.llm_client import CVELLMClient, LLMParseError, LLMRequestError

_RETRIEVER_SYSTEM_PROMPT = """你是一名 CVE 漏洞知识库专家，拥有 NVD、MITRE、OSV.dev 的完整知识。
用户将提交漏洞分诊结果，你需要检索并返回相关 CVE 条目与修复策略。

请严格按照以下 JSON 格式输出，不得包含任何 Markdown 代码块：
{
  "retrieved_cve_entries": [
    {
      "cve_id": "CVE-XXXX-XXXXX",
      "description": "漏洞简述（1-2句话）",
      "cvss_score": 7.5,
      "cvss_vector": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N",
      "affected_versions": "受影响版本范围",
      "patch_available": true,
      "patch_reference": "修复补丁或 commit 链接"
    }
  ],
  "remediation_strategies": [
    "修复策略1（最高优先级，可立即执行）",
    "修复策略2（中期加固方案）",
    "修复策略3（长期架构改进建议）"
  ]
}

要求：
- 返回 2-3 个最相关的真实 CVE 条目
- 修复策略按优先级排序，最多3条，每条需具体可操作"""


async def _async_cve_retrieve(state: CVETriageState) -> dict:
    """异步执行 CVE 知识库检索的核心逻辑。"""
    node_start_ts = time.time()
    client = CVELLMClient()

    severity = state.get("severity", "MEDIUM")
    vuln_type = state.get("vulnerability_type", "Unknown")
    component = state.get("affected_component", "Unknown")
    cve_id = state.get("cve_id", "UNKNOWN")
    request_trace_id = state.get("request_trace_id", "N/A")

    user_prompt = f"""请检索以下漏洞场景的相关 CVE 条目与修复策略：

- 严重性等级: {severity}
- 漏洞类型: {vuln_type}
- 受影响组件: {component}
- 已知 CVE 编号（参考）: {cve_id}

请返回与上述场景最相关的真实 CVE 条目（基于 NVD/OSV.dev 知识），以及按优先级排序的修复策略。"""

    # 降级默认值
    retrieved_entries: list[dict] = []
    remediation_strategies: list[str] = [
        f"立即为受影响的 {component} 组件应用官方安全补丁",
        f"针对 {vuln_type} 漏洞类型实施输入验证与输出编码防御",
        "启用 Web 应用防火墙（WAF）规则拦截已知攻击向量",
    ]
    tokens_used = 0

    try:
        parsed, tokens_used = await client.classify(
            system_prompt=_RETRIEVER_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.2,
            max_tokens=1200,
        )
        if isinstance(parsed, dict):
            entries = parsed.get("retrieved_cve_entries", [])
            if isinstance(entries, list) and entries:
                retrieved_entries = entries
            strategies = parsed.get("remediation_strategies", [])
            if isinstance(strategies, list) and strategies:
                remediation_strategies = strategies

    except (LLMParseError, LLMRequestError, KeyError, TypeError) as e:
        # 降级：保留上面设置的默认策略，节点不中断 Pipeline
        pass

    latency_ms = round((time.time() - node_start_ts) * 1000, 2)

    status_msg = (
        f"[CVE 知识库检索节点 | TraceID: {request_trace_id}] "
        f"检索完成 → 命中 {len(retrieved_entries)} 条相关 CVE | "
        f"生成 {len(remediation_strategies)} 条修复策略 | 耗时: {latency_ms}ms\n"
        f"Top 修复策略: {remediation_strategies[0] if remediation_strategies else 'N/A'}"
    )

    return {
        "retrieved_cve_entries": retrieved_entries,
        "remediation_strategies": remediation_strategies,
        "messages": [AIMessage(content=status_msg)],
        "total_llm_tokens": tokens_used,
        "node_latency_log": [{
            "node": "cve_knowledge_retriever",
            "latency_ms": latency_ms,
            "tokens_used": tokens_used,
            "entries_found": len(retrieved_entries),
            "strategies_count": len(remediation_strategies),
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


def cve_retriever_node(state: CVETriageState) -> dict:
    """CVE 知识库检索节点（同步入口，线程安全防 Event Loop 冲突）。

    Args:
        state: 当前全局 CVETriageState 快照。

    Returns:
        包含 retrieved_cve_entries/remediation_strategies 及可观测字段的增量更新字典。
    """
    return _run_async_in_thread(_async_cve_retrieve, state)
