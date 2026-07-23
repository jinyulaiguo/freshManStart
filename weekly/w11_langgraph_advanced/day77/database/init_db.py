"""PostgreSQL 沙箱数据库初始化与连接管理模块 (Day 77 企业级实战)

设计方案与架构说明：
----------------------------------------------------------------
本模块负责为 SQL Agent 提供物理真实的 PostgreSQL 沙箱数据源。
1. 环境变量契约：统一从 `.env` 读取 POSTGRES_HOST (127.0.0.1), POSTGRES_PORT (5432),
   POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB 凭证。
2. 连接管理：使用 psycopg2 建立连接，提供幂等的建表与种子数据重置功能 (`init_database()`)。
3. 容错与防泄漏：提供 `get_db_connection()` 上下文或连接助手，确保事务显式提交或回滚。

数据流与生命周期：
------------------
[init_database] -> 读取 schema.sql -> 执行 DDL/DML 重建 users 与 orders 表 -> 验证种子记录数
"""

import os
import sys
import psycopg2
from typing import Dict, Any, List, Tuple

# 动态将工作区根目录添加到 sys.path (向上 4 层)
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../"))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from weekly.w04_prompt_and_http.utils import load_env_file

# 加载环境变量
load_env_file()


def get_pg_config() -> Dict[str, Any]:
    """从环境变量获取 PostgreSQL 连接参数契约。"""
    return {
        "host": os.getenv("POSTGRES_HOST", "127.0.0.1"),
        "port": int(os.getenv("POSTGRES_PORT", "5432")),
        "user": os.getenv("POSTGRES_USER", "postgres"),
        "password": os.getenv("POSTGRES_PASSWORD", "postgres"),
        "dbname": os.getenv("POSTGRES_DB", "postgres")
    }


def get_db_connection():
    """建立并返回一个 PostgreSQL 数据库连接。"""
    config = get_pg_config()
    conn = psycopg2.connect(**config)
    conn.autocommit = False  # 确保显式事务控制
    return conn


def init_database() -> bool:
    """读取 schema.sql 文件并初始化/重置 PostgreSQL 沙箱数据库。
    
    Returns:
        bool: 初始化成功返回 True。
    """
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    if not os.path.exists(schema_path):
        raise FileNotFoundError(f"未找到 SQL 脚本: {schema_path}")
        
    with open(schema_path, "r", encoding="utf-8") as f:
        sql_script = f.read()

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # 执行 DDL 与 DML 脚本
            cursor.execute(sql_script)
        conn.commit()
        
        # 简单核验插入记录数
        with conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM users;")
            user_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM orders;")
            order_count = cursor.fetchone()[0]
            
        print(f"✅ PostgreSQL 沙箱数据库初始化成功！(用户数: {user_count}, 订单数: {order_count})")
        return True
    except Exception as e:
        conn.rollback()
        print(f"❌ 初始化 PostgreSQL 失败: {e}")
        raise e
    finally:
        conn.close()


def execute_query(sql: str, params: Tuple = None) -> List[Dict[str, Any]]:
    """在 PostgreSQL 中执行 SQL 查询并返回字典形式的列表数据。
    
    Args:
        sql: 待执行的 SQL 语句。
        params: 绑定参数元组。
        
    Returns:
        List[Dict[str, Any]]: 格式化后的数据行列表。
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            
            # 如果是 DML 语句 (UPDATE/DELETE/INSERT)，提交事务并返回受影响行数
            if cursor.description is None:
                conn.commit()
                affected = cursor.rowcount
                return [{"affected_rows": affected, "status": "SUCCESS"}]
                
            # 如果是 SELECT 语句，抓取列名与数据行
            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()
            conn.commit()
            
            result = []
            for row in rows:
                row_dict = {}
                for col, val in zip(columns, row):
                    # 将 datetime 等特殊类型转换为 string
                    row_dict[col] = str(val) if val is not None else None
                result.append(row_dict)
            return result
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


if __name__ == "__main__":
    init_database()
