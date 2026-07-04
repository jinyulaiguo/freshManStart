"""
OpsChat CLI - 并发安全与 LRU 淘汰会话管理器 (session_manager.py)

=========================================
设计方案说明
=========================================
1. 设计意图：
   在高并发多用户或多会话调试场景下，实现会话数据协程安全隔离。
   采用 OrderedDict 构建 LRU 缓存，当会话数超过 max_sessions 时自动淘汰最久未访问会话。

2. 类与函数结构：
   - Session:
     - append_message(message): 并发安全地向消息历史追加单条消息。
   - SessionManager:
     - get_session(session_id, create_if_missing): 获取或热装载 Session。
     - append_message_to_session(session_id, message): 线程安全追加消息。
=========================================
"""

import asyncio
from collections import OrderedDict
from typing import Dict, Optional, Callable, Awaitable, List

class Session:
    """
    单个用户的会话对象，封装了专属的消息历史与并发控制锁。
    """
    def __init__(self, session_id: str):
        self.session_id: str = session_id
        self.history: List[dict] = []
        self.lock: asyncio.Lock = asyncio.Lock()  # 单个 Session 的消息追加锁

    async def append_message(self, message: dict) -> None:
        """
        并发安全地向当前会话的历史记录中追加一条消息。
        """
        async with self.lock:
            await asyncio.sleep(0.001)  # 模拟微小延迟
            self.history.append(message)


class SessionManager:
    """
    并发安全的会话管理器，提供基于 LRU 机制、防击穿与二级缓存加载的会话管理。
    """
    def __init__(
        self, 
        max_sessions: int, 
        on_evict_callback: Optional[Callable[[Session], Awaitable[None]]] = None,
        on_load_callback: Optional[Callable[[str], Awaitable[Optional[List[dict]]]]] = None
    ):
        self.max_sessions: int = max_sessions
        self.on_evict_callback: Optional[Callable[[Session], Awaitable[None]]] = on_evict_callback
        self.on_load_callback: Optional[Callable[[str], Awaitable[Optional[List[dict]]]]] = on_load_callback
        
        self.sessions: OrderedDict[str, Session] = OrderedDict()
        self.lock: asyncio.Lock = asyncio.Lock()  # 保护全局 sessions 映射表的读写锁
        self.session_creation_locks: Dict[str, asyncio.Lock] = {}  # 细粒度加载锁，防止缓存击穿

    async def get_session(self, session_id: str, create_if_missing: bool = True) -> Optional[Session]:
        """
        获取指定 Session 实例。使用 Double-Checked Locking 保证并发加载原子性。
        """
        # 1. 第一重检查
        async with self.lock:
            if session_id in self.sessions:
                self.sessions.move_to_end(session_id)
                return self.sessions[session_id]

        if not create_if_missing:
            return None

        # 2. 准备加载或新建，获取细粒度锁
        async with self.lock:
            if session_id not in self.session_creation_locks:
                self.session_creation_locks[session_id] = asyncio.Lock()
            sid_lock = self.session_creation_locks[session_id]

        async with sid_lock:
            # 双重检查
            async with self.lock:
                if session_id in self.sessions:
                    self.sessions.move_to_end(session_id)
                    return self.sessions[session_id]

            # 二级缓存加载
            loaded_history = None
            if self.on_load_callback:
                loaded_history = await self.on_load_callback(session_id)

            session = Session(session_id)
            if loaded_history is not None:
                session.history = loaded_history.copy()

            evicted_session: Optional[Session] = None
            async with self.lock:
                self.sessions[session_id] = session
                if len(self.sessions) > self.max_sessions:
                    _, evicted_session = self.sessions.popitem(last=False)

            if evicted_session and self.on_evict_callback:
                await self.on_evict_callback(evicted_session)

            async with self.lock:
                self.session_creation_locks.pop(session_id, None)

            return session

    async def append_message_to_session(self, session_id: str, message: dict) -> None:
        """
        并发安全地向指定 Session 追加一条消息。
        """
        session = await self.get_session(session_id, create_if_missing=True)
        await session.append_message(message)
