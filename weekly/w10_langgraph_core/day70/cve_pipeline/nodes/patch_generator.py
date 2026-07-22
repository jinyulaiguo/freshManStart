"""
节点 4/8：LLM 代码补丁生成节点

===================================================================================
模块设计方案 (Architectural Design)
===================================================================================
设计意图：
   本节点是 Pipeline 反馈环路的核心执行体。基于上游 CVE 知识检索结果和修复策略，
   调用 LLM 生成具体的 Python 安全补丁代码。

   反馈环路设计要点：
   - 首次生成（patch_retry_count == 0）：基于知识检索结果和修复策略生成补丁。
   - 重试生成（patch_retry_count > 0）：将上一轮 static_validator 的 validation_findings
     注入 Prompt，要求 LLM 针对具体问题进行定向修正。
   - patch_retry_count 在每次调用时递增，路由函数 R3 依据此值控制环路次数。

节点接口：
   - 真实 LLM API 调用（文本生成）
   - 输入：vulnerability_type, affected_component, remediation_strategies,
           patch_retry_count, validation_findings (重试时注入)
   - 输出更新字段：
       generated_patch_code, patch_retry_count (递增)
       messages, total_llm_tokens, node_latency_log
===================================================================================
"""

import time
import asyncio
from langchain_core.messages import AIMessage
from cve_pipeline.state import CVETriageState
from cve_pipeline.llm_client import CVELLMClient, LLMRequestError

_PATCH_SYSTEM_PROMPT = """你是一名专业的 Python 安全工程师，专精于安全漏洞修复与防御性编程。
你的任务是根据提供的漏洞信息和修复策略，生成一段高质量的 Python 安全补丁代码。

代码质量要求：
1. 使用参数化查询替代字符串拼接（针对 SQLi）
2. 使用 bleach/markupsafe 进行输出编码（针对 XSS）
3. 使用 subprocess 的列表形式避免 shell 注入
4. 对所有外部输入进行严格类型验证
5. 添加详细的类型注解（PEP 484）和 Docstring（PEP 257）
6. 包含完整的异常处理链

请直接输出 Python 代码，不要包含任何解释性文字或 Markdown 代码块标记（```）。"""


def _build_patch_prompt(
    vulnerability_type: str,
    affected_component: str,
    remediation_strategies: list[str],
    retry_count: int,
    validation_findings: list[str],
    raw_input: str,
) -> str:
    """根据是否为重试轮次，构建不同侧重点的补丁生成 Prompt。

    Args:
        vulnerability_type:     漏洞类型。
        affected_component:     受影响组件。
        remediation_strategies: 修复策略列表。
        retry_count:            当前重试轮次（0 表示首次生成）。
        validation_findings:    上一轮静态验证发现的问题列表。
        raw_input:              原始漏洞描述，提供业务上下文。

    Returns:
        构建好的用户 Prompt 字符串。
    """
    strategies_text = "\n".join(f"  {i+1}. {s}" for i, s in enumerate(remediation_strategies))

    base_context = f"""漏洞场景信息：
- 漏洞类型: {vulnerability_type}
- 受影响组件: {affected_component}
- 漏洞描述摘要: {raw_input[:300]}...

推荐修复策略（按优先级）：
{strategies_text}"""

    if retry_count == 0:
        return f"""{base_context}

请生成完整的 Python 安全补丁代码，包括：
1. 包含漏洞的原始代码示例（注释标注 # VULNERABLE）
2. 修复后的安全代码（注释标注 # SECURE）
3. 必要的辅助函数和验证逻辑
4. 简短的设计说明（以 Python 注释形式）"""
    else:
        findings_text = "\n".join(f"  - {f}" for f in validation_findings)
        return f"""{base_context}

⚠️ 这是第 {retry_count} 次修复迭代。上一版本补丁在静态分析中发现了以下问题，请针对这些问题进行定向修正：

静态分析发现的问题：
{findings_text}

请在上述问题的基础上重新生成修复后的完整 Python 补丁代码。确保所有上述问题均已修正。"""


async def _async_patch_generate(state: CVETriageState) -> dict:
    """异步执行代码补丁生成的核心逻辑。"""
    node_start_ts = time.time()
    client = CVELLMClient()

    vulnerability_type = state.get("vulnerability_type", "Unknown")
    affected_component = state.get("affected_component", "Unknown")
    remediation_strategies = state.get("remediation_strategies", [])
    current_retry_count = state.get("patch_retry_count", 0)
    validation_findings = state.get("validation_findings", [])
    raw_input = state.get("raw_input", "")
    request_trace_id = state.get("request_trace_id", "N/A")

    user_prompt = _build_patch_prompt(
        vulnerability_type=vulnerability_type,
        affected_component=affected_component,
        remediation_strategies=remediation_strategies,
        retry_count=current_retry_count,
        validation_findings=validation_findings,
        raw_input=raw_input,
    )

    generated_code = ""
    tokens_used = 0

    try:
        generated_code, tokens_used = await client.generate(
            system_prompt=_PATCH_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.5,
            max_tokens=2000,
        )
    except LLMRequestError as e:
        generated_code = f"# [补丁生成失败] LLM 请求异常: {e}\n# 请手动修复 {affected_component} 中的 {vulnerability_type} 漏洞"

    # 每次调用递增重试计数器（路由函数 R3 依据此值控制环路）
    new_retry_count = current_retry_count + 1

    # 计算当前补丁的 MD5 指纹（用于熔断引擎的震荡检测）
    patch_fingerprint = client.compute_text_fingerprint(generated_code)
    latency_ms = round((time.time() - node_start_ts) * 1000, 2)

    retry_label = "首次生成" if current_retry_count == 0 else f"第 {current_retry_count} 次重试修正"
    status_msg = (
        f"[代码补丁生成节点 | TraceID: {request_trace_id}] "
        f"{retry_label}完成 → 补丁代码 {len(generated_code)} 字符 | "
        f"指纹: {patch_fingerprint} | 耗时: {latency_ms}ms"
    )

    return {
        "generated_patch_code": generated_code,
        "patch_retry_count": new_retry_count,
        "messages": [AIMessage(content=status_msg)],
        "total_llm_tokens": tokens_used,
        "node_latency_log": [{
            "node": "code_patch_generator",
            "latency_ms": latency_ms,
            "tokens_used": tokens_used,
            "retry_round": current_retry_count,
            "patch_fingerprint": patch_fingerprint,
            "code_length": len(generated_code),
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


def patch_generator_node(state: CVETriageState) -> dict:
    """LLM 代码补丁生成节点（同步入口，线程安全防 Event Loop 冲突）。

    Args:
        state: 当前全局 CVETriageState 快照。

    Returns:
        包含 generated_patch_code/patch_retry_count 及可观测字段的增量更新字典。
    """
    return _run_async_in_thread(_async_patch_generate, state)
