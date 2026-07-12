"""
AetherMind Long Term Memory Manager
===================================

设计方案:
---------
该模块负责长期记忆事实（Facts）的生命周期起点：实体级事实的抽取与基于多租户隔离的向量检索。
- **增量 Facts 提取**：使用大模型以 Pydantic 结构化约束（`FactExtractionResult`）
  从最新的会话对话中抽取原子级事实键值对，描述用户特定的偏好、习惯与背景。
- **租户物理隔离**：所有的 Facts 写入和检索均强制绑定 `user_id`。
  检索时，使用 `user_id` 构建 Qdrant 过滤器（Payload Filter），确保不同用户的记忆在向量检索层面 100% 物理隔离。

结构说明:
---------
- FactExtractionItem: 单条抽取事实的 Pydantic 模型。
- FactExtractionResult: 批量事实抽取包装的 Pydantic 模型。
- LongMemoryManager: 长期记忆管理类，提供事实提取与租户隔离的多路向量召回。

数据流向:
---------
1. 对话流转结束后，主引擎将单次交互文本传入 `extract_facts()`。
2. LLM 解析输入，提取原子事实列表，返回 `List[FactExtractionItem]`。
3. 检索时，调用 `retrieve_relevant_facts()`，计算 Query 的 Embedding，
   在 Qdrant 中使用 `user_id` 和 `status='active'` 过滤器执行 Cosine 相似度搜索。
"""

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from aether_mind.storage.base import VectorStore
from aether_mind.utils.client import AetherMindLLMClient
from aether_mind.utils.logging import logger


class FactExtractionItem(BaseModel):
    """
    单条原子事实数据提取模型。
    """
    fact_key: str = Field(
        ...,
        description="蛇形下划线键名，精准标识该事实主题。例如: user_framework_preference, user_code_style"
    )
    fact_value: str = Field(
        ...,
        description="客观、独立的事实陈述，不要使用人称代词（如'我'、'你'），使用'用户'。例如: '用户常用 Python 作为开发语言'"
    )


class FactExtractionResult(BaseModel):
    """
    事实提取结果的包装模型，强制输出 JSON 格式。
    """
    facts: List[FactExtractionItem] = Field(
        default_factory=list,
        description="从对话历史中增量提取的事实实体列表。如果没有提取到新事实，返回空列表。"
    )


class LongMemoryManager:
    """
    长期记忆事实提取与多租户隔离向量化召回管理器。
    """

    def __init__(self, client: AetherMindLLMClient):
        """
        初始化长期记忆管理器。

        Args:
            client (AetherMindLLMClient): 统一大模型客户端实例。
        """
        self.client = client

    async def extract_facts(self, dialogue: str) -> List[FactExtractionItem]:
        """
        利用大模型从给定对话片段中，增量提取出用户事实和偏好记录。

        Args:
            dialogue (str): 对话内容文本。

        Returns:
            List[FactExtractionItem]: 抽取出的原子事实列表。
        """
        # 1. 构造事实抽取 Prompt
        prompt = [
            {
                "role": "system",
                "content": (
                    "你是一个资深的用户画像事实抽取专家。\n"
                    "请从给定的用户与助理的对话片段中，抽取出关于用户的长期事实（Facts）与偏好（Preferences）。\n\n"
                    "抽取规范：\n"
                    "1. 事实键名 (fact_key)：采用全小写蛇形命名（如 user_database_preference）。\n"
                    "2. 事实陈述 (fact_value)：用客观、独立的第三人称陈述句，禁止包含人称代词（如'我'、'你'），统一用'用户'代替。\n"
                    "3. 仅提取与技术偏好、研究领域、框架选型、开发习惯等相关的长期事实，忽略天气、打招呼等瞬时信息。\n"
                    "4. 如果没有任何符合的长期事实，则 facts 列表输出为空。\n"
                    "5. 必须严格按照指定 JSON Schema 输出格式，不要包含任何自然语言回复前缀或包裹围栏。"
                )
            },
            {
                "role": "user",
                "content": f"【待抽取的对话片段】\n{dialogue}\n\n请输出提取的事实结果："
            }
        ]

        try:
            # 2. 调用 JSON 结构化提取接口进行反序列化
            result = await self.client.request_llm_json(
                messages=prompt,
                response_model=FactExtractionResult,
                temperature=0.1
            )
            logger.info(f"[长期事实提取] 从对话中提取出 {len(result.facts)} 条新 Facts。")
            return result.facts
        except Exception as e:
            logger.error(f"[长期事实提取异常] 提取 Facts 失败: {str(e)}")
            return []

    async def retrieve_relevant_facts(
        self,
        user_id: str,
        query: str,
        vector_store: VectorStore,
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """
        基于多租户隔离，检索出与当前查询最相关的用户事实。

        Args:
            user_id (str): 租户用户唯一 ID。
            query (str): 查询文本。
            vector_store (VectorStore): 向量数据库连接适配器。
            top_k (int): 返回检索条目上限。

        Returns:
            List[Dict[str, Any]]: 召回事实列表，含评分及 payload 元数据。
        """
        # 1. 计算 Query Embedding (生成 1536 维特征向量)
        query_vector = await self.client.get_embedding(query, embed_type="query")

        # 2. 构造租户隔离 Filter：必须匹配 user_id 且 status 为 'active'
        filter_dict = {
            "user_id": user_id,
            "status": "active"
        }

        # 3. 从向量数据库 Qdrant 中执行近邻匹配检索
        results = await vector_store.search_points(
            collection="memory_collection",
            query_vector=query_vector,
            filter_dict=filter_dict,
            top_k=top_k
        )

        logger.info(f"[长期记忆检索] 租户 {user_id} 召回了 {len(results)} 条相关事实")
        return results
