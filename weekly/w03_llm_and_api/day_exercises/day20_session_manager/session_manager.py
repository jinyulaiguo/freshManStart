"""
Day 20 参考答案：并发安全的 Session 会话管理器与 LRU 淘汰机制

设计方案：
1. 设计意图：
   在高并发多用户 Agent 系统下，会话数据需要线程/协程安全隔离。同时系统内存有限，需应用 LRU（最近最少使用）算法淘汰冷数据。
   本模块使用 asyncio.Lock 保证并发安全，并采用 collections.OrderedDict 实现 O(1) 的 LRU 淘汰策略。
   当会话数超过 max_sessions 时，将自动弹出最久未访问的会话，并触发异步淘汰回调。
   当内存未命中时，将触发异步加载回调，实现数据的二级缓存热装载。
   引入 Double-Checked Locking 双重检查锁机制防止高并发缓存击穿。

2. 类与函数结构：
   - Session 类：
     - lock: asyncio.Lock。保护 history 读写以避免协程竞态冲突。
     - append_message(message): 并发安全地向消息历史追加单条消息。
   - SessionManager 类：
     - lock: asyncio.Lock。保护 OrderedDict 会话缓存表本身操作的原子性。
     - session_creation_locks: Dict[str, asyncio.Lock]。各 Session ID 加载排队锁，防止缓存击穿。
     - sessions: OrderedDict[str, Session]。管理活跃会话，最右侧（尾部）为最新使用，最左侧（头部）为最老。
     - get_session(session_id, create_if_missing): 获取会话并将该会话置为最新使用；不存在且允许创建时新建会话，并在超出容量时执行淘汰。
     - append_message_to_session(session_id, message): 线程安全地往特定会话追加消息。

3. 关键数据流向与锁粒度控制：
   - 访问 Manager 时，先在全局 lock 的保护下对映射表做 O(1) 检索。
   - 若不命中，则使用细粒度的局部加载锁对特定的 session_id 加锁，进行异步落库历史热装载 (on_load_callback)，避免高并发下的缓存击穿。
   - 在加载后，使用 Double Check 确保不会被重复覆盖，然后写入 OrderedDict 表尾。
   - 淘汰会话触发的 Awaitable 回调（on_evict_callback）在全局 lock 释放后，在临界区外执行，避免阻塞其他会话的访问。
   - 单个 Session 的具体写入采用 Session 级别的 lock，隔离不同用户的锁竞争，支持多用户并行写入。
"""

