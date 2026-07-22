"""
SQLite Persistence Store Module.

设计方案说明：
1. **设计意图**：
   本模块通过 aiosqlite 库封装了多 Session 的关系型物理存储，提供系统状态持久化（Persistence Store）的能力。
   当系统突发断电、容器重启或进程退出时，可以通过重新读取数据库还原 Working Memory（短期会话消息与总结）和 Long-term Memory（原子 Facts）。
2. **三表实体 Schema 结构**：
   - `sessions`: 会话基本信息，包含 session_id, user_id, 摘要内容 (summary) 以及创建时间。
   - `messages`: 活跃工作记忆消息流，记录角色 (role)、内容 (content) 及消息物理时序。
   - `memories`: 长期事实库，记录 user_id, fact_key, fact_value, 写入时戳 (timestamp) 及艾宾浩斯留存权重 (weight)。
3. **关键数据流**：
   - 会话创建：建立 sessions 表中的主键关联。
   - 交互数据追加：消息在 append 时同步插入 messages 表。
   - 摘要更新：短期记忆滑动触发后，异步总结内容回填 sessions 表的 summary 字段。
   - 长期记忆消解：在 memories 表中执行增删改。
"""

import time
import os
from typing import List, Dict, Any, Optional
import aiosqlite

class PersistenceStore:
    """基于 SQLite 的异步多 Session 持久化存储管理器。"""

    def __init__(self, db_path: str = "agent_memory.db"):
        """初始化持久化管理器。

        Args:
            db_path: 本地 SQLite 数据库文件的物理路径。
        """
        self.db_path = db_path

    async def init_db(self) -> None:
        """异步执行建表初始化，物理构建三张关联表并增加必要的索引。

        Raises:
            RuntimeError: 数据库连接或建表操作失败时。
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                # 步骤 1: 物理构建 sessions 元数据表（增加 summary 字段存储滑动归约摘要）
                await db.execute('''
                    CREATE TABLE IF NOT EXISTS sessions (
                        session_id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL,
                        summary TEXT NOT NULL DEFAULT '',
                        created_at INTEGER NOT NULL
                    )
                ''')
                
                # 步骤 2: 物理构建 messages 会话消息表
                await db.execute('''
                    CREATE TABLE IF NOT EXISTS messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id TEXT NOT NULL,
                        role TEXT NOT NULL,
                        content TEXT NOT NULL,
                        timestamp INTEGER NOT NULL,
                        FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
                    )
                ''')
                
                # 步骤 3: 物理构建 memories 长期事实表，支持权重和时戳
                await db.execute('''
                    CREATE TABLE IF NOT EXISTS memories (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id TEXT NOT NULL,
                        fact_key TEXT NOT NULL,
                        fact_value TEXT NOT NULL,
                        timestamp REAL NOT NULL,
                        weight REAL NOT NULL DEFAULT 1.0
                    )
                ''')
                
                # 步骤 4: 建立索引以提升高并发与大消息量下的检索性能
                await db.execute("CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id)")
                await db.execute("CREATE INDEX IF NOT EXISTS idx_memories_user ON memories(user_id)")
                
                await db.commit()
                print(f"[数据库] 初始化建表并创建索引成功。数据库路径: {self.db_path}")
        except Exception as e:
            raise RuntimeError(f"数据库初始化建表失败: {e}")

    async def create_session(self, session_id: str, user_id: str) -> None:
        """注册一个新的会话 Session 记录。

        Args:
            session_id: 会话唯一标识符。
            user_id: 租户/用户唯一标识符。
        """
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO sessions (session_id, user_id, created_at) VALUES (?, ?, ?)",
                (session_id, user_id, int(time.time()))
            )
            await db.commit()

    async def get_session_user(self, session_id: str) -> Optional[str]:
        """获取特定 Session 所属的 User ID。

        Args:
            session_id: 会话唯一标识符。

        Returns:
            user_id，如果不存在则返回 None。
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT user_id FROM sessions WHERE session_id = ?", (session_id,)) as cursor:
                row = await cursor.fetchone()
                return row["user_id"] if row else None

    async def list_sessions(self) -> List[Dict[str, Any]]:
        """获取所有已注册的会话元数据列表。

        Returns:
            会话属性字典列表。
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT session_id, user_id, summary, created_at FROM sessions ORDER BY created_at DESC") as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def save_message(self, session_id: str, role: str, content: str) -> None:
        """将交互消息持久化写入 messages 表中。

        Args:
            session_id: 会话唯一标识符。
            role: 消息角色 (user / assistant / system)。
            content: 消息文本。
        """
        async with aiosqlite.connect(self.db_path) as db:
            # 使用毫秒级时间戳，保障时序排序绝对精准
            await db.execute(
                "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
                (session_id, role, content, int(time.time() * 1000))
            )
            await db.commit()

    async def load_session_context(self, session_id: str) -> List[Dict[str, str]]:
        """从 SQLite 中加载并反序列化指定 Session 的全部历史消息（按时间戳升序）。

        Args:
            session_id: 会话唯一标识符。

        Returns:
            符合 API 格式的消息字典列表。
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT role, content FROM messages WHERE session_id = ? ORDER BY timestamp ASC",
                (session_id,)
            ) as cursor:
                rows = await cursor.fetchall()
                return [{"role": r["role"], "content": r["content"]} for r in rows]

    async def clear_session_messages(self, session_id: str) -> None:
        """从 messages 表中清空指定 Session 的所有消息历史。

        用于配合滑窗摘要完成后在数据库中执行局部清除（或者也可以不清除，用以保留全量历史。
        但为配合 Day 58 “只保留摘要后的剩余活跃消息”，我们在做断电重塑时可以清理已被归纳的底层消息）。

        Args:
            session_id: 会话唯一标识符。
        """
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            await db.commit()

    async def keep_last_n_messages(self, session_id: str, keep_count: int) -> None:
        """仅保留最近的 N 条消息，删除其余旧消息。

        用于在短期滑窗归约后同步清理数据库的消息历史，防止断电后加载出已总结的消息。

        Args:
            session_id: 会话唯一标识符。
            keep_count: 需要保留的消息数量。
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            # 查询该 session 的全部 id，按时间升序
            async with db.execute(
                "SELECT id FROM messages WHERE session_id = ? ORDER BY timestamp ASC",
                (session_id,)
            ) as cursor:
                rows = await cursor.fetchall()
                total = len(rows)
                if total > keep_count:
                    # 确定需要删除的边界 id
                    delete_limit_id = rows[total - keep_count - 1]["id"]
                    await db.execute(
                        "DELETE FROM messages WHERE session_id = ? AND id <= ?",
                        (session_id, delete_limit_id)
                    )
                    await db.commit()

    async def update_session_summary(self, session_id: str, summary: str) -> None:
        """更新会话在 SQLite 中的累计摘要。

        Args:
            session_id: 会话唯一标识符。
            summary: 最新的历史摘要归纳。
        """
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE sessions SET summary = ? WHERE session_id = ?",
                (summary, session_id)
            )
            await db.commit()

    async def get_session_summary(self, session_id: str) -> str:
        """获取特定会话当前的累计摘要。

        Args:
            session_id: 会话唯一标识符。

        Returns:
            摘要字符串，如果未找到或无摘要则返回空字符串。
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT summary FROM sessions WHERE session_id = ?", (session_id,)) as cursor:
                row = await cursor.fetchone()
                return row["summary"] if row else ""

    async def save_fact(self, user_id: str, fact_key: str, fact_value: str, weight: float = 1.0, timestamp: Optional[float] = None) -> None:
        """物理写入或覆盖原子事实偏好（支持权重与时间戳）。

        Args:
            user_id: 租户唯一标识符。
            fact_key: 事实主属性键。
            fact_value: 事实具体值。
            weight: 记忆衰减初始权重。
            timestamp: 记忆时间戳（默认为当前时间）。
        """
        t = timestamp if timestamp is not None else time.time()
        async with aiosqlite.connect(self.db_path) as db:
            # 步骤 1: 物理去重，擦除已有相同 fact_key 记录
            await db.execute(
                "DELETE FROM memories WHERE user_id = ? AND fact_key = ?",
                (user_id, fact_key)
            )
            # 步骤 2: 原地插入新记录，保证数据一致性
            await db.execute(
                "INSERT INTO memories (user_id, fact_key, fact_value, timestamp, weight) VALUES (?, ?, ?, ?, ?)",
                (user_id, fact_key, fact_value, t, weight)
            )
            await db.commit()

    async def delete_fact(self, user_id: str, fact_key: str) -> None:
        """物理擦除指定用户的特定事实记录。

        Args:
            user_id: 租户唯一标识符。
            fact_key: 事实主属性键。
        """
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "DELETE FROM memories WHERE user_id = ? AND fact_key = ?",
                (user_id, fact_key)
            )
            await db.commit()

    async def load_user_memories(self, user_id: str) -> Dict[str, str]:
        """获取特定用户的长期事实偏好键值对（用于组装 LLM 输入）。

        Args:
            user_id: 租户唯一标识符。

        Returns:
            简单事实键值字典：{fact_key: fact_value}。
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT fact_key, fact_value FROM memories WHERE user_id = ? ORDER BY timestamp ASC",
                (user_id,)
            ) as cursor:
                rows = await cursor.fetchall()
                return {r["fact_key"]: r["fact_value"] for r in rows}

    async def load_all_memory_items(self, user_id: str) -> List[Dict[str, Any]]:
        """获取特定用户的长期事实完整属性记录（用于调试或 Dashboard 展示）。

        Args:
            user_id: 租户唯一标识符。

        Returns:
            包含完整字段的字典列表。
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT fact_key, fact_value, timestamp, weight FROM memories WHERE user_id = ? ORDER BY timestamp ASC",
                (user_id,)
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]

    async def clear_decayed_memories(self, user_id: str, threshold: float) -> List[str]:
        """物理清除权重低于指定阈值的“冷事实”。

        Args:
            user_id: 租户唯一标识符。
            threshold: 淘汰阈值。

        Returns:
            被删除的事实键（fact_key）列表。
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            # 步骤 1: 查询哪些将被删除
            async with db.execute(
                "SELECT fact_key FROM memories WHERE user_id = ? AND weight < ?",
                (user_id, threshold)
            ) as cursor:
                rows = await cursor.fetchall()
                deleted_keys = [r["fact_key"] for r in rows]
                
            if deleted_keys:
                # 步骤 2: 执行批量删除
                await db.execute(
                    "DELETE FROM memories WHERE user_id = ? AND weight < ?",
                    (user_id, threshold)
                )
                await db.commit()
                
            return deleted_keys

    async def update_memories_weights(self, user_id: str, weights_map: Dict[str, float]) -> None:
        """批量更新事实偏好的权重。

        Args:
            user_id: 租户唯一标识符。
            weights_map: 键为 fact_key, 值为新权重的映射表。
        """
        async with aiosqlite.connect(self.db_path) as db:
            for fact_key, weight in weights_map.items():
                await db.execute(
                    "UPDATE memories SET weight = ? WHERE user_id = ? AND fact_key = ?",
                    (weight, user_id, fact_key)
                )
            await db.commit()
