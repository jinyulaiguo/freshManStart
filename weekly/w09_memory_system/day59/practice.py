"""
Day 59: 长期记忆系统 - 实体级 Facts 提取与多租户物理隔离 (Practice Template)

设计方案说明：
1. **设计意图**：
   工作记忆中的聊天记录容易产生信息稀释。本模块通过 Pydantic 定义原子事实契约，
   使用 LLM 从对话中提取出独立的结构化 Facts，并使用租户 ID 进行严格的数据空间物理隔离，
   防止多用户并发环境下的越权访问和记忆交叉污染。
2. **类与数据模型结构**：
   - `FactItem(BaseModel)`: 原子事实实体，包含 `fact_key` 和 `fact_value`。
   - `FactExtractor`: 事实提取与隔离存储核心类。
     - `extract_facts(dialogue_history)`: 调用大模型提取结构化原子事实列表。
     - `save_facts(user_id, facts)`: 基于 `user_id` 物理隔离持久化事实。
     - `recall_facts(user_id, query)`: 基于用户 ID 的安全检索召回。
3. **关键数据流向**：
   - 历史消息 -> LLM JSON Prompt -> 解析为 `FactItem` 列表。
   - 提取的 `FactItem` -> 隔离分区 `self._isolated_db[user_id]` 写入。
   - 检索时 -> 仅在 `self._isolated_db[user_id]` 内部遍历，外部 query 无法跨租户碰撞。
"""

import json
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from weekly.w04_prompt_and_http.utils import LLMClient

class FactItem(BaseModel):
    """原子事实偏好数据结构契约"""
    fact_key: str = Field(description="事实的主体属性名，使用下划线蛇形命名，如 user_prefer_language, user_company")
    fact_value: str = Field(description="事实的具体内容值，必须精准、精炼，如 Python, 谷歌")


class FactExtractor:
    """事实提取与多租户物理隔离管理器"""

    def __init__(self, client: Optional[LLMClient] = None):
        """初始化 Facts 提取管理器。

        Args:
            client: 真实大模型请求客户端。
        """
        self.client = client or LLMClient()
        
        # 模拟持久化数据库：用字典在内存中维护物理分区的多租户数据
        # 结构：{user_id: {fact_key: fact_value}}
        self._isolated_db: Dict[str, Dict[str, Any]] = {}

    async def extract_facts(self, dialogue_history: List[Dict[str, str]]) -> List[FactItem]:
        """调用大模型，从多轮交互会话历史中提取出结构化事实 Facts。

        Args:
            dialogue_history: 多轮对话消息列表。

        Returns:
            提取出来的 FactItem 实例列表。
        """
        # TODO: 1. 构造强规 JSON 输出的 System Prompt，要求模型提取 FactItem
        # TODO: 2. 将对话历史序列化拼入 User Prompt
        # TODO: 3. 调用 LLMClient 请求模型，获取规范的 JSON 文本响应
        # TODO: 4. 执行反序列化 json.loads() 并使用 FactItem 逐个进行 Pydantic 校验转换
        raise NotImplementedError("TODO: 请实现 FactExtractor.extract_facts")

    def save_facts(self, user_id: str, facts: List[FactItem]) -> None:
        """多租户隔离写入：将提取出的原子事实写入该用户独立的数据分区中。

        Args:
            user_id: 用户唯一租户标识符。
            facts: 提取出的 Facts 列表。
        """
        # TODO: 1. 检查 self._isolated_db 是否已为 user_id 初始化分区，若无则初始化
        # TODO: 2. 遍历 facts，将 fact_key 与 fact_value 物理写入该用户的字典分区内，实现完全的租户物理隔离
        raise NotImplementedError("TODO: 请实现 FactExtractor.save_facts")

    def recall_facts(self, user_id: str, query: str, limit: int = 5) -> List[FactItem]:
        """多租户隔离检索：在对应用户的独立分区中执行语义/关键字匹配召回。

        Args:
            user_id: 用户唯一租户标识符。
            query: 用户当前提问。
            limit: 最大召回限制。

        Returns:
            召回的 FactItem 列表。
        """
        # TODO: 1. 检验租户权限，如果 user_id 不在 self._isolated_db 中，立即返回空列表，防止越权碰撞
        # TODO: 2. 遍历对应 user_id 分区下的 Facts，进行匹配筛选（本练习中可使用简易子串或单词匹配进行模拟）
        # TODO: 3. 构造 FactItem 并返回
        raise NotImplementedError("TODO: 请实现 FactExtractor.recall_facts")


# 调试主入口
if __name__ == "__main__":
    print("=== 启动 Day 59 长期记忆 Facts 提取与隔离调试入口 ===")
    
    extractor = FactExtractor()
    
    try:
        # 尝试触发 TODO 拦截
        print("\n尝试调用大模型提取事实...")
        import asyncio
        asyncio.run(extractor.extract_facts([{"role": "user", "content": "我的开发技术栈主要是 Python"}]))
    except NotImplementedError as e:
        print(f"❌ 捕获到预期的 TODO 拦截错误: {e}")
        print("💡 请学员根据 practice.py 中的 TODO 注释完成 FactExtractor 的提取与隔离逻辑。")