import asyncio
import random
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
            # 模拟微小的处理时延，用于在未加锁时暴露竞态条件
            await asyncio.sleep(0.001)
            self.history.append(message)

    def __repr__(self) -> str:
        return f"Session(id={self.session_id}, len_history={len(self.history)})"


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
        使用 Double-Checked Locking 机制保证并发加载的原子性，防止重复装载或创建。
        """
        # 1. 第一重检查：快速持有全局锁检索 sessions 表。若命中，移动到表尾并返回。
        async with self.lock:
            if session_id in self.sessions:
                self.sessions.move_to_end(session_id)
                return self.sessions[session_id]

        if not create_if_missing:
            return None

        # 2. 内存不命中，准备加载或新建。在全局锁保护下获取/创建专属该 session_id 的局部加载锁。
        async with self.lock:
            if session_id not in self.session_creation_locks:
                self.session_creation_locks[session_id] = asyncio.Lock()
            sid_lock = self.session_creation_locks[session_id]

        # 3. 持有该 session_id 专属的细粒度加载锁，防止并发击穿数据库
        async with sid_lock:
            # 双重检查锁（Double-Checked Locking）：
            # 在排队等待该加载锁的过程中，其他协程可能已经将此 Session 加载进入内存了
            async with self.lock:
                if session_id in self.sessions:
                    self.sessions.move_to_end(session_id)
                    return self.sessions[session_id]

            # 4. 触发二级缓存：通过异步回调从持久层载入历史消息
            loaded_history = None
            if self.on_load_callback:
                loaded_history = await self.on_load_callback(session_id)

            # 新建或还原 Session 实例
            session = Session(session_id)
            if loaded_history is not None:
                session.history = loaded_history.copy()

            # 5. 临界区操作：将 Session 写入内存映射表，并做 LRU 容量溢出剔除
            evicted_session: Optional[Session] = None
            async with self.lock:
                self.sessions[session_id] = session
                if len(self.sessions) > self.max_sessions:
                    # 弹出最左侧（最久未访问）的会话
                    _, evicted_session = self.sessions.popitem(last=False)

            # 6. 在全局锁外部触发落库持久化回调，避免高延时 I/O 阻塞 SessionManager 的其它轻量检索
            if evicted_session and self.on_evict_callback:
                await self.on_evict_callback(evicted_session)

            # 7. 及时清理用过的加载锁，防止内存泄漏
            async with self.lock:
                self.session_creation_locks.pop(session_id, None)

            return session

    async def append_message_to_session(self, session_id: str, message: dict) -> None:
        """
        并发安全地向指定 Session 追加一条消息。
        """
        session = await self.get_session(session_id, create_if_missing=True)
        # 调用单个会话内部的局部并发安全锁
        await session.append_message(message)


# ==========================================
# 调试主入口与高并发模拟验证
# ==========================================
async def main():
    print("==================================================")
    print("🚀 开始 Day 20 Session管理器 并发与 LRU 压力测试")
    print("==================================================")

    # 模拟外部数据库
    db_store: Dict[str, List[dict]] = {}
    evicted_log = []
    
    # 模拟数据持久化的异步回调函数 (落库)
    async def db_persistence_callback(session: Session):
        print(f"[Callback 💾] 会话 {session.session_id} 被 LRU 淘汰！正在将其异步写入数据库... 消息总数: {len(session.history)}")
        await asyncio.sleep(0.01)  # 模拟持久化 I/O 延迟
        db_store[session.session_id] = session.history.copy()
        evicted_log.append(session.session_id)
        print(f"[Callback 💾] 会话 {session.session_id} 数据库写入完毕。")

    # 模拟数据库历史消息检索 (回装)
    async def db_load_callback(session_id: str) -> Optional[List[dict]]:
        print(f"[Callback 🔍] 内存未命中会话 {session_id}，正在从持久层装载历史...")
        await asyncio.sleep(0.01)  # 模拟加载 I/O 延迟
        return db_store.get(session_id, None)

    # 创建一个容量上限仅为 5 的会话管理器
    max_cap = 5
    manager = SessionManager(
        max_sessions=max_cap, 
        on_evict_callback=db_persistence_callback,
        on_load_callback=db_load_callback
    )

    # 模拟 20 个并发客服用户（session_0 到 session_19）
    num_users = 20
    messages_per_user = 3

    async def simulate_user(user_idx: int):
        session_id = f"session_{user_idx}"
        for msg_idx in range(messages_per_user):
            # 模拟用户消息在不可预测的时序上到达，产生并发协程交叉读写与频繁 LRU 换入换出
            await asyncio.sleep(random.uniform(0.01, 0.05))
            message = {"sender": f"user_{user_idx}", "text": f"Msg {msg_idx}", "seq": msg_idx}
            await manager.append_message_to_session(session_id, message)

    # 用 asyncio.gather 并发运行所有用户模拟任务
    print(f"\n[测试] 启动 {num_users} 个用户并发，每个追加 {messages_per_user} 条消息...")
    tasks = [simulate_user(i) for i in range(num_users)]
    await asyncio.gather(*tasks)

    # 在所有并发写入完成后，为了做最终一致性审查，我们把当前内存中和数据库中的所有会话做一次大审计
    print("\n================== 测试结果审计 ==================")
    print(f"内存中当前的活跃会话数: {len(manager.sessions)} (预期不超过 max_sessions={max_cap})")
    print(f"内存中的会话列表: {list(manager.sessions.keys())}")
    print(f"数据库 (db_store) 中持久化的会话数: {len(db_store)}")

    # 1. 验证内存容量未溢出
    assert len(manager.sessions) <= max_cap, "❌ 错误: 内存中缓存的会话数超过了上限容量！"
    
    # 2. 验证所有数据的完整性（包含内存中的与持久层中的）
    all_sessions_verified = True
    
    # 挨个检查 20 个用户的所有历史数据
    for u_idx in range(num_users):
        sid = f"session_{u_idx}"
        
        # 捞出最新的数据（若在内存则取内存，若被淘汰了则去数据库找）
        current_session = await manager.get_session(sid, create_if_missing=False)
        history = current_session.history if current_session else db_store.get(sid, None)
        
        if history is None:
            print(f"❌ 错误: 会话 {sid} 的历史完全丢失了！")
            all_sessions_verified = False
            continue
            
        if len(history) != messages_per_user:
            print(f"❌ 错误: 会话 {sid} 的消息长度异常，当前为 {len(history)}，预期为 {messages_per_user}")
            all_sessions_verified = False
        else:
            # 校验消息内容的连续性与顺序
            for idx, msg in enumerate(history):
                if msg["seq"] != idx:
                    print(f"❌ 错误: 会话 {sid} 中的消息顺序发生错乱！第 {idx} 位是 seq={msg['seq']}")
                    all_sessions_verified = False

    if all_sessions_verified:
        print("\n✅ [验证成功] 二级缓存机制完美工作：淘汰落库 (Evict) 与 热回装 (Lazy Load) 无缝衔接！")
        print("✅ [验证成功] 并发访问与 LRU 容量限制测试圆满通过，所有数据强一致且顺序正确！")
    else:
        print("\n❌ [验证失败] 检测到并发或 LRU 换入换出导致的数据丢失或错乱！")

if __name__ == "__main__":
    asyncio.run(main())
