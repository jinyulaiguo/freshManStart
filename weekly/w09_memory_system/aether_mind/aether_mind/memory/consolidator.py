r"""
AetherMind Memory Consolidator
==============================

设计方案:
---------
本模块负责长期记忆的时序一致性维护与艾宾浩斯时间遗忘衰减。
- **冲突消歧 (Conflict Resolution)**：
  当提取出新 Fact 时，首先检索 Qdrant 中该用户相似度 > 0.7 的旧 Facts。
  利用大模型分类器判断它们的关系：
  1. `conflict`（冲突）：新事实推翻了旧事实。将旧事实从向量库物理删除，并在 SQL 日志中记为 `deleted`；随后写入新事实。
  2. `redundant`（冗余）：语义重复。忽略新事实，将旧事实在向量库及 SQL 中的时间戳刷新为当前时间，权重重置为 1.0。
  3. `complement`（互补）：没有逻辑冲突。直接将新事实写入向量库并记录 SQL 日志。
- **艾宾浩斯遗忘衰减 (Ebbinghaus Decay)**：
  定期（或在单次交互后）根据公式 $W = W_{old} \times e^{-decay\_rate \times \Delta t}$
  更新该租户的所有活跃 Facts 的权重。若权重 $W < 0.2$，则从向量库中物理清除，
  并在 SQL 审计日志中标记为 `expired`。

结构说明:
---------
- ConsolidationAction: 消歧判断结果的 Pydantic 数据模型。
- MemoryConsolidator: 记忆整合控制类，封装消歧与时间衰减算法。
"""

import time
import math
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from aether_mind.storage.base import SQLStore, VectorStore
from aether_mind.utils.client import AetherMindLLMClient
from aether_mind.utils.logging import logger


class ConsolidationAction(BaseModel):
    """
    大模型消歧关系判定模型。
    """
    relationship: str = Field(
        ...,
        description="新旧事实的关系分类。可选值: conflict (新旧事实对立冲突), redundant (新事实是旧事实的重复或子集), complement (新旧事实相辅相成，无逻辑对立)"
    )
    reason: str = Field(
        ...,
        description="做出关系判定的技术理由与证据推导"
    )


