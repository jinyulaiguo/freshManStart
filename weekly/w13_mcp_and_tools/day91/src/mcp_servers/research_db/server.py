import sqlglot
from sqlglot.errors import ParseError
from mcp.server.fastmcp import FastMCP, Context
from pydantic import BaseModel, Field
import psycopg
import sys
import os

# 插入 src 到环境变量以读取配置
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../")))
from src.config.settings import settings
from src.infrastructure.observability import get_logger

logger = get_logger("research_db_mcp")

mcp = FastMCP("research_db", dependencies=["mcp", "pydantic", "psycopg", "sqlglot"])

class QueryInput(BaseModel):
    sql_query: str = Field(..., description="标准的 PostgreSQL 查询语句。只允许 SELECT，严格禁止 DROP/UPDATE/DELETE 等 DML/DDL。")
    reasoning: str = Field(..., description="调用此 SQL 的思维链解释，用于事后审计。")

def is_safe_select(sql: str) -> bool:
    """
    基于 sqlglot 的 AST 解析防御，从语法树层面阻断危险操作。
    """
    try:
        parsed = sqlglot.parse(sql, read="postgres")
        for statement in parsed:
            if not isinstance(statement, sqlglot.exp.Select):
                logger.warning("Blocked unsafe SQL AST", statement=type(statement).__name__)
                return False
        return True
    except ParseError as e:
        logger.error("Failed to parse SQL", error=str(e))
        return False

@mcp.tool()
async def query_experiment(input: QueryInput, ctx: Context) -> str:
    """
    查询核心科研实验数据库。系统内嵌 AST 防御，任何非 SELECT 操作将被拦截并引发逆向采样 (Sampling) 审计。
    """
    logger.info("Executing research DB query", reasoning=input.reasoning, sql=input.sql_query)
    
    # 1. AST 安全防御
    if not is_safe_select(input.sql_query):
        # 触发逆向审计
        logger.warning("Unsafe SQL detected, triggering sampling audit...")
        try:
            # 向大模型大脑发起逆向请求
            audit_result = await ctx.session.create_message(
                messages=[{
                    "role": "user", 
                    "content": f"审计请求：某个子系统正试图执行高危 SQL: `{input.sql_query}`。请判断其危险性。"
                }]
            )
            return f"[拦截] 高危 SQL 执行被挂起。大脑审计结果: {audit_result}"
        except Exception as e:
            return f"[拦截] 这是一个危险语句，且审计连接失败：{str(e)}"

    # 2. 安全查询执行
    uri = f"postgresql://{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
    try:
        # 使用 psycopg 的异步支持
        async with await psycopg.AsyncConnection.connect(uri) as aconn:
            # 强制设定 Statement Timeout (10秒)
            await aconn.execute("SET statement_timeout = '10s'")
            async with aconn.cursor() as acur:
                await acur.execute(input.sql_query)
                records = await acur.fetchall()
                # 获取列名
                columns = [desc[0] for desc in acur.description] if acur.description else []
                # 简单格式化返回
                res = [dict(zip(columns, row)) for row in records]
                return str(res)
    except psycopg.Error as e:
        logger.error("Database execution error", error=str(e))
        return f"查询执行失败: {str(e)}"

if __name__ == "__main__":
    mcp.run(transport="stdio")
