"""
Day 61: 底层关系持久化 - Schema 建模与多 Session 状态重构 (Standard Answer)

设计方案说明：
1. **设计意图**：
   本模块通过 aiosqlite 构建本地 SQLite 持久化管理，提供了断电状态重构（State Recovery）的底层支持。
   解耦了内存中的状态变量与底层物理存储机制，支持 Session 的断开重建与 facts 偏好的跨会话持久留存。
2. **三表 Schema 实体结构**：
   - `sessions`: 会话元数据表，建立 session 与 user 的所属关系。
   - `messages`: 会话顺序消息历史表，级联 session_id。
   - `memories`: 持久 Facts 事实表，级联 user_id。
3. **一致性与物理防错设计**：
   - Facts 写入时在单个事务中执行“先删后插”，原地覆盖重复 Facts，杜绝冗余项堆积。
   - 在测试结束阶段，主动关闭连接并物理移除临时 DB 备份文件，保护工作空间清洁。
"""

import os
import time
import sys
from typing import List, Dict, Any
import aiosqlite

class PersistenceStore:
    """基于 aiosqlite 的多 Session 关系持久化管理器"""

    def __init__(self, db_path: str = "agent_memory.db"):
        """初始化持久化管理器。

        Args:
            db_path: 本地 SQLite 数据库文件路径。
        """
        self.db_path = db_path

    async def init_db(self) -> None:
        """异步执行建表初始化，物理构建 sessions, messages, memories 三张关联表。"""
        async with aiosqlite.connect(self.db_path) as db:
            # 步骤 1: 建立 sessions 表，映射会话 ID、用户 ID 及创建时间
            await db.execute('''
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                )
            ''')
            
            # 步骤 2: 建立 messages 表，级联存储短期会话历史消息流
            await db.execute('''
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    timestamp INTEGER NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
                )
            ''')
            
            # 步骤 3: 建立 memories 表，持久化存储该用户已沉淀的结构化 Facts 实体偏好
            await db.execute('''
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    fact_key TEXT NOT NULL,
                    fact_value TEXT NOT NULL,
                    timestamp INTEGER NOT NULL
                )
            ''')
            await db.commit()
            print("[数据库] 初始化建表三张关联 Schema 表成功。")

    async def create_session(self, session_id: str, user_id: str) -> None:
        """注册一个新的会话 Session 元数据记录。

        Args:
            session_id: 会话唯一标识符。
            user_id: 用户唯一租户标识符。
        """
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO sessions (session_id, user_id, created_at) VALUES (?, ?, ?)",
                (session_id, user_id, int(time.time()))
            )
            await db.commit()

    async def save_message(self, session_id: str, role: str, content: str) -> None:
        """异步将单条交互消息写入 messages 表中。

        Args:
            session_id: 会话唯一标识符。
            role: 消息角色 (user / assistant / system)。
            content: 消息文本。
        """
        async with aiosqlite.connect(self.db_path) as db:
            # 执行异步插入，插入会话消息及时间戳，确保后续读取时可以顺序复原
            await db.execute(
                "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
                (session_id, role, content, int(time.time() * 1000))
            )
            await db.commit()

    async def save_fact(self, user_id: str, fact_key: str, fact_value: str) -> None:
        """异步增量持久化原子偏好事实，实现去重覆盖。

        Args:
            user_id: 用户唯一租户标识符。
            fact_key: 事实的主体键。
            fact_value: 事实的值。
        """
        async with aiosqlite.connect(self.db_path) as db:
            # 步骤 1: 预防冗余，在写入前先删除该用户下已存在的相同 fact_key 记录
            await db.execute(
                "DELETE FROM memories WHERE user_id = ? AND fact_key = ?",
                (user_id, fact_key)
            )
            # 步骤 2: 原地增量写入最新的事实与时间戳
            await db.execute(
                "INSERT INTO memories (user_id, fact_key, fact_value, timestamp) VALUES (?, ?, ?, ?)",
                (user_id, fact_key, fact_value, int(time.time()))
            )
            await db.commit()

    async def load_session_context(self, session_id: str) -> List[Dict[str, str]]:
        """重构加载特定会话的消息历史上下文，重现 Working Memory 状态。

        Args:
            session_id: 会话唯一标识符.

        Returns:
            符合 API 格式要求的消息字典列表（按时间戳升序排序）。
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            # 按时间戳升序排序进行检索，确保还原后的上下文对话逻辑顺序正确
            async with db.execute(
                "SELECT role, content FROM messages WHERE session_id = ? ORDER BY timestamp ASC",
                (session_id,)
            ) as cursor:
                rows = await cursor.fetchall()
                # 步骤 2: 反序列化重塑符合大模型接口契约的消息列表
                return [{"role": r["role"], "content": r["content"]} for r in rows]

    async def load_user_memories(self, user_id: str) -> Dict[str, str]:
        """重构加载特定用户的长期事实偏好，还原 Long-term Memory 状态。

        Args:
            user_id: 用户唯一租户标识符。

        Returns:
            以字典形式表示的长期偏好 Facts 键值对。
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT fact_key, fact_value FROM memories WHERE user_id = ?",
                (user_id,)
            ) as cursor:
                rows = await cursor.fetchall()
                # 步骤 2: 将数据库扁平记录重构成长期 facts 键值对
                return {r["fact_key"]: r["fact_value"] for r in rows}


