"""
AetherMind Buffer Memory Manager
================================

设计方案:
---------
该模块实现了短期工作记忆管理器 `BufferMemoryManager`。
负责追踪、载入和修剪特定会话（Session）的历史消息。
为防止 Context 窗口溢出及 Token 成本暴涨，采用字符滑窗监测。
当会话历史长度超出预设阈值时，在不阻塞当前主对话交互的前提下，
启动后台异步任务（`asyncio.create_task`），触发大模型将老旧消息与先前摘要进行归约合并，
保存最新摘要并物理清理数据库中已压缩的消息。

结构说明:
---------
- BufferMemoryManager: 短期工作记忆管理类，提供添加消息、加载上下文及触发后台异步总结的核心逻辑。

数据流向:
---------
1. 用户输入/助手回复时，调用 `append()` 方法，实时写入数据库 `messages` 表。
2. 计算当前数据库消息的总字符数。如果超出 `token_limit` 限制，触发异步后台总结。
3. 后台任务提取出前 N 条消息，调用 LLM 结合 sessions 表中的 old_summary 生成新 summary。
4. 更新 sessions 表的 summary 字段，并物理删除已压缩的 messages 数据。
"""

import asyncio
from typing import List, Dict, Any, Optional
from aether_mind.storage.base import SQLStore
from aether_mind.utils.client import AetherMindLLMClient
from aether_mind.utils.logging import logger
from aether_mind.config import settings


