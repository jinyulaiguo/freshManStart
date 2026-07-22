"""
节点 1/8：输入净化与 Prompt 注入检测节点

===================================================================================
模块设计方案 (Architectural Design)
===================================================================================
设计意图：
   本节点是整个 Pipeline 的第一道安全防线。在任何 LLM 调用之前，对用户提交的
   原始文本执行静态规则检测，拦截以下攻击向量：
   1. Prompt 注入模式：如 "ignore previous instructions"、"act as DAN"、
      "system: ..." 等试图劫持 LLM 系统角色的注入语句。
   2. 恶意指令关键词：如 DROP TABLE、rm -rf 等危险系统命令混入。
   3. 特殊控制字符：如 <|endoftext|>、[INST]、<<SYS>> 等 LLM Token 边界符。

节点接口：
   - 输入：state["raw_input"] (str)
   - 输出更新字段：
       is_input_safe (bool)：是否通过安全检测。
       injection_detection_report (str)：检测详细报告。
       messages (list)：追加检测结论 AIMessage。
       node_latency_log (list)：追加本节点执行延迟日志。

设计决策：
   - 使用纯静态正则规则，不调用 LLM（确保安全门槛在 LLM 调用之前执行）。
   - 规则分层：高置信度规则（正则 Pattern）优先，逐层降低置信度阈值。
   - 检测发现时立即短路（fail-fast），不继续执行后续规则节省开销。
===================================================================================
"""

import re
import time
from langchain_core.messages import AIMessage
from cve_pipeline.state import CVETriageState


# =============================================================================
# 安全检测规则库
# =============================================================================

# Prompt 注入攻击模式（正则，忽略大小写）
_INJECTION_PATTERNS: list[tuple[str, str]] = [
    # 指令覆盖类
    (r"ignore\s+(previous|all|above)\s+(instructions?|prompts?|rules?)", "指令覆盖攻击：试图忽略系统 Prompt"),
    (r"forget\s+(everything|all)\s+(above|before|previous)", "历史清除攻击：试图清除上下文记忆"),
    (r"disregard\s+(your|all)\s+(instructions?|rules?|training)", "规则绕过攻击：试图绕过训练规则"),
    # 角色劫持类
    (r"\bact\s+as\s+(DAN|an?\s+AI\s+without|a\s+jailbreak)", "角色劫持攻击：DAN/越狱模式注入"),
    (r"you\s+are\s+now\s+(DAN|an?\s+unrestricted|a\s+evil)", "身份替换攻击：试图替换 AI 身份"),
    (r"pretend\s+(you|to\s+be)\s+(have\s+no\s+restrictions?|evil|malicious)", "伪装攻击：无限制模式"),
    # 系统角色注入类
    (r"(?:^|\n)\s*system\s*:\s*", "系统角色注入：伪造 system 消息"),
    (r"(?:^|\n)\s*\[system\]", "系统块注入：[system] 边界注入"),
    (r"<<SYS>>|<\|system\|>|\[INST\]|<\|endoftext\|>|\[/INST\]", "Token 边界攻击：LLM 特殊控制 Token"),
    # 数据泄露类
    (r"(print|reveal|show|output|tell me)\s+(your\s+)?(system\s+prompt|instructions?|training\s+data)", "信息泄露攻击：试图提取系统 Prompt"),
    (r"what\s+(are|were)\s+your\s+(original\s+)?(instructions?|rules?|constraints?)", "规则探测攻击：试图探测系统约束"),
]

# 危险系统命令模式
_DANGEROUS_COMMAND_PATTERNS: list[tuple[str, str]] = [
    (r"\bDROP\s+TABLE\b", "SQL 注入尝试：DROP TABLE 命令"),
    (r"\bDELETE\s+FROM\b.*\bWHERE\b", "SQL 注入尝试：DELETE 条件删除命令"),
    (r"\bUNION\s+SELECT\b", "SQL 注入尝试：UNION SELECT 联合查询"),
    (r"rm\s+-rf\s+[/~]", "系统命令注入：rm -rf 递归删除"),
    (r"sudo\s+(?:rm|dd|mkfs|chmod\s+777)", "提权命令注入：sudo 危险操作"),
    (r"curl\s+.*\|\s*(?:bash|sh|python)", "远程代码执行：curl pipe bash"),
    (r"__import__\s*\(\s*['\"]os['\"]", "Python 代码注入：os 模块导入"),
    (r"exec\s*\(\s*(?:compile|__import__|eval)", "Python 代码注入：动态代码执行"),
]