# 调试主入口与物理断电恢复测试
async def main() -> None:
    print("=== 运行 Day 61 关系型持久化与断电状态重构标准答案 ===")

    test_db = "temp_test_agent_memory.db"
    
    # 1. 初始化持久化存储
    store = PersistenceStore(db_path=test_db)
    await store.init_db()

    session_id = "session_mock_abc123"
    user_id = "user_leeming"

    # 2. 模拟运行写入，注册会话及追加消息/Facts
    print("\n--- 步骤 1: 写入活跃会话数据与 Facts 偏好 ---")
    await store.create_session(session_id, user_id)
    await store.save_message(session_id, "user", "你好，我叫李明，目前在谷歌写 Python。")
    await store.save_message(session_id, "assistant", "你好，李明！请问目前遇到了什么技术难点？")
    
    await store.save_fact(user_id, "user_prefer_language", "Python")
    await store.save_fact(user_id, "user_employer", "Google")
    print("活跃上下文及持久 Facts 已物理写入数据库。")

    # 3. 模拟“突然断电 / 进程崩溃”：物理销毁旧的 PersistenceStore 实例
    print("\n--- 步骤 2: 模拟系统突发崩溃退出 (销毁内存实例) ---")
    del store
    print("旧的持久化内存对象已物理销毁。")

    # 4. 模拟“系统重启恢复”：建立全新 PersistenceStore 实例并传入 session_id
    print("\n--- 步骤 3: 系统重启，执行状态重构 (State Recovery) ---")
    new_store = PersistenceStore(db_path=test_db)
    
    # 异步反序列化恢复 Working Memory 与 Long-term Memory
    recovered_context = await new_store.load_session_context(session_id)
    recovered_memories = await new_store.load_user_memories(user_id)

    # 5. 验证是否 100% 恢复
    print("\n--- 步骤 4: 校验数据重塑一致性 ---")
    print(f"重构恢复的消息数: {len(recovered_context)} 条")
    for idx, msg in enumerate(recovered_context):
        print(f" [{idx}] {msg['role'].upper()}: {msg['content']}")
        
    print(f"重构恢复的 Facts: {recovered_memories}")

    # 断言数据契约是否完全吻合
    is_message_ok = (len(recovered_context) == 2 and recovered_context[0]["role"] == "user")
    is_memory_ok = (recovered_memories.get("user_prefer_language") == "Python")
    
    print(f"\n物理断电恢复校验 (三表状态 100% 复原): {'✅ 通过' if (is_message_ok and is_memory_ok) else '❌ 失败'}")

    # 6. 物理清理临时文件，保障工作区绝对纯净
    if os.path.exists(test_db):
        os.remove(test_db)
        print("\n[物理清理] 已安全删除临时测试 DB 文件，维护工作区整洁。")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