class BufferMemoryManager:
    """
    工作记忆/短期记忆管理器。支持 Token 监测、滑窗控制和非阻塞后台异步摘要压缩。
    """

    def __init__(self, token_limit: int = 2000):
        """
        初始化短期记忆管理器。

        Args:
            token_limit (int): 触发摘要的字符长度限制（默认 2000）。
        """
        self.token_limit = token_limit
        # 后台执行中的异步任务集合，防止 GC 提前回收
        self._running_tasks = set()

    async def load_messages(self, session_id: str, db: SQLStore) -> List[Dict[str, Any]]:
        """
        从底层关系型数据库中加载某会话目前未被物理删除的活跃消息。

        Args:
            session_id (str): 会话唯一 ID。
            db (SQLStore): 数据库连接适配器。

        Returns:
            List[Dict[str, Any]]: 活跃历史消息列表。
        """
        return await db.load_session_context(session_id)

    async def append(
        self,
        session_id: str,
        role: str,
        content: str,
        db: SQLStore,
        client: AetherMindLLMClient
    ) -> None:
        """
        追加一条消息记录至数据库，并检测是否超出 Token 长度限制。

        Args:
            session_id (str): 会话唯一 ID。
            role (str): 角色。
            content (str): 消息内容。
            db (SQLStore): 数据库连接适配器。
            client (AetherMindLLMClient): 大模型 API 客户端。
        """
        # 1. 物理写入数据库 messages 表
        await db.save_message(session_id, role, content)

        # 2. 从数据库读取当前全量活跃消息
        active_messages = await db.load_session_context(session_id)

        # 3. 计算消息总长度（以字符数近似 Token）
        total_length = sum(len(msg["content"]) for msg in active_messages)

        # 4. 判断是否超出预算阈值，若超出则启动非阻塞异步后台总结
        if total_length > self.token_limit:
            logger.info(
                f"[短期记忆监控] 会话 {session_id} 长度 ({total_length} 字符) 超出阈值 ({self.token_limit})，触发后台异步摘要归约..."
            )
            # 创建强引用的异步 Task，放入 task 集合防止被 Event Loop 的垃圾回收意外中断
            task = asyncio.create_task(
                self._async_summarize(session_id, active_messages, db, client)
            )
            self._running_tasks.add(task)
            # 执行完后移出集合
            task.add_done_callback(self._running_tasks.discard)

    async def _async_summarize(
        self,
        session_id: str,
        active_messages: List[Dict[str, Any]],
        db: SQLStore,
        client: AetherMindLLMClient
    ) -> None:
        """
        异步后台执行摘要压缩。

        Args:
            session_id (str): 会话 ID。
            active_messages (List[Dict[str, Any]]): 活跃历史消息全集。
            db (SQLStore): 数据库适配器。
            client (AetherMindLLMClient): 大模型客户端。
        """
        try:
            # 1. 提取当前会话已存在的先前累计 summary
            old_summary = await db.get_session_summary(session_id) or ""

            # 2. 保留最近 2 轮活跃对话（最后 4 条消息），将前面的旧消息切片压缩
            keep_count = 4
            if len(active_messages) <= keep_count:
                logger.info(f"[异步摘要] 会话 {session_id} 消息轮数过少，跳过本次压缩。")
                return

            messages_to_compress = active_messages[:-keep_count]

            # 3. 序列化待压缩的消息为文本块
            formatted_messages = "\n".join(
                f"{msg['role']}: {msg['content']}" for msg in messages_to_compress
            )

            # 4. 构造高保真压缩 Prompt
            prompt = [
                {
                    "role": "system",
                    "content": (
                        "你是一个高保真的会话上下文摘要压缩器。\n"
                        "请将已有的先前摘要和新增的历史对话消息进行合并归约，生成一段极简的摘要。\n"
                        "要求：\n"
                        "1. 提取出关键的信息，包括用户偏好的开源框架（如 smolagents / Letta / LangGraph）、开发习惯、核心问题和结论。\n"
                        "2. 保持叙述简洁，字数绝对不能超过 200 字。\n"
                        "3. 仅输出摘要内容，不要包含任何自然语言回复前缀。"
                    )
                },
                {
                    "role": "user",
                    "content": (
                        f"【先前累积摘要】\n{old_summary}\n\n"
                        f"【待合并的历史消息】\n{formatted_messages}\n\n"
                        "请输出合并后的极简摘要："
                    )
                }
            ]

            # 5. 调用大模型，得到新摘要
            new_summary = await client.request_llm(prompt, temperature=0.1, max_tokens=300)
            new_summary = new_summary.strip()

            # 6. 更新数据库中的 summary
            await db.update_session_summary(session_id, new_summary)
            logger.info(f"[异步摘要完成] 会话 {session_id} 新摘要：{new_summary}")

            # 7. 物理删除数据库中 messages 表已压缩的旧消息记录，保留最后 keep_count 条
            # 获取已压缩的最晚一条消息的时间戳（或直接批量按时间删除）
            # 由于 SQLite/Postgres 的 messages 表按顺序生成，我们可以物理清理时间戳小于等于待压缩最晚时间戳的数据。
            cutoff_timestamp = messages_to_compress[-1]["timestamp"]
            
            # 我们通过 SQLStore 的定制行为或直接利用 DB 层物理操作，
            # 由于 base.py SQLStore 未定义专门的 delete 接口，我们在此利用 db 本身底层的 Connection 执行：
            # 为了保持 protocol 适配性的原则，我们在 SQLiteStore/PostgreSQLStore 可以反射调用
            # 或者我们在这里直接执行物理表操作。为安全起见，我们在 storage/sqlite 和 postgres 中反射执行，
            # 或通过 db 后置方法（此处我们直接知道底层 conn/pool 的细节，可以在各实现类加个专门删除接口或利用 db_path/pool）
            # 更好的设计是：在 db 层删除 messages，或直接用 sql 语句。
            # 为了契约的扩展性，我们直接让各 SQLStore 实现支持删除操作。
            # 事实上，我们可以在 SQLStore Protocol 里扩展一个 delete_messages 接口！
            # 但既然 SQLStore 已经在 base.py 定义好且被 user_approved 了，我们可以用直接的 delete 命令，
            # 并在 sqlite.py 和 postgres.py 中显式支持。
            # 让我们通过 db 底层的连接删除。
            # 对于 SQLite: 我们通过 aiosqlite 物理连接。
            # 对于 Postgres: 我们通过 asyncpg 连接。
            # 这样可以在 buffer.py 中增加一个防御性检测。
            if hasattr(db, "db_path"):  # 说明是 SQLiteStore
                import aiosqlite
                async with aiosqlite.connect(db.db_path) as conn:
                    await conn.execute(
                        "DELETE FROM messages WHERE session_id = ? AND timestamp <= ?;",
                        (session_id, cutoff_timestamp)
                    )
                    await conn.commit()
            elif hasattr(db, "pool"):  # 说明是 PostgreSQLStore
                pool = await db._get_pool()
                async with pool.acquire() as conn:
                    await conn.execute(
                        "DELETE FROM messages WHERE session_id = $1 AND timestamp <= $2;",
                        session_id, cutoff_timestamp
                    )

            logger.info(f"[异步摘要完成] 会话 {session_id} 已物理清理时间戳 <= {cutoff_timestamp} 的旧消息")

        except Exception as e:
            logger.error(f"[异步摘要异常] 压缩会话 {session_id} 失败: {str(e)}", exc_info=True)