class MemoryConsolidator:
    """
    长期事实记忆整合、冲突解决与艾宾浩斯遗忘衰减管理器。
    """

    def __init__(self, client: AetherMindLLMClient, decay_rate: float = 0.05):
        """
        初始化记忆整合器。

        Args:
            client (AetherMindLLMClient): 大模型客户端。
            decay_rate (float): 时间衰减系数。默认 0.05（单位：秒或小时，根据 delta_t 标定）。
        """
        self.client = client
        self.decay_rate = decay_rate

    async def consolidate_fact(
        self,
        user_id: str,
        new_fact_key: str,
        new_fact_value: str,
        db: SQLStore,
        vector_store: VectorStore
    ) -> None:
        """
        对单条新提取的 Fact 进行时序冲突消歧，并安全地写入存储后端。

        Args:
            user_id (str): 租户用户 ID。
            new_fact_key (str): 新事实 Key。
            new_fact_value (str): 新事实内容。
            db (SQLStore): 关系型数据库适配器。
            vector_store (VectorStore): 向量数据库适配器。
        """
        # 1. 计算新事实的特征向量并检索相似旧事实（阈值 0.7）
        new_vector = await self.client.get_embedding(new_fact_value, embed_type="query")
        
        # 仅检索该用户 active 状态的事实
        filter_dict = {"user_id": user_id, "status": "active"}
        candidates = await vector_store.search_points(
            collection="memory_collection",
            query_vector=new_vector,
            filter_dict=filter_dict,
            top_k=3
        )

        # 相似度高于 0.7 判定为潜在相关旧事实
        related_old_facts = [c for c in candidates if c["score"] >= 0.7]

        # 2. 如果没有发现语义相关的旧事实，作为新事实直接写入
        if not related_old_facts:
            await self._insert_new_fact(user_id, new_fact_key, new_fact_value, new_vector, db, vector_store)
            return

        # 3. 如果存在相关事实，调用大模型进行消歧决策
        old_fact_node = related_old_facts[0]  # 取相似度最高的一个
        old_fact_value = old_fact_node["payload"]["fact"]
        old_fact_id = old_fact_node["id"]
        old_fact_key = old_fact_node["payload"]["fact_key"]

        prompt = [
            {
                "role": "system",
                "content": (
                    "你是一个严密的关系型数据消歧与冲突判定引擎。\n"
                    "你需要对比一条已有的旧事实与一条新提取的事实，判断新事实对旧事实的影响，并输出 relationship 类型：\n"
                    "- conflict：新事实与旧事实在逻辑上直接对立或发生矛盾变动。新事实推翻了旧事实。例如：旧事实为'常用 Java'，新事实为'极其讨厌 Java 常用 Python'。\n"
                    "- redundant：新事实在语义上完全是旧事实的重复、子集，或新事实未提供任何增量价值。例如：旧事实为'用户常用 Python'，新事实为'用户在项目里用 Python 开发'。\n"
                    "- complement：新事实与旧事实不存在冲突，它们描述了用户在不同维度的偏好，应该共存。例如：旧事实为'用户常用 Python'，新事实为'用户喜欢使用 SQLite 作为本地测试库'。\n\n"
                    "必须严格按照指定 JSON Schema 结构输出，除 JSON 内容外不要包含任何自然语言文字。"
                )
            },
            {
                "role": "user",
                "content": (
                    f"【已有旧事实】: {old_fact_value}\n"
                    f"【新提取事实】: {new_fact_value}\n\n"
                    "请输出判定分类关系："
                )
            }
        ]

        try:
            decision = await self.client.request_llm_json(
                messages=prompt,
                response_model=ConsolidationAction,
                temperature=0.01
            )
            rel = decision.relationship
            logger.info(f"[消歧判定结果] '{new_fact_value}' vs '{old_fact_value}' -> 关系: {rel}, 原因: {decision.reason}")

            if rel == "conflict":
                # 3.1 冲突消解：删除旧事实（逻辑 + 物理），写入新事实
                await vector_store.delete_points("memory_collection", [old_fact_id])
                await db.save_memory_log(
                    user_id=user_id,
                    action="delete",
                    fact_key=old_fact_key,
                    fact_value=old_fact_value,
                    details=f"时序冲突被推翻，新事实: '{new_fact_value}'. 原因: {decision.reason}"
                )
                # 写入新事实
                await self._insert_new_fact(user_id, new_fact_key, new_fact_value, new_vector, db, vector_store)

            elif rel == "redundant":
                # 3.2 冗余更新：不写入新事实，直接刷新旧事实的时间戳和权重为 1.0
                payload = old_fact_node["payload"]
                payload["timestamp"] = float(time.time())
                payload["importance"] = 1.0  # 刷新权重
                
                # 重写回向量数据库
                await vector_store.upsert_points(
                    collection="memory_collection",
                    points=[{
                        "id": old_fact_id,
                        "vector": new_vector, # 可使用新计算的更精准向量
                        "payload": payload
                    }]
                )
                await db.save_memory_log(
                    user_id=user_id,
                    action="update",
                    fact_key=old_fact_key,
                    fact_value=old_fact_value,
                    details=f"检测到重复事实，刷新时戳与权重。原因: {decision.reason}"
                )

            else:
                # 3.3 互补：共存，直接插入新事实
                await self._insert_new_fact(user_id, new_fact_key, new_fact_value, new_vector, db, vector_store)

        except Exception as e:
            logger.error(f"[消歧判定失败] 降级为直接共存写入。错误: {str(e)}")
            await self._insert_new_fact(user_id, new_fact_key, new_fact_value, new_vector, db, vector_store)

    async def _insert_new_fact(
        self,
        user_id: str,
        fact_key: str,
        fact_value: str,
        vector: List[float],
        db: SQLStore,
        vector_store: VectorStore
    ) -> None:
        """
        核心辅助：向存储端安全插入新事实。
        """
        timestamp = float(time.time())
        payload = {
            "user_id": user_id,
            "type": "fact",
            "fact_key": fact_key,
            "fact": fact_value,
            "importance": 1.0,  # 初始权重设为 1.0
            "confidence": 1.0,
            "timestamp": timestamp,
            "status": "active",
            "version": 1
        }
        # 写入向量库
        await vector_store.upsert_points(
            collection="memory_collection",
            points=[{
                "vector": vector,
                "payload": payload
            }]
        )
        # 记录审计日志
        await db.save_memory_log(
            user_id=user_id,
            action="insert",
            fact_key=fact_key,
            fact_value=fact_value,
            details="原子偏好事实首次插入长期记忆向量库"
        )
        logger.info(f"[事实写入成功] 租户 {user_id} 新事实: '{fact_value}'")

    async def apply_ebbinghaus_decay(
        self,
        user_id: str,
        db: SQLStore,
        vector_store: VectorStore,
        current_time: Optional[float] = None
    ) -> None:
        """
        扫描当前用户所有 active 状态的事实记忆，根据最后修改时间进行艾宾浩斯遗忘权重衰减。
        若权重降低至 0.2 以下，则物理逐出向量库并标记 SQL 状态为 expired。

        Args:
            user_id (str): 用户 ID。
            db (SQLStore): 关系数据库。
            vector_store (VectorStore): 向量数据库。
            current_time (Optional[float]): 当前时间戳，主要用于测试中模拟未来时间。
        """
        ref_time = current_time or time.time()
        
        # 1. 召回该用户的所有活跃事实
        # 采用随机的高维全零特征向量进行无差别召回所有（可使用 top_k = 100 覆盖）
        dummy_vector = [0.0] * 1536
        results = await vector_store.search_points(
            collection="memory_collection",
            query_vector=dummy_vector,
            filter_dict={"user_id": user_id, "status": "active"},
            top_k=100
        )

        for node in results:
            payload = node["payload"]
            last_timestamp = payload.get("timestamp", ref_time)
            
            # 计算时差（秒数）
            delta_t = ref_time - last_timestamp
            if delta_t < 0:
                delta_t = 0
                
            # 2. 艾宾浩斯指数衰减公式计算
            # W = W_old * e^(-decay_rate * delta_t)
            old_weight = payload.get("importance", 1.0)
            new_weight = old_weight * math.exp(-self.decay_rate * delta_t)
            
            if new_weight < 0.2:
                # 3. 淘汰驱逐：权重低于 0.2，从向量库物理清除
                node_id = node["id"]
                await vector_store.delete_points("memory_collection", [node_id])
                
                # 记录审计日志
                await db.save_memory_log(
                    user_id=user_id,
                    action="decay_evict",
                    fact_key=payload["fact_key"],
                    fact_value=payload["fact"],
                    details=f"时间衰减权重过低被驱逐 (最终权重: {new_weight:.4f}, 时差: {delta_t}s)"
                )
                logger.info(f"[记忆淘汰驱逐] Fact ID {node_id} 权重过低 ({new_weight:.4f}) 被彻底移出")
            else:
                # 4. 更新权重：权重更新，写回向量库
                node_id = node["id"]
                payload["importance"] = new_weight
                await vector_store.upsert_points(
                    collection="memory_collection",
                    points=[{
                        "id": node_id,
                        "vector": None, # 只更新 payload，不改变原有向量
                        "payload": payload
                    }]
                )
                logger.debug(f"[记忆衰减更新] Fact ID {node_id} 权重更新为 {new_weight:.4f}")
