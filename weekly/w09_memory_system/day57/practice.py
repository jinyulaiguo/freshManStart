"""
Day 57: 多层级记忆契约与协议定义 (Practice Template)

设计方案说明：
1. **设计意图**：
   本模块用于定义 Agent 多层级记忆系统的抽象契约（Protocol），包括短期工作记忆、长期记忆和语义缓存。
   通过 `typing.Protocol` 定义类型契约，确保具体存储实现（如 SQLite, Qdrant, InMemory）具备一致的接口，
   实现存储介质与核心业务 Pipeline 的解耦。
2. **类结构**：
   - `ShortTermMemory(Protocol)`: 短期消息堆栈契约，规范上下文的读写。
   - `LongTermMemory(Protocol)`: 长期事实库契约，规范 Facts 的提取与增量读写。
   - `SemanticCache(Protocol)`: 语义缓存契约，拦截碰撞重复请求。
   - `InMemoryShortTermMemory`: 短期工作记忆的内存级实现示例。
   - `InMemorySemanticCache`: 语义缓存的内存级实现示例。
3. **数据流向**：
   - 交互数据写入时：消息写入 `ShortTermMemory`，命中检测在 `SemanticCache` 碰撞。
   - 数据读取时：根据 `session_id` 重构 `ShortTermMemory` 上下文。
"""

from typing import Protocol, Dict, Any, List, Optional, runtime_checkable

@runtime_checkable
class ShortTermMemory(Protocol):
    """短期工作记忆（Working Memory）的类型契约"""

    def append(self, message: Dict[str, Any]) -> None:
        """向工作记忆追加单条消息。

        Args:
            message: 消息字典，必须包含 'role' 和 'content' 字段。
        """
        ...

    def get_context(self) -> List[Dict[str, Any]]:
        """获取当前活跃的全部上下文消息列表。

        Returns:
            符合 LLM 消息输入规范的字典列表。
        """
        ...

    def clear(self) -> None:
        """清空当前 Session 的所有消息缓存。"""
        ...


@runtime_checkable
class LongTermMemory(Protocol):
    """长期记忆（Long-term Memory）的类型契约"""

    async def save_fact(self, user_id: str, key: str, value: Any) -> bool:
        """增量持久化一条用户事实或偏好。

        Args:
            user_id: 租户隔离唯一标识符。
            key: 事实或偏好的键。
            value: 事实的具体值。

        Returns:
            是否成功写入。
        """
        ...

    async def recall_facts(self, user_id: str, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """基于语义或关键词召回与 Query 相关的用户事实偏好。

        Args:
            user_id: 租户隔离唯一标识符。
            query: 检索词。
            limit: 最大召回数量上限。

        Returns:
            召回的事实列表。
        """
        ...


@runtime_checkable
class SemanticCache(Protocol):
    """语义缓存（Semantic Cache）的类型契约"""

    async def get(self, query: str) -> Optional[str]:
        """语义检索缓存是否命中。

        Args:
            query: 输入的 Query。

        Returns:
            命中的响应内容，若未命中返回 None。
        """
        ...

    async def set(self, query: str, response: str) -> None:
        """缓存一条推理响应。

        Args:
            query: 输入的 Query。
            response: 推理生成的响应。
        """
        ...


class InMemoryShortTermMemory:
    """短期工作记忆的内存型实现（待学员实现）"""

    def __init__(self) -> None:
        # 使用列表在内存中维护消息历史
        self._messages: List[Dict[str, Any]] = []

    def append(self, message: Dict[str, Any]) -> None:
        """实现追加消息契约方法"""
        # TODO: 学员需要在这里实现逻辑，往 self._messages 中添加消息
        raise NotImplementedError("TODO: 请实现 InMemoryShortTermMemory.append")

    def get_context(self) -> List[Dict[str, Any]]:
        """实现获取上下文契约方法"""
        # TODO: 学员需要在此处返回消息列表
        raise NotImplementedError("TODO: 请实现 InMemoryShortTermMemory.get_context")

    def clear(self) -> None:
        """实现清除契约方法"""
        # TODO: 学员需要清除消息列表
        raise NotImplementedError("TODO: 请实现 InMemoryShortTermMemory.clear")


class InMemorySemanticCache:
    """语义缓存的内存简易型实现（基于精确字符串碰撞，待学员实现）"""

    def __init__(self) -> None:
        # 使用字典在内存中缓存键值对
        self._cache: Dict[str, str] = {}

    async def get(self, query: str) -> Optional[str]:
        """精确匹配缓存"""
        # TODO: 学员需要根据 query 匹配 self._cache 中的记录并返回
        raise NotImplementedError("TODO: 请实现 InMemorySemanticCache.get")

    async def set(self, query: str, response: str) -> None:
        """设置缓存值"""
        # TODO: 学员需要将 key-value 写入缓存字典
        raise NotImplementedError("TODO: 请实现 InMemorySemanticCache.set")


if __name__ == "__main__":
    print("=== 启动 Day 57 记忆系统分层契约调试入口 ===")
    
    # 模拟学员编写的组件实例化
    st_memory = InMemoryShortTermMemory()
    sem_cache = InMemorySemanticCache()

    # 1. 验证类型协议契约契合度
    print(f"InMemoryShortTermMemory 是否符合 ShortTermMemory 契约: {isinstance(st_memory, ShortTermMemory)}")
    print(f"InMemorySemanticCache 是否符合 SemanticCache 契约: {isinstance(sem_cache, SemanticCache)}")

    try:
        # 2. 模拟触发异常拦截，提示学员进行 TODO 填充
        print("\n尝试写入短期记忆...")
        st_memory.append({"role": "user", "content": "Hello"})
    except NotImplementedError as e:
        print(f"❌ 捕获到预期的 TODO 拦截错误: {e}")
        print("💡 请学员根据 practice.py 中的 TODO 注释编写具体逻辑。")
