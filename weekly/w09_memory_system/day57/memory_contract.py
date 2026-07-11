"""
Day 57: 多层级记忆契约与协议定义 (Standard Answer)

设计方案说明：
1. **设计意图**：
   本模块提供了多层级记忆系统接口的完整在内存（In-Memory）实现。
   这些实现不仅符合 `ShortTermMemory`、`LongTermMemory` 和 `SemanticCache` 契约，
   还通过具体的内存结构（列表、字典）模拟出工作上下文的管理及语义缓存的检索过程。
2. **类结构**：
   - `ShortTermMemory(Protocol)`: 短期工作记忆协议。
   - `LongTermMemory(Protocol)`: 长期事实库协议。
   - `SemanticCache(Protocol)`: 语义缓存协议。
   - `InMemoryShortTermMemory`: 短期工作记忆的具体内存实现。
   - `InMemoryLongTermMemory`: 长期事实记忆的具体内存实现。
   - `InMemorySemanticCache`: 基于精确碰撞或简化向量比对的语义缓存内存实现。
3. **数据流向**：
   - 数据写入时，调用 `InMemoryShortTermMemory.append` 将消息追加进会话列表。
   - 临时交互可以通过 `InMemorySemanticCache.set` 进行缓存以供复用。
"""

from typing import Protocol, Dict, Any, List, Optional, runtime_checkable
import asyncio

@runtime_checkable
class ShortTermMemory(Protocol):
    """短期工作记忆（Working Memory）的类型契约"""

    def append(self, message: Dict[str, Any]) -> None:
        """向工作记忆追加单条消息"""
        ...

    def get_context(self) -> List[Dict[str, Any]]:
        """获取当前活跃的全部上下文消息列表"""
        ...

    def clear(self) -> None:
        """清空当前 Session 的所有消息缓存"""
        ...


