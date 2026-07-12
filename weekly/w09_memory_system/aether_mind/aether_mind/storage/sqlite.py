"""
AetherMind SQLite Storage Adapter
=================================

设计方案:
---------
本模块使用 `aiosqlite` 异步库，实现了关系型数据库存储契约 `SQLStore`。
为本地运行环境提供一键式、轻量级的会话状态和日志记录持久化。

结构说明:
---------
- SQLiteStore: 实现 `SQLStore` Protocol 的适配器类，接受 `db_path` 作为数据库物理文件路径。

数据流向:
---------
1. 调用 `init_db()` 时，建立 SQLite 连接，物理执行 DDL 创建表。
2. 调用各增删改查方法时，内部开启异步连接与游标 (Connection & Cursor)，完成 SQL 语句绑定执行后，提交事务并自动释放资源。
"""

import time
import aiosqlite
from typing import List, Dict, Any, Optional
from aether_mind.storage.base import SQLStore


class SQLiteStore(SQLStore):
    """
    异步 SQLite 存储适配器，满足 SQLStore 协议契约。
    """

    def __init__(self, db_path: str = "aether_mind.db"):
        """
        初始化 SQLite 存储适配器。

        Args:
            db_path (str): SQLite 物理数据库文件路径。
        """
        self.db_path = db_path

    async def init_db(self) -> None:
        """
        创建 SQLite 物理表结构及对应高性能查询索引。
        """
        async with aiosqlite.connect(self.db_path) as conn:
            # 开启外键约束支持
            await conn.execute("PRAGMA foreign_keys = ON;")

            # 1. 创建用户表
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                );
            """)

            # 2. 创建会话表
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    created_at INTEGER NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
                );
            """)

            # 3. 创建消息历史表
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    timestamp INTEGER NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
                );
            """)

            # 4. 创建 Trace 追踪日志表
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS trace_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    step_name TEXT NOT NULL,
                    duration_ms INTEGER NOT NULL,
                    input_data TEXT,
                    output_data TEXT,
                    timestamp INTEGER NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
                );
            """)

            # 5. 创建长期记忆变动审计日志表
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS memory_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    fact_key TEXT NOT NULL,
                    fact_value TEXT NOT NULL,
                    details TEXT,
                    timestamp INTEGER NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
                );
            """)

            # 6. 创建提升高并发检索效率的索引
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_msg_session ON messages(session_id);")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_trace_session ON trace_log(session_id);")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_user ON memory_log(user_id);")

            await conn.commit()

    async def create_session(self, session_id: str, user_id: str) -> None:
        """
        创建新会话，如果关联的用户不存在，则自动隐式创建对应用户。

        Args:
            session_id (str): 会话唯一 ID。
            user_id (str): 用户 ID。
        """
        async with aiosqlite.connect(self.db_path) as conn:
            # 隐式创建用户（如果不存在该用户）
            await conn.execute(
                "INSERT OR IGNORE INTO users (user_id, username, created_at) VALUES (?, ?, ?);",
                (user_id, f"User_{user_id[:8]}", int(time.time()))
            )
            # 创建会话
            await conn.execute(
                "INSERT OR IGNORE INTO sessions (session_id, user_id, summary, created_at) VALUES (?, ?, ?, ?);",
                (session_id, user_id, "", int(time.time()))
            )
            await conn.commit()

    async def save_message(self, session_id: str, role: str, content: str) -> None:
        """
        将单条消息存入数据库。

        Args:
            session_id (str): 会话 ID。
            role (str): 消息发送者角色 (system/user/assistant)。
            content (str): 消息内容文本。
        """
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(
                "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?);",
                (session_id, role, content, int(time.time()))
            )
            await conn.commit()

    async def load_session_context(self, session_id: str) -> List[Dict[str, Any]]:
        """
        按时间升序加载某个会话的历史消息。

        Args:
            session_id (str): 会话 ID。

        Returns:
            List[Dict[str, Any]]: 格式化后的消息字典列表。
        """
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute(
                "SELECT role, content, timestamp FROM messages WHERE session_id = ? ORDER BY timestamp ASC;",
                (session_id,)
            ) as cursor:
                rows = await cursor.fetchall()
                return [{"role": row["role"], "content": row["content"], "timestamp": row["timestamp"]} for row in rows]

    async def update_session_summary(self, session_id: str, summary: str) -> None:
        """
        更新会话摘要。

        Args:
            session_id (str): 会话 ID。
            summary (str): 最新的摘要文本。
        """
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(
                "UPDATE sessions SET summary = ? WHERE session_id = ?;",
                (summary, session_id)
            )
            await conn.commit()

    async def get_session_summary(self, session_id: str) -> Optional[str]:
        """
        获取会话摘要。

        Args:
            session_id (str): 会话 ID。

        Returns:
            Optional[str]: 摘要文本。未找到会话时返回 None。
        """
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute(
                "SELECT summary FROM sessions WHERE session_id = ?;",
                (session_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return row["summary"] if row else None

    async def get_session_user(self, session_id: str) -> Optional[str]:
        """
        根据会话 ID 检索租户用户 ID，用于隔离鉴权。

        Args:
            session_id (str): 会话 ID。

        Returns:
            Optional[str]: 关联的 user_id。
        """
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute(
                "SELECT user_id FROM sessions WHERE session_id = ?;",
                (session_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return row["user_id"] if row else None

    async def save_memory_log(
        self, user_id: str, action: str, fact_key: str, fact_value: str, details: Optional[str] = None
    ) -> None:
        """
        审计记录长期记忆的增删改衰减动作。

        Args:
            user_id (str): 用户 ID。
            action (str): 执行的操作类型。
            fact_key (str): 事实 Key。
            fact_value (str): 事实 Value 详情。
            details (Optional[str]): 额外关联描述。
        """
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(
                "INSERT INTO memory_log (user_id, action, fact_key, fact_value, details, timestamp) VALUES (?, ?, ?, ?, ?, ?);",
                (user_id, action, fact_key, fact_value, details or "", int(time.time()))
            )
            await conn.commit()

    async def save_trace_log(
        self, session_id: str, step_name: str, duration_ms: int, input_data: str, output_data: str
    ) -> None:
        """
        记录各个子任务/微引擎调用的执行轨迹与时间消耗。

        Args:
            session_id (str): 会话 ID。
            step_name (str): 步骤描述。
            duration_ms (int): 执行时长（ms）。
            input_data (str): 序列化的输入。
            output_data (str): 序列化的输出。
        """
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(
                "INSERT INTO trace_log (session_id, step_name, duration_ms, input_data, output_data, timestamp) VALUES (?, ?, ?, ?, ?, ?);",
                (session_id, step_name, duration_ms, input_data, output_data, int(time.time()))
            )
            await conn.commit()
