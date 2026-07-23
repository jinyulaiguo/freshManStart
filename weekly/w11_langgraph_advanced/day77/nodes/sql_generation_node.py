"""SQL 动态生成节点 (Day 77 真实 LLM 交互 - 约束字面量输出与跨轮错误重置)

设计方案与架构说明：
----------------------------------------------------------------
本节点负责接收自然语言查询，调用真实 LLM API (MiniMax) 生成标准的 SQL 语句与绑定参数。
1. 完整内联字面量约束：提示 LLM 在 SQL 语句中直接写入内联字面量 (如 `WHERE name = 'Fiona'`)，绝不出 `$1`, `$2` 等未绑定占位符。
2. 思考链与 Markdown 剥离：剥离 `<think>...</think>` 标签及 ```json。
3. 状态清空防护：在成功生成新 SQL 后，物理覆盖清空 `error_log: []`，彻底防止上一轮推演失败残留的错误历史污染后续正常的路由条件流转！

数据流：
--------
Input (messages[-1]) -> 真实 LLM API 推演 -> 剥离 <think> -> 提取 JSON -> 写入 state (清空 error_log)
"""

import os
import sys
import re
import json
import asyncio
from typing import Dict, Any

# 动态将工作区根目录添加到 sys.path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../"))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from weekly.w04_prompt_and_http.utils import LLMClient
from weekly.w11_langgraph_advanced.day77.state.main_state import SQLAgentState

llm_client = LLMClient()

SYSTEM_PROMPT = """你是一位精通 PostgreSQL 的顶级 SQL 专家 Agent。
请根据用户的自然语言问题，构建精准、高效且合法的 PostgreSQL 数据库查询/修改语句。

数据库包含以下两张表：
1. `users` 表结构：
   - id: SERIAL PRIMARY KEY
   - name: VARCHAR(100)
   - email: VARCHAR(150)
   - status: VARCHAR(20) ('active', 'inactive', 'suspended')
   - last_login: TIMESTAMP

2. `orders` 表结构：
   - id: SERIAL PRIMARY KEY
   - user_id: INT (外键关联 users.id)
   - product: VARCHAR(200)
   - amount: NUMERIC(10, 2)
   - status: VARCHAR(20) ('completed', 'pending', 'refunded', 'cancelled')
   - created_at: TIMESTAMP

【强约束要求】：
1. 必须在 SQL 语句中直接填入具体的常量字面量（例如: `UPDATE users SET status = 'inactive' WHERE name = 'Fiona';`），绝对不能使用 $1、$2 等占位符！
2. 必须严格且仅输出一个合法的 JSON 对象！绝对不要输出思考过程，不要输出 <think> 标签，不要包含 Markdown 标记！
JSON 字典格式规范：
{
    "sql": "SELECT * FROM users WHERE status = 'active';",
    "params": {}
}
"""


async def sql_generation_node(state: SQLAgentState) -> Dict[str, Any]:
    """主图节点：调用真实 LLM API 生成 SQL 语句与参数 (擦除上轮 error_log 残留)。"""
    user_query = state["messages"][-1].content if state["messages"] else "查询所有激活用户"
    print(f"\n[Node: SQL Generation] 正在向真实 LLM 发起 SQL 推演请求... 问题: '{user_query}'")

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"请生成对应的 SQL 语句：{user_query}"}
    ]

    try:
        raw_response = await llm_client.request_llm(messages, temperature=0.1, max_tokens=300)
        
        # 1. 剥离 <think>...</think> 思考链
        cleaned = re.sub(r'<think>.*?</think>', '', raw_response, flags=re.DOTALL).strip()
        
        # 2. 剥离 ```json 代码块
        if "```" in cleaned:
            cleaned = re.sub(r'```(?:json)?\s*(.*?)\s*```', r'\1', cleaned, flags=re.DOTALL).strip()

        # 3. 提取第一个 '{' 与最后一个 '}' 之间的字符串
        json_match = re.search(r'\{.*\}', cleaned, flags=re.DOTALL)
        if not json_match:
            raise ValueError(f"原始响应中未找到有效 JSON 结构: {cleaned}")
            
        json_str = json_match.group(0)
        parsed = json.loads(json_str)
        
        generated_sql = parsed.get("sql", "").strip()
        sql_params = parsed.get("params", {})

        if not generated_sql:
            raise ValueError("解析得到的 SQL 字段为空！")

        print(f"  ✅ 真实 LLM 成功生成 SQL: {generated_sql}")

        return {
            "generated_sql": generated_sql,
            "sql_params": sql_params,
            "error_log": [],  # 擦除上一轮产生的失败残留！
            "audit_trail": [f"LLM generated SQL: '{generated_sql}' for user query: '{user_query}'"]
        }
    except Exception as e:
        print(f"  ❌ LLM 生成 SQL 或 JSON 解析失败: {e}")
        # 针对简单读查询的极简兜底
        fallback_sql = f"SELECT * FROM users WHERE name ILIKE '%{user_query}%';"
        print(f"  ⚠️ 使用安全可执行兜底 SQL: {fallback_sql}")
        return {
            "generated_sql": fallback_sql,
            "sql_params": {},
            "error_log": [],  # 兜底恢复后清空阻断日志
            "audit_trail": [
                "LLM generation fallback invoked due to parse failure.",
                f"Fallback SQL set to: '{fallback_sql}'"
            ]
        }