@runtime_checkable
class LongTermMemory(Protocol):
    """长期记忆（Long-term Memory）的类型契约"""

    async def save_fact(self, user_id: str, key: str, value: Any) -> bool:
        """增量持久化一条用户事实或偏好"""
        ...

    async def recall_facts(self, user_id: str, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """基于语义或关键词召回与 Query 相关的用户事实偏好"""
        ...


@runtime_checkable
class SemanticCache(Protocol):
    """语义缓存（Semantic Cache）的类型契约"""

    async def get(self, query: str) -> Optional[str]:
        """语义检索缓存是否命中"""
        ...

    async def set(self, query: str, response: str) -> None:
        """缓存一条推理响应"""
        ...


class InMemoryShortTermMemory:
    """短期工作记忆的内存型完整实现"""

    def __init__(self) -> None:
        # 用列表在内存中顺序存储会话消息
        self._messages: List[Dict[str, Any]] = []

    def append(self, message: Dict[str, Any]) -> None:
        """实现追加消息契约方法"""
        # 步骤 1: 数据合约校验，确保消息包含核心的 role 与 content 字段
        if "role" not in message or "content" not in message:
            raise ValueError("Invalid message contract: 'role' and 'content' are required.")
        # 步骤 2: 将消息追加至内部数组中
        self._messages.append(message)

    def get_context(self) -> List[Dict[str, Any]]:
        """实现获取上下文契约方法"""
        # 返回内部消息的拷贝，防止外部直接修改状态
        return list(self._messages)

    def clear(self) -> None:
        """实现清除契约方法"""
        # 物理清空数组
        self._messages.clear()


class InMemoryLongTermMemory:
    """长期事实记忆的内存型完整实现"""

    def __init__(self) -> None:
        # 使用字典，以 user_id 作为主键隔离用户数据
        # 内部结构为：{user_id: {fact_key: fact_value}}
        self._store: Dict[str, Dict[str, Any]] = {}

    async def save_fact(self, user_id: str, key: str, value: Any) -> bool:
        """实现保存用户事实偏好"""
        # 步骤 1: 多租户物理分区初始化
        if user_id not in self._store:
            self._store[user_id] = {}
        # 步骤 2: 增量写入或覆盖历史 Facts 键值对
        self._store[user_id][key] = value
        # 模拟磁盘或异步数据库的网络 I/O 延迟
        await asyncio.sleep(0.01)
        return True

    async def recall_facts(self, user_id: str, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """实现召回用户事实偏好"""
        # 步骤 1: 多租户隔离验证，若无该用户数据则返回空
        if user_id not in self._store:
            return []
        
        user_facts = self._store[user_id]
        recalled: List[Dict[str, Any]] = []
        
        # 步骤 2: 简易相似度检索（检测 key 的拆分词是否出现在 query 中，忽略过短的虚词）
        # 生产环境中此部分会替换为 Embedding Cosine Similarity 召回
        for k, v in user_facts.items():
            words = k.lower().split("_")
            if any(word in query.lower() and len(word) > 3 for word in words):
                recalled.append({"fact_key": k, "fact_value": v})
                if len(recalled) >= limit:
                    break
        
        await asyncio.sleep(0.01)
        return recalled


class InMemorySemanticCache:
    """语义缓存的简易内存实现（基于字符串前缀与去除噪音后的匹配）"""

    def __init__(self) -> None:
        # 使用字典在内存中缓存键值对
        self._cache: Dict[str, str] = {}

    async def get(self, query: str) -> Optional[str]:
        """前缀语义匹配缓存"""
        # 步骤 1: 规范化 Query，清洗掉常见语气词与中英文标点，还原核心文本
        def normalize(text: str) -> str:
            for char in "？?。.,，呢啊吗":
                text = text.replace(char, "")
            return text.strip().lower()

        norm_query = normalize(query)
        # 步骤 2: 遍历缓存，如果存在相似前缀则视为碰撞成功
        # 生产环境使用 Vector Similarity Threshold Filtering (例如 cosine >= 0.95)
        for cached_query, response in self._cache.items():
            norm_cached = normalize(cached_query)
            if norm_query.startswith(norm_cached) or norm_cached.startswith(norm_query):
                return response
        return None

    async def set(self, query: str, response: str) -> None:
        """设置缓存值"""
        # 将 key-value 物理写入内存字典
        self._cache[query] = response
        await asyncio.sleep(0.005)


async def main() -> None:
    print("=== 运行 Day 57 记忆系统分层契约参考答案 ===")

    # 1. 实例化核心组件
    st_memory = InMemoryShortTermMemory()
    lt_memory = InMemoryLongTermMemory()
    sem_cache = InMemorySemanticCache()

    # 2. 契约契合度检验
    print(f"InMemoryShortTermMemory 是否符合 ShortTermMemory 契约: {isinstance(st_memory, ShortTermMemory)}")
    print(f"InMemoryLongTermMemory 是否符合 LongTermMemory 契约: {isinstance(lt_memory, LongTermMemory)}")
    print(f"InMemorySemanticCache 是否符合 SemanticCache 契约: {isinstance(sem_cache, SemanticCache)}")

    # 3. 模拟 Working Memory 数据流写入与读取
    st_memory.append({"role": "user", "content": "你好，我叫张三。"})
    st_memory.append({"role": "assistant", "content": "你好，张三！请问有什么我可以帮你的？"})
    print(f"\n短期上下文数量: {len(st_memory.get_context())} 条")
    
    # 4. 模拟 Long-term Memory 事实增量写入与语义召回
    await lt_memory.save_fact(user_id="user_9527", key="user_prefer_language", value="Python")
    await lt_memory.save_fact(user_id="user_9527", key="user_skill_level", value="Advanced")
    
    # 尝试基于 query 'language' 召回事实
    recalled = await lt_memory.recall_facts(user_id="user_9527", query="你常用的编程language是什么？")
    print(f"长期偏好召回结果: {recalled}")

    # 5. 模拟 Semantic Cache 碰撞
    await sem_cache.set(query="什么是 Memory Engineering？", response="Memory Engineering 是一套管理 Agent 生命周期、时序一致性和路由状态的系统工程。")
    
    cached_response = await sem_cache.get(query="什么是 Memory Engineering 呢？")
    print(f"语义缓存命中响应: '{cached_response}'")

if __name__ == "__main__":
    asyncio.run(main())
