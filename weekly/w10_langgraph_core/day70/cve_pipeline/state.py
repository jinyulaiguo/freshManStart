"""
CVE Triage Pipeline — 全局状态契约与自定义 Reducer

===================================================================================
模块设计方案 (Architectural Design)
===================================================================================
1. 设计意图：
   本模块为整个 CVE 分诊 Pipeline 定义唯一的全局共享状态快照 `CVETriageState`。
   遵循 LangGraph 的 TypedDict 强类型契约规范，将所有节点可读写的状态字段集中
   声明，并通过 `Annotated[T, reducer_fn]` 语法绑定自定义归约器，控制并发写入时
   的合并策略。

2. 自定义 Reducer 设计：
   - `token_sum_reducer`：各节点向状态写入本次调用的 Token 增量，引擎在合并时
     自动累加，用于实时跟踪全链路 LLM Token 消耗（支持 Token 预算熔断）。
   - `append_reducer`：各节点写入包含 {node, latency_ms, tokens} 的字典，引擎
     在合并时追加（而非覆盖），保留完整的节点执行时序日志，用于 Telemetry 看板。

3. 状态字段分层：
   - 安全层：`is_input_safe`, `injection_detection_report`
   - 分诊层：`severity`, `cve_id`, `affected_component`, `vulnerability_type`
   - 知识检索层：`retrieved_cve_entries`, `remediation_strategies`
   - 补丁生成与验证层：`generated_patch_code`, `patch_retry_count`,
                       `validation_verdict`, `validation_findings`
   - 合规报告层：`compliance_report`, `risk_score`
   - 多租户与审计追踪：`tenant_id`, `request_trace_id`
   - 可观测与熔断：`total_llm_tokens`, `node_latency_log`,
                    `is_circuit_broken`, `degradation_payload`
===================================================================================
"""

from typing import TypedDict, Annotated
from langchain_core.messages import BaseMessage
from langgraph.graph import add_messages


# =============================================================================
# 自定义 Reducer 函数定义
# =============================================================================

def token_sum_reducer(left: int | None, right: int | None) -> int:
    """Token 消耗累加归约器。

    LangGraph 在合并状态时调用此函数：left 为当前全局累计值，right 为节点本次
    写入的增量值。两者相加，确保 total_llm_tokens 字段跨节点正确累加。

    Args:
        left: 当前全局状态中的 Token 累计数。
        right: 节点本次 LLM 调用消耗的 Token 增量。

    Returns:
        两者之和，作为新的全局累计值。
    """
    return (left or 0) + (right or 0)


def append_reducer(
    left: list[dict] | None,
    right: list[dict] | None
) -> list[dict]:
    """节点执行日志追加归约器。

    LangGraph 在合并状态时调用此函数：left 为当前全局日志列表，right 为节点本次
    写入的新日志条目列表。直接拼接，保留完整的时序执行记录。

    Args:
        left: 当前全局状态中的执行日志列表。
        right: 节点本次新增的日志条目列表。

    Returns:
        拼接后的完整日志列表。
    """
    left_list = left or []
    right_list = right or []
    return left_list + right_list


# =============================================================================
# 全局状态契约
# =============================================================================