# 内容边界字符白名单（CVE 描述中合法的特殊符号）
_LEGITIMATE_SYMBOLS_PATTERN = re.compile(r"^[\w\s\-.,;:()\[\]{}'\"\/\\@#$%^&*+=<>|`~\n]+$", re.UNICODE)


def _run_pattern_checks(
    text: str,
    patterns: list[tuple[str, str]],
    pattern_flags: int = re.IGNORECASE | re.MULTILINE,
) -> list[str]:
    """对文本执行一组正则模式检测，返回所有命中的威胁描述列表。

    Args:
        text:          待检测的输入文本。
        patterns:      (regex_pattern, threat_description) 元组列表。
        pattern_flags: 正则编译标志位。

    Returns:
        命中的威胁描述列表（空列表表示未检测到威胁）。
    """
    threats: list[str] = []
    for pattern, description in patterns:
        if re.search(pattern, text, flags=pattern_flags):
            threats.append(description)
    return threats


def input_sanitizer_node(state: CVETriageState) -> dict:
    """输入净化与 Prompt 注入检测节点。

    对 state["raw_input"] 执行多层安全规则检测。检测到威胁时将 is_input_safe
    设置为 False，并生成包含具体威胁类型列表的检测报告，后续路由函数将据此
    将流量导向 block_response 节点终止处理。

    Args:
        state: 当前全局 CVETriageState 快照。

    Returns:
        包含以下字段的增量更新字典：
        - is_input_safe (bool)
        - injection_detection_report (str)
        - messages (list[AIMessage])
        - node_latency_log (list[dict])
    """
    node_start_ts = time.time()
    raw_input = state.get("raw_input", "")
    request_trace_id = state.get("request_trace_id", "N/A")

    detected_threats: list[str] = []

    # ── 规则层 1: Prompt 注入模式检测 ──
    threats_1 = _run_pattern_checks(raw_input, _INJECTION_PATTERNS)
    detected_threats.extend(threats_1)

    # ── 规则层 2: 危险系统命令检测 ──
    threats_2 = _run_pattern_checks(raw_input, _DANGEROUS_COMMAND_PATTERNS)
    detected_threats.extend(threats_2)

    # ── 规则层 3: 文本长度防爆（防止超长输入撑爆 Context Window） ──
    if len(raw_input) > 8000:
        detected_threats.append(f"输入长度超限：{len(raw_input)} 字符 > 8000 上限，疑似数据填充攻击")

    is_safe = len(detected_threats) == 0

    # 构建检测报告
    if is_safe:
        report = (
            f"[InputSanitizer | TraceID: {request_trace_id}] "
            f"输入安全检测通过。已执行 {len(_INJECTION_PATTERNS)} 条注入规则 + "
            f"{len(_DANGEROUS_COMMAND_PATTERNS)} 条危险命令规则，均未命中。"
        )
        status_msg = f"[输入净化节点 ✅] 输入文本安全，长度 {len(raw_input)} 字符，流转至严重性分诊。"
    else:
        threat_list_str = "\n  • ".join(detected_threats)
        report = (
            f"[InputSanitizer | TraceID: {request_trace_id}] "
            f"⚠️ 检测到 {len(detected_threats)} 项安全威胁：\n  • {threat_list_str}\n"
            f"原始输入已拦截，Pipeline 终止。"
        )
        status_msg = (
            f"[输入净化节点 🚫] 检测到 {len(detected_threats)} 项威胁，"
            f"路由至 block_response 终止处理。"
        )

    latency_ms = round((time.time() - node_start_ts) * 1000, 2)

    return {
        "is_input_safe": is_safe,
        "injection_detection_report": report,
        "messages": [AIMessage(content=status_msg)],
        # append_reducer 会将此条目追加到全局日志列表，而非覆盖
        "node_latency_log": [{
            "node": "input_sanitizer",
            "latency_ms": latency_ms,
            "tokens_used": 0,
            "is_safe": is_safe,
            "threats_found": len(detected_threats),
        }],
    }
