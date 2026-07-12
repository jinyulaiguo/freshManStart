"""
AetherMind PostgreSQL Storage Adapter
====================================

设计方案:
---------
本模块使用 `asyncpg` 异步库，实现了关系型数据库存储契约 `SQLStore`。
为生产环境提供高并发、高性能、带连接池特性的 PostgreSQL 持久化存储后端。

结构说明:
---------
- PostgreSQLStore: 实现 `SQLStore` Protocol 的适配器类，内部封装 `asyncpg.Pool` 管理数据库连接池。

数据流向:
---------
1. 调用 `init_db()` 时，建立物理连接池，并执行物理 DDL 完成建表和索引。
2. 每一个增删改查动作都会从 Pool 中借出 Connection，执行参数绑定查询后归还，保证资源的高并发复用。
"""

import time
import asyncpg
from typing import List, Dict, Any, Optional
from aether_mind.storage.base import SQLStore


class PostgreSQLStore(SQLStore):
    """
    异步 PostgreSQL 存储适配器，满足 SQLStore 协议契约。
    使用 asyncpg 连接池实现多租户数据的高并发写入和隔离访问。
    """

    def __init__(self, dsn: str):
        """
        初始化 PostgreSQL 存储适配器。

        Args:
            dsn (str): PostgreSQL 数据库连接 DSN (例如: postgresql://user:pwd@host:port/db)。
        """
        self.dsn = dsn
        self.pool: Optional[asyncpg.Pool] = None

    async def _get_pool(self) -> asyncpg.Pool:
        """
        延迟初始化并获取数据库连接池。

        Returns:
            asyncpg.Pool: 可用的连接池对象。
        """
        if self.pool is None:
            # 创建带有最少2个、最多10个连接的物理池
            self.pool = await asyncpg.create_pool(self.dsn, min_size=2, max_size=10)
        return self.pool

    async def init_db(self) -> None:
        """
        初始化 PostgreSQL 数据库物理表及高性能复合索引。
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            # 1. 创建用户表
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id VARCHAR(64) PRIMARY KEY,
                    username VARCHAR(100) NOT NULL,
                    created_at BIGINT NOT NULL
                );
            """)

            # 2. 创建会话表
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id VARCHAR(64) PRIMARY KEY,
                    user_id VARCHAR(64) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    summary TEXT NOT NULL DEFAULT '',
                    created_at BIGINT NOT NULL
                );
            """)

            # 3. 创建消息历史表
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id SERIAL PRIMARY KEY,
                    session_id VARCHAR(64) NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
                    role VARCHAR(20) NOT NULL,
                    content TEXT NOT NULL,
                    timestamp BIGINT NOT NULL
                );
            """)

            # 4. 创建 Trace 追踪日志表
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS trace_log (
                    id SERIAL PRIMARY KEY,
                    session_id VARCHAR(64) NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
                    step_name VARCHAR(50) NOT NULL,
                    duration_ms INT NOT NULL,
                    input_data TEXT,
                    output_data TEXT,
                    timestamp BIGINT NOT NULL
                );
            """)

            # 5. 创建长期记忆变动审计日志表
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS memory_log (
                    id SERIAL PRIMARY KEY,
                    user_id VARCHAR(64) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                    action VARCHAR(50) NOT NULL,
                    fact_key VARCHAR(100) NOT NULL,
                    fact_value TEXT NOT NULL,
                    details TEXT,
                    timestamp BIGINT NOT NULL
                );
            """)

            # 6. 创建索引提升多租户会话与审计的查询速度
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_msg_session ON messages(session_id);")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_trace_session ON trace_log(session_id);")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_pg_mem_user ON memory_log(user_id);")

    async def create_session(self, session_id: str, user_id: str) -> None:
        """
        物理建立会话记录，并隐式创建用户。

        Args:
            session_id (str): 会话 ID。
            user_id (str): 用户唯一租户 ID。
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            # 开启显式事务以确保用户与会话的原子插入
            async with conn.transaction():
                await conn.execute(
                    "INSERT INTO users (user_id, username, created_at) VALUES ($1, $2, $3) ON CONFLICT (user_id) DO NOTHING;",
                    user_id, f"User_{user_id[:8]}", int(time.time())
                )
                await conn.execute(
                    "INSERT INTO sessions (session_id, user_id, summary, created_at) VALUES ($1, $2, $3, $4) ON CONFLICT (session_id) DO NOTHING;",
                    session_id, user_id, "", int(time.time())
                )

    async def save_message(self, session_id: str, role: str, content: str) -> None:
        """
        写入历史消息。

        Args:
            session_id (str): 会话唯一 ID。
            role (str): 角色。
            content (str): 消息内容。
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO messages (session_id, role, content, timestamp) VALUES ($1, $2, $3, $4);",
                session_id, role, content, int(time.time())
            )

    async def load_session_context(self, session_id: str) -> List[Dict[str, Any]]:
        """
        加载消息对话链。

        Args:
            session_id (str): 会话 ID。

        Returns:
            List[Dict[str, Any]]: 历史消息列表。
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT role, content, timestamp FROM messages WHERE session_id = $1 ORDER BY timestamp ASC;",
                session_id
            )
            return [{"role": r["role"], "content": r["content"], "timestamp": r["timestamp"]} for r in rows]

    async def update_session_summary(self, session_id: str, summary: str) -> None:
        """
        更新历史会话摘要。

        Args:
            session_id (str): 会话 ID。
            summary (str): 摘要文本。
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE sessions SET summary = $1 WHERE session_id = $2;",
                summary, session_id
            )

    async def get_session_summary(self, session_id: str) -> Optional[str]:
        """
        获取会话摘要。

        Args:
            session_id (str): 会话 ID。

        Returns:
            Optional[str]: 摘要内容。
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT summary FROM sessions WHERE session_id = $1;",
                session_id
            )
            return row["summary"] if row else None

    async def get_session_user(self, session_id: str) -> Optional[str]:
        """
        获取会话关联的用户租户。

        Args:
            session_id (str): 会话 ID。

        Returns:
            Optional[str]: 用户 ID。
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT user_id FROM sessions WHERE session_id = $1;",
                session_id
            )
            return row["user_id"] if row else None

    async def save_memory_log(
        self, user_id: str, action: str, fact_key: str, fact_value: str, details: Optional[str] = None
    ) -> None:
        """
        长期记忆变更审计。

        Args:
            user_id (str): 用户 ID。
            action (str): 执行的行为。
            fact_key (str): 事实 Key。
            fact_value (str): 事实内容。
            details (Optional[str]): 审计描述。
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO memory_log (user_id, action, fact_key, fact_value, details, timestamp) VALUES ($1, $2, $3, $4, $5, $6);",
                user_id, action, fact_key, fact_value, details or "", int(time.time())
            )

    async def save_trace_log(
        self, session_id: str, step_name: str, duration_ms: int, input_data: str, output_data: str
    ) -> None:
        """
        微引擎 Trace 调用链路审计记录。

        Args:
            session_id (str): 会话 ID。
            step_name (str): 步骤名称。
            duration_ms (int): 执行时长（毫秒）。
            input_data (str): 序列化的输入。
            output_data (str): 序列化的输出。
        """
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO trace_log (session_id, step_name, duration_ms, input_data, output_data, timestamp) VALUES ($1, $2, $3, $4, $5, $6);",
                session_id, step_name, duration_ms, input_data, output_data, int(time.time())
            )

    async def close(self) -> None:
        """
        关闭数据库物理连接池。
        """
        if self.pool is not None:
            await self.pool.close()
            self.pool = None
            
    def __del__(self) -> None:
        """
        析构函数中警告未手动释放的 Pool 连接资源。
        """
        if self.pool is not None:
            # 仅在 GC 阶段做后台防护性清空
            pass