class CVETriageState(TypedDict):
    """企业级 CVE 漏洞分诊与自动修复 Pipeline 全局状态契约。

    该 TypedDict 是整个 LangGraph 图的唯一状态容器。所有节点只能读取此对象的字段，
    并通过返回字典的子集来触发增量更新。LangGraph 引擎负责调用对应字段绑定的
    Reducer 函数进行合并。

    字段说明：
        # ── 输入层 ──
        messages:               对话消息链（HumanMessage + AIMessage），
                                使用内置 add_messages 归约器实现 append + ID 去重。
        raw_input:              用户提交的原始漏洞描述文本。

        # ── 安全净化层 ──
        is_input_safe:          输入安全检测结果。False 时触发 block_response 节点。
        injection_detection_report: Prompt 注入检测的详细报告文本。

        # ── LLM 严重性分诊层 ──
        severity:               漏洞严重等级，枚举值: CRITICAL / HIGH / MEDIUM / LOW。
        cve_id:                 LLM 识别到的关联 CVE 编号（如 CVE-2026-12345）。
        affected_component:     受影响的系统组件或模块名称。
        vulnerability_type:     漏洞类型（SQLi / XSS / RCE / SSRF / LFI / ...）。

        # ── CVE 知识检索层 ──
        retrieved_cve_entries:  从知识库检索到的相关 CVE 条目列表，每项为包含
                                {cve_id, description, cvss_score, remediation} 的字典。
        remediation_strategies: LLM 从检索结果中提炼的修复策略列表（有序，最优先在前）。

        # ── 补丁生成与验证层 ──
        generated_patch_code:   LLM 生成的 Python 安全补丁代码字符串。
        patch_retry_count:      补丁重试轮数计数器，用于控制反馈环路：当该值 >= 2
                                时触发人工升舱而非继续重试。
        validation_verdict:     静态分析验证结论，枚举值: PASS / FAIL / PARTIAL。
        validation_findings:    静态分析器发现的具体问题列表（用于下一轮补丁修正）。

        # ── 合规报告层 ──
        compliance_report:      LLM 签发的最终合规分析报告（Markdown 格式）。
        risk_score:             量化风险评分，范围 0.0（无风险）~ 10.0（严重风险）。

        # ── 多租户与链路追踪 ──
        tenant_id:              多租户标识符，在 thread_id 中作为前缀使用。
        request_trace_id:       请求级链路追踪 ID（UUID），用于跨节点日志关联。

        # ── 可观测性与熔断保护 ──
        total_llm_tokens:       全链路 LLM Token 消耗累计值，使用 token_sum_reducer
                                跨节点累加，支持 Token 预算熔断维度检测。
        node_latency_log:       各节点执行延迟与 Token 日志，使用 append_reducer
                                追加，用于 Telemetry 仪表盘时序图渲染。
        is_circuit_broken:      熔断激活标志，True 时表示系统已触发降级保护。
        degradation_payload:    结构化降级诊断数据，包含熔断原因、触发维度、
                                当前步数、Token 消耗、状态指纹历史等。
    """

    # ── 输入层 ──
    messages: Annotated[list[BaseMessage], add_messages]
    raw_input: str

    # ── 安全净化层 ──
    is_input_safe: bool
    injection_detection_report: str

    # ── LLM 严重性分诊层 ──
    severity: str
    cve_id: str
    affected_component: str
    vulnerability_type: str

    # ── CVE 知识检索层 ──
    retrieved_cve_entries: list[dict]
    remediation_strategies: list[str]

    # ── 补丁生成与验证层 ──
    generated_patch_code: str
    patch_retry_count: int
    validation_verdict: str
    validation_findings: list[str]

    # ── 合规报告层 ──
    compliance_report: str
    risk_score: float

    # ── 多租户与链路追踪 ──
    tenant_id: str
    request_trace_id: str

    # ── 可观测性与熔断保护（自定义 Reducer） ──
    total_llm_tokens: Annotated[int, token_sum_reducer]
    node_latency_log: Annotated[list[dict], append_reducer]
    is_circuit_broken: bool
    degradation_payload: dict


def make_initial_state(
    raw_input: str,
    tenant_id: str,
    request_trace_id: str,
) -> CVETriageState:
    """构建初始化的空白 State 快照工厂函数。

    为图的首次 invoke 调用提供类型安全的初始化状态，确保所有字段均有默认值，
    防止节点在读取未初始化字段时抛出 KeyError。

    Args:
        raw_input:        用户提交的原始漏洞描述文本。
        tenant_id:        多租户标识符。
        request_trace_id: 请求链路追踪 ID。

    Returns:
        完整的 CVETriageState 初始快照。
    """
    from langchain_core.messages import HumanMessage
    return CVETriageState(
        messages=[HumanMessage(content=raw_input)],
        raw_input=raw_input,
        is_input_safe=True,
        injection_detection_report="",
        severity="UNKNOWN",
        cve_id="UNKNOWN",
        affected_component="UNKNOWN",
        vulnerability_type="UNKNOWN",
        retrieved_cve_entries=[],
        remediation_strategies=[],
        generated_patch_code="",
        patch_retry_count=0,
        validation_verdict="PENDING",
        validation_findings=[],
        compliance_report="",
        risk_score=0.0,
        tenant_id=tenant_id,
        request_trace_id=request_trace_id,
        total_llm_tokens=0,
        node_latency_log=[],
        is_circuit_broken=False,
        degradation_payload={},
    )
