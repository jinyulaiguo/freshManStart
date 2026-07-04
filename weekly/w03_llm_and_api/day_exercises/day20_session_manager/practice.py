"""
Day 20 练习模版：并发安全的 Session 会话管理器与 LRU 淘汰机制

设计方案：
1. 设计意图：
   在高并发多用户 Agent 系统中，多协程可能并发读写同一个会话（Session），导致数据竞态问题。
   同时，系统物理内存有限，无限增长的 Session 极易导致 OOM。
   本模块通过 asyncio.Lock 保证并发安全，并通过 OrderedDict 实现 $O(1)$ 的 LRU 会话淘汰机制。
   引入二级缓存思想：当会话被淘汰时通过 on_evict_callback 异步落库；当内存未命中时通过 on_load_callback 异步热装载。
   引入双重检查锁（Double-Checked Locking）机制防范高并发下的缓存击穿。

2. 类与函数结构：
   - Session: 代表单个用户的会话对象。
     - history: 存储消息历史列表。
     - lock: asyncio.Lock，保证单个会话内消息追加的串行化。
     - append_message(message): 并发安全地向历史追加消息。
   - SessionManager: 全局会话管理器。
     - max_sessions: 允许在内存中缓存的最大会话数。
     - sessions: OrderedDict[str, Session]，存储所有活跃会话，利用其有序性进行 LRU 淘汰。
     - lock: asyncio.Lock，保护 sessions 映射表结构的读写原子性。
     - session_creation_locks: dict，临时存放各个 session_id 专属的加载创建锁，防止并发击穿。
     - on_evict_callback: 协程回调函数，当 Session 被淘汰时触发落库。
     - on_load_callback: 协程回调函数，当内存未命中时触发历史消息加载。
     - get_session(session_id, create_if_missing): 获取或创建会话，调整其 LRU 优先级。
     - append_message_to_session(session_id, message): 对特定会话追加消息。

3. 关键数据流向：
   [用户并发请求] 
         │
         ▼
   [SessionManager.get_session] ───(检查内存)───> [命中：移动到表尾并返回]
         │
         ├───(未命中：获取专属会话创建锁)───> [双重检查内存] ───> [已加载：直接返回]
         │                                                      │
         │                                                      ▼
         │                                            [未加载：触发 on_load_callback]
         │                                                      │
         │                                                      ▼
         │                                            [新建会话并装载历史，插入表尾]
         │                                                      │
         │ (若超出容量限制)                                      ▼
         └────────────────────────────────────────────> [LRU 弹出最老 Session]
                                                                │
                                                                ▼
                                                       [触发异步落库回调]
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
        # TODO: 使用会话锁保证消息追加的串行与原子性
        raise NotImplementedError("TODO: 实现 Session.append_message 并发安全追加消息")

    def __repr__(self) -> str:
        return f"Session(id={self.session_id}, len_history={len(self.history)})"


class SessionManager:
    """
    并发安全的会话管理器，提供基于 LRU 机制与双重检查锁的二级缓存会话管理。
    """
    def __init__(
        self, 
        max_sessions: int, 
        on_evict_callback: Optional[Callable[[Session], Awaitable[None]]] = None,
        on_load_callback: Optional[Callable[[str], Awaitable[Optional[List[dict]]]]] = None
    ):
        """
        初始化管理器。
        :param max_sessions: 内存中允许保留的最大 Session 数量上限
        :param on_evict_callback: 异步回调函数，在会话被淘汰时调用，传入被淘汰的 Session 对象进行落库
        :param on_load_callback: 异步回调函数，在内存未命中时调用，传入 session_id 加载已持久化的历史数据
        """
        self.max_sessions: int = max_sessions
        self.on_evict_callback: Optional[Callable[[Session], Awaitable[None]]] = on_evict_callback
        self.on_load_callback: Optional[Callable[[str], Awaitable[Optional[List[dict]]]]] = on_load_callback
        
        # 使用 OrderedDict 管理 LRU 缓存：最新访问的放右侧（尾部），最久未被访问的放左侧（头部）
        self.sessions: OrderedDict[str, Session] = OrderedDict()
        self.lock: asyncio.Lock = asyncio.Lock()  # 保护全局 sessions 映射表的读写锁
        self.session_creation_locks: Dict[str, asyncio.Lock] = {}  # 细粒度加载锁，防止缓存击穿

    async def get_session(self, session_id: str, create_if_missing: bool = True) -> Optional[Session]:
        """
        获取指定 Session 实例。如果存在，提升其 LRU 优先级并返回；
        如果不存在且 create_if_missing 为 True，则新建/热装载一个 Session 并处理可能发生的 LRU 淘汰。
        需要使用 Double-Checked Locking 机制保证并发加载的原子性，防止重复装载或创建。
        """
        # TODO: 1. 快速检查内存：持有全局锁检索 sessions 表。若命中，移动到 OrderedDict 尾部并返回。
        # TODO: 2. 内存不命中且 create_if_missing 为 True 时：
        #          - 在全局锁的保护下，获取或创建该 session_id 专属的细粒度加载锁。
        # TODO: 3. 在专属加载锁的保护下：
        #          - 再次检查 sessions 映射表（双重检查），若已由其他协程加载完毕，直接返回。
        #          - 调用 on_load_callback 异步加载持久化的历史。
        #          - 创建并初始化 Session，将历史装载进去。
        #          - 在全局锁的保护下，将 Session 插入表尾，若长度超出容量上限，弹出头部最老的会话。
        # TODO: 4. 在临界区锁外（即释放了 OrderedDict 锁后），执行被淘汰会话的异步落库回调。
        # TODO: 5. 清理专属加载锁并返回新建的 Session 实例。
        raise NotImplementedError("TODO: 实现 SessionManager.get_session 方法，包含双重检查锁与热装载 LRU 淘汰")

    async def append_message_to_session(self, session_id: str, message: dict) -> None:
        """
        并发安全地向指定 Session 追加一条消息。
        """
        # TODO: 1. 获取（或自动回装创建）对应的 Session
        # TODO: 2. 调用 Session 自身的并发安全方法追加消息
        raise NotImplementedError("TODO: 实现 SessionManager.append_message_to_session 方法")


# ==========================================
# 调试主入口与 TODO 拦截提示
# ==========================================
async def main():
    print("=== 开始 Day 20 Session管理器测试 ===")
    
    async def mock_db_save(session: Session):
        print(f"[Callback] 💾 正在保存被淘汰会话 {session.session_id}，消息数: {len(session.history)}")
        await asyncio.sleep(0.01)

    async def mock_db_load(session_id: str):
        print(f"[Callback] 🔍 正在加载会话 {session_id} 的历史数据...")
        await asyncio.sleep(0.01)
        return []

    manager = SessionManager(max_sessions=3, on_evict_callback=mock_db_save, on_load_callback=mock_db_load)
    
    try:
        print("\n--- 测试 1: 消息并发追加 ---")
        await manager.append_message_to_session("session_1", {"role": "user", "content": "你好"})
        session = await manager.get_session("session_1")
        print(f"获取成功: {session}, 历史: {session.history}")

    except NotImplementedError as e:
        print("\n" + "="*50)
        print("🚩 【拦截提示】您需要实现核心代码以通过测试！")
        print(f"提示细节: {e}")
        print("="*50 + "\n")

if __name__ == "__main__":
    asyncio.run(main())
