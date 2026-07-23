"""SQL 双重风控评估节点 (规则初筛 + 真实 LLM 语义研判 - 强效防御性空安全)

设计方案与架构说明：
----------------------------------------------------------------
本节点负责对生成/编辑后的 SQL 语句进行多维度安全研判，决定控制流是否触发表单挂起 (interrupt_before)。
1. 强效空安全防护：校验 `sql` 是否为 `None` 或空字符串，防止 `NoneType` 引起 `AttributeError` 崩溃。
2. 审批状态重置：每次进行新一轮风控研判时，重置 `approval_status="pending"`，防止上一轮残留的 "rejected" 误导路由。
3. Layer 1 规则初筛：正则匹配 DML/DDL 敏感关键字。
4. Layer 2 真实 LLM 语义分析：剥离思考链 <think> 标签，强效提取评级。
5. 风险熔炼逻辑：取最高风险等级 (`blocked > sensitive > safe`)。

数据流：
--------
Input (generated_sql) -> 重置 approval_status -> 双重研判 -> 熔炼 risk_level -> 写入 state
"""

import os
import sys
import re
import asyncio
from typing import Dict, Any, Tuple

# 动态将工作区根目录添加到 sys.path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../"))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from weekly.w04_prompt_and_http.utils import LLMClient
from weekly.w11_langgraph_advanced.day77.state.main_state import SQLAgentState

llm_client = LLMClient()

RISK_RANK = {"safe": 1, "sensitive": 2, "blocked": 3}
RANK_TO_RISK = {1: "safe", 2: "sensitive", 3: "blocked"}


def evaluate_rule_layer(sql: str) -> str:
    """Layer 1: 静态规则引擎正则初筛 (强防护 None)。"""
    if not sql:
        return "safe"

    sql_upper = str(sql).upper().strip()

    # 高危极险指令直接 Block
    if re.search(r"\b(DROP|TRUNCATE|GRANT|REVOKE)\b", sql_upper):
        return "blocked"

    # 敏感修改指令挂起审批
    if re.search(r"\b(UPDATE|DELETE|INSERT|ALTER|CREATE)\b", sql_upper):
        return "sensitive"

    # SELECT 查询默认放行
    return "safe"


async def evaluate_llm_layer(sql: str, rule_risk: str) -> Tuple[str, str]:
    """Layer 2: 真实 LLM 语义风险分析 (强防护 None)。"""
    if not sql:
        return "safe", "[LLM 语义分析]: SQL 为空，默认放行。"

    prompt = f"""你是一位数据库安全审计专家。请深度评估以下 PostgreSQL SQL 语句的语义安全风险：

SQL: `{sql}`

请分析：
1. 语法与语义是否存在危害（例如：UPDATE/DELETE 缺少 WHERE 条件导致全表影响；是否存在 '1'='1' 注入等）。
2. 判定该 SQL 的风险等级，仅能选择以下三者之一：
   - safe: 纯 SELECT 只读查询或带正常条件的只读，无数据破裂风险。
   - sensitive: 包含 UPDATE / DELETE / INSERT / ALTER 等改写/写操作，影响单条/多条，需安全员审核放行。
   - blocked: 高危危险操作（如全表无条件 DELETE/UPDATE、DROP TABLE、数据库注入等），物理强阻断。

【强约束输出格式】：
首行必须且仅输出以下评级单词之一 (全小写)：
safe 或 sensitive 或 blocked

第二行开始输出 1-2 句简洁的审计理由。
"""

    messages = [
        {"role": "system", "content": "你是一位苛刻且精准的数据库安全审计专家。"},
        {"role": "user", "content": prompt}
    ]

    try:
        raw = await llm_client.request_llm(messages, temperature=0.0, max_tokens=250)
        # 剥离思考链
        cleaned = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL).strip()
        lines = [line.strip() for line in cleaned.split('\n') if line.strip()]

        if not lines:
            return rule_risk, f"[LLM 语义分析]: 评估响应为空，降级为规则层 '{rule_risk}'"

        first_line = lines[0].lower()
        analysis_text = "\n".join(lines[1:]) if len(lines) > 1 else cleaned

        if "blocked" in first_line:
            llm_risk = "blocked"
        elif "sensitive" in first_line:
            llm_risk = "sensitive"
        elif "safe" in first_line:
            llm_risk = "safe"
        else:
            # 兜底遵循规则层判定
            llm_risk = rule_risk

        return llm_risk, f"[LLM 语义分析]: {analysis_text}"
    except Exception as e:
        return rule_risk, f"[LLM 评估异常]: 无法进行语义分析，降级遵循规则层 {rule_risk} ({e})"


async def risk_assessment_node(state: SQLAgentState) -> Dict[str, Any]:
    """主图节点：规则 + 真实 LLM 双重风险研判 (重置 approval_status 为 pending)。"""
    sql = state.get("generated_sql") or ""
    print(f"\n[Node: Risk Assessment] 正在执行 SQL 双重风控研判... SQL: '{sql}'")

    # 1. Layer 1 静态规则初筛
    rule_risk = evaluate_rule_layer(sql)

    # 2. Layer 2 真实 LLM 语义评估
    llm_risk, risk_analysis = await evaluate_llm_layer(sql, rule_risk)

    # 3. 熔炼最终风险等级 (取二者最高)
    final_rank = max(RISK_RANK.get(rule_risk, 1), RISK_RANK.get(llm_risk, 1))
    final_risk = RANK_TO_RISK[final_rank]

    full_analysis = f"规则层判定: '{rule_risk}' | LLM层判定: '{llm_risk}' => 最终熔炼风险等级: '{final_risk}'\n{risk_analysis}"
    print(f"  🛡️ 风控研判完成! {full_analysis}")

    return {
        "risk_level": final_risk,
        "risk_analysis": full_analysis,
        "approval_status": "pending",  # 强置重置防止残留
        "audit_trail": [f"Risk Assessment: risk_level='{final_risk}' (rule='{rule_risk}', llm='{llm_risk}')"]
    }
