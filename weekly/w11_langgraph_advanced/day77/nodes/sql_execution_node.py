"""PostgreSQL SQL 真实执行节点 (Day 77 物理沙箱 - 空 SQL 强校验)

设计方案与架构说明：
----------------------------------------------------------------
本节点负责在通过风控/人工审批放行后，连接真实 PostgreSQL 沙箱数据库物理执行 SQL。
1. 空 SQL 强校验：防止 None 或空 SQL 传给 psycopg2 触发 can't execute an empty query 崩溃。
2. 物理数据库交互：使用 `database/init_db.py` 中的 `execute_query` 连接 Docker PG 数据库。
3. 可控异常注入点 (Fault Injection)：
   - 检查环境变量 `FORCE_SQL_ERROR`，若为 "1"，故意抛出模拟数据库连接中断异常，用于测试“时间旅行”故障恢复。
4. 容错与状态记录：
   - 执行成功将格式化行列表写入 `state.execution_result`。
   - 执行抛出异常捕获存入 `state.error_log`。

数据流：
--------
Input (generated_sql, sql_params) -> 校验非空 -> PG 执行 -> [execution_result] / [error_log]
"""

import os
import sys
from typing import Dict, Any

# 动态将工作区根目录添加到 sys.path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../"))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from weekly.w11_langgraph_advanced.day77.database.init_db import execute_query
from weekly.w11_langgraph_advanced.day77.state.main_state import SQLAgentState


async def sql_execution_node(state: SQLAgentState) -> Dict[str, Any]:
    """主图节点：在 PostgreSQL 物理沙箱中执行 SQL。"""
    sql = state.get("generated_sql")
    params = state.get("sql_params") or {}
    
    print(f"\n[Node: SQL Execution] 正在连接 Docker PostgreSQL 执行 SQL...")
    print(f"  -> 执行 SQL: {sql}")

    # 0. 校验 SQL 是否为空
    if not sql or not str(sql).strip():
        print("  ⚠️ SQL 语句为空，物理跳过 PostgreSQL 查询。")
        return {
            "execution_result": None,
            "error_log": ["PostgreSQL Execution Error: 待执行的 SQL 语句为空！"],
            "audit_trail": ["SQL Execution SKIPPED because sql query is empty."]
        }

    # 1. 检查故障注入开关 (测试 Time Travel 恢复场景)
    if os.getenv("FORCE_SQL_ERROR") == "1":
        print("  💥 [Fault Injection] 触发可控模拟故障: PostgreSQL connection pool exhausted!")
        return {
            "execution_result": None,
            "error_log": ["PostgreSQL execution error: Connection lost (simulated fault)"],
            "audit_trail": ["SQL Execution ABORTED due to simulated database connection fault."]
        }

    # 2. 物理执行 SQL
    try:
        results = execute_query(sql, tuple(params.values()) if params else None)
        print(f"  ✅ PostgreSQL 执行成功! 返回 {len(results)} 行数据/受影响行。")
        return {
            "execution_result": results,
            "audit_trail": [f"Successfully executed SQL in PostgreSQL. Returned {len(results)} records."]
        }
    except Exception as e:
        print(f"  ❌ PostgreSQL 执行崩溃: {e}")
        return {
            "execution_result": None,
            "error_log": [f"PostgreSQL Execution Error: {str(e)}"],
            "audit_trail": [f"SQL Execution FAILED with error: {str(e)}"]
        }
