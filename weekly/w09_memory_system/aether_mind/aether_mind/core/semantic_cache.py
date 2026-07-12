"""
AetherMind Production Semantic Cache Engine
============================================

设计方案:
---------
本模块实现了生产级三层瀑布式语义缓存（Semantic Cache）微引擎。
取代原有基于 SQL 精确匹配（input_data = ?）的伪缓存方案，
实现真正意义上的"语义等价命中"：
  "RAG是什么" ≈ "什么是RAG" → L2 语义层可命中缓存

三层缓存架构:
--------------
  L1 精确哈希缓存（Python in-memory dict + LRU）:
    - key = f"{user_id}:{SHA256(normalize(query))}"
    - 命中延迟 < 1ms
    - 支持 TTL 超期自动 miss 与 LRU 容量驱逐

  L2 向量语义缓存（Qdrant ANN 检索）:
    - 对 Query Embedding 执行 ANN 检索
    - 相似度 cosine_sim > SIM_THRESHOLD（默认 0.92）则命中
    - 独立 Collection：semantic_cache_collection
    - 多租户过滤：filter_dict={"user_id": user_id}
    - 支持 TTL：命中条目若超期则忽略并异步删除

  L3 LLM 兜底推理:
    - 正常推理流程，结果由调用方通过 put() 双写回 L1+L2
    - put() 本身是同步操作，调用方需用 create_task 包裹以保持非阻塞

结构说明:
---------
- SemanticCacheEngine: 三层缓存微引擎主类，对外暴露 get() 与 put()。
- _L1Entry: L1 缓存条目数据结构（内含写入时间戳用于 TTL 判断）。
"""

import re
import time
import uuid
import hashlib
import asyncio
from collections import OrderedDict
from typing import Optional, Tuple, List
from dataclasses import dataclass, field

from aether_mind.utils.client import AetherMindLLMClient
from aether_mind.storage.base import VectorStore
from aether_mind.utils.logging import logger
from aether_mind.config import settings


# ===================================================================
# 内部数据结构
# ===================================================================

@dataclass
class _L1Entry:
    """
    L1 精确哈希缓存的单条记录。

    Attributes:
        response (str): 缓存的 LLM 回复文本。
        written_at (float): 写入的 UNIX 时间戳（秒），用于 TTL 判断。
    """
    response: str
    written_at: float = field(default_factory=time.time)


# ===================================================================
# SemanticCacheEngine 主类
# ===================================================================

class SemanticCacheEngine:
    """
    生产级三层瀑布式语义缓存微引擎。

    使用方式（在 engine.py 中装配）:
        cache_engine = SemanticCacheEngine(client, vector_store)

        # 请求处理时
        result = await cache_engine.get(user_id, query)
        if result:
            cached_text, hit_level = result
            # 直接流式回显 cached_text

        # LLM 推理完成后（非阻塞后台双写）
        asyncio.create_task(cache_engine.put(user_id, query, final_reply))
    """

    # Qdrant 语义缓存专用集合名称（与 knowledge/memory 物理隔离）
    CACHE_COLLECTION = "semantic_cache_collection"

    def __init__(
        self,
        client: AetherMindLLMClient,
        vector_store: VectorStore,
    ):
        """
        初始化语义缓存引擎。

        Args:
            client (AetherMindLLMClient): 统一 LLM + Embedding 客户端。
            vector_store (VectorStore): Qdrant 向量数据库适配器。
        """
        self.client = client
        self.vector_store = vector_store

        # 从全局 settings 读取缓存配置项
        self.enabled: bool = settings.semantic_cache_enabled
        self.sim_threshold: float = settings.semantic_cache_threshold
        self.ttl_seconds: int = settings.semantic_cache_ttl_seconds
        self.l1_max_size: int = settings.semantic_cache_l1_max_size

        # L1 缓存：使用 OrderedDict 实现 LRU 驱逐策略
        # key: "{user_id}:{sha256_hash}"  value: _L1Entry
        self._l1_cache: OrderedDict[str, _L1Entry] = OrderedDict()

        logger.info(
            f"[SemanticCache] 初始化完成。enabled={self.enabled}, "
            f"threshold={self.sim_threshold}, ttl={self.ttl_seconds}s, "
            f"l1_max={self.l1_max_size}"
        )

    # ---------------------------------------------------------------
    # 公共接口
    # ---------------------------------------------------------------

    async def get(
        self,
        user_id: str,
        query: str
    ) -> Optional[Tuple[str, str]]:
        """
        按 L1 → L2 顺序查询缓存。

        Args:
            user_id (str): 当前用户 ID（用于多租户隔离）。
            query (str): 用户原始提问文本。

        Returns:
            Optional[Tuple[str, str]]:
                命中时返回 (cached_response, hit_level)，
                hit_level 为 "L1_HIT" 或 "L2_HIT"。
                未命中时返回 None。
        """
        if not self.enabled:
            return None

        # --- L1 精确哈希查询 ---
        l1_result = self._l1_get(user_id, query)
        if l1_result is not None:
            logger.info(f"[SemanticCache] L1_HIT | user={user_id} query='{query[:30]}...'")
            return l1_result, "L1_HIT"

        # --- L2 向量语义查询 ---
        l2_result = await self._l2_get(user_id, query)
        if l2_result is not None:
            logger.info(f"[SemanticCache] L2_HIT | user={user_id} query='{query[:30]}...'")
            # L2 命中时，顺手回填 L1（下次同 query 直接 L1 命中）
            self._l1_put(user_id, query, l2_result)
            return l2_result, "L2_HIT"

        logger.info(f"[SemanticCache] MISS | user={user_id} query='{query[:30]}...'")
        return None

    async def put(
        self,
        user_id: str,
        query: str,
        response: str
    ) -> None:
        """
        将 LLM 回复双写回 L1 + L2 缓存（建议由调用方用 create_task 非阻塞调用）。

        Args:
            user_id (str): 当前用户 ID。
            query (str): 用户原始提问文本。
            response (str): LLM 生成的最终回复文本。
        """
        if not self.enabled:
            return

        # 1. 同步写 L1（in-memory，无网络 I/O，可直接执行）
        self._l1_put(user_id, query, response)

        # 2. 异步写 L2（需要 Embedding 网络调用 + Qdrant 写入）
        await self._l2_put(user_id, query, response)

    async def init_collection(self) -> None:
        """
        初始化 Qdrant 语义缓存专用 Collection（若不存在则自动创建）。
        应在 engine.initialize() 中调用。
        """
        try:
            await self.vector_store.upsert_points(self.CACHE_COLLECTION, [])
            logger.info(f"[SemanticCache] Qdrant Collection '{self.CACHE_COLLECTION}' 就绪。")
        except Exception:
            # 首次调用时 collection 不存在，upsert 会触发隐式创建
            pass

    # ---------------------------------------------------------------
    # L1 精确哈希缓存（内部方法）
    # ---------------------------------------------------------------

    @staticmethod
    def _normalize(query: str) -> str:
        """
        规范化 Query：折叠空白 + 转小写，消除无意义的字符差异。

        例如："  什么是 RAG  " → "什么是 rag"
        """
        return re.sub(r'\s+', ' ', query.strip().lower())

    def _build_l1_key(self, user_id: str, query: str) -> str:
        """
        构建 L1 缓存 key："{user_id}:{SHA256(normalize(query))}"

        Args:
            user_id (str): 用户 ID（多租户隔离前缀）。
            query (str): 原始 Query 文本。

        Returns:
            str: 缓存唯一键。
        """
        normalized = self._normalize(query)
        hash_hex = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        return f"{user_id}:{hash_hex}"

    def _l1_get(self, user_id: str, query: str) -> Optional[str]:
        """
        查询 L1 内存缓存。

        流程：
        1. 构建 key 并查找 OrderedDict
        2. 若命中，检查 TTL 是否超期；超期则删除并返回 None
        3. 未超期则将该 key 移至末尾（标记为最近访问，LRU 策略）

        Args:
            user_id (str): 用户 ID。
            query (str): Query 文本。

        Returns:
            Optional[str]: 命中时返回缓存文本，未命中或超期返回 None。
        """
        key = self._build_l1_key(user_id, query)
        entry = self._l1_cache.get(key)

        if entry is None:
            return None

        # TTL 检查：超期则从 L1 驱逐
        if time.time() - entry.written_at > self.ttl_seconds:
            del self._l1_cache[key]
            logger.debug(f"[SemanticCache] L1 TTL 超期驱逐: key={key[:20]}...")
            return None

        # LRU：将命中 key 移至 OrderedDict 末尾（表示最近访问）
        self._l1_cache.move_to_end(key)
        return entry.response

    def _l1_put(self, user_id: str, query: str, response: str) -> None:
        """
        写入 L1 内存缓存，并在容量超限时驱逐最久未访问的条目（LRU）。

        Args:
            user_id (str): 用户 ID。
            query (str): Query 文本。
            response (str): LLM 回复文本。
        """
        key = self._build_l1_key(user_id, query)

        # 若 key 已存在，更新并移至末尾
        self._l1_cache[key] = _L1Entry(response=response)
        self._l1_cache.move_to_end(key)

        # LRU 容量驱逐：超出上限时弹出最头部（最久未访问）的条目
        while len(self._l1_cache) > self.l1_max_size:
            evicted_key, _ = self._l1_cache.popitem(last=False)
            logger.debug(f"[SemanticCache] L1 LRU 驱逐: key={evicted_key[:20]}...")

    # ---------------------------------------------------------------
    # L2 向量语义缓存（内部方法）
    # ---------------------------------------------------------------

    async def _l2_get(self, user_id: str, query: str) -> Optional[str]:
        """
        查询 L2 Qdrant 向量语义缓存。

        流程：
        1. 调用 Embedding API 将 query 向量化
        2. 在 semantic_cache_collection 中执行 ANN 检索（多租户过滤）
        3. 取相似度最高的候选；若 score > threshold 且未超 TTL 则返回缓存文本
        4. 若超 TTL，则异步驱逐该过期向量点并返回 None

        Args:
            user_id (str): 用户 ID（用于 Qdrant Payload 过滤，多租户隔离）。
            query (str): Query 文本。

        Returns:
            Optional[str]: 命中时返回缓存文本，未命中/超期/错误返回 None。
        """
        try:
            # 步骤 1：生成 Query 向量
            query_vector = await self.client.get_embedding(query, embed_type="query")

            # 步骤 2：Qdrant ANN 检索（仅搜当前 user_id 的缓存，防止租户间污染）
            hits = await self.vector_store.search_points(
                collection=self.CACHE_COLLECTION,
                query_vector=query_vector,
                filter_dict={"user_id": user_id},
                top_k=1
            )

            if not hits:
                return None

            best = hits[0]
            score: float = best.get("score", 0.0)
            payload: dict = best.get("payload", {})

            # 步骤 3：相似度阈值检查
            if score < self.sim_threshold:
                logger.debug(
                    f"[SemanticCache] L2 相似度未达阈值: score={score:.4f} < {self.sim_threshold}"
                )
                return None

            # 步骤 4：TTL 检查
            created_at: float = payload.get("created_at", 0.0)
            if time.time() - created_at > self.ttl_seconds:
                # 过期：异步删除该向量点（非阻塞，不影响当前请求）
                expired_id = best.get("id")
                asyncio.create_task(
                    self.vector_store.delete_points(self.CACHE_COLLECTION, [expired_id])
                )
                logger.info(
                    f"[SemanticCache] L2 TTL 超期，异步删除过期向量点 id={expired_id}"
                )
                return None

            logger.info(
                f"[SemanticCache] L2 命中: score={score:.4f}, "
                f"original_query='{payload.get('original_query', '')[:30]}'"
            )
            return payload.get("cached_response")

        except Exception as e:
            # 缓存层异常不能影响主流程，降级为 MISS
            logger.warning(f"[SemanticCache] L2 查询异常，降级 MISS: {str(e)}")
            return None

    async def _l2_put(self, user_id: str, query: str, response: str) -> None:
        """
        将回复结果写入 L2 Qdrant 语义缓存。

        流程：
        1. 调用 Embedding API 将 query 向量化
        2. 构建包含 user_id、原始 query、回复文本、写入时间的 Payload
        3. Upsert 到 semantic_cache_collection

        Args:
            user_id (str): 用户 ID。
            query (str): 用户原始 Query 文本。
            response (str): LLM 最终回复文本。
        """
        try:
            # 步骤 1：向量化 Query（作为 ANN 检索的特征向量）
            query_vector = await self.client.get_embedding(query, embed_type="query")

            # 步骤 2：构建 Payload（包含多租户 key 和 TTL 时间戳）
            payload = {
                "user_id": user_id,
                "original_query": query,
                "cached_response": response,
                "created_at": time.time(),   # UNIX 时间戳，用于 TTL 超期判断
                "hit_count": 0               # 命中次数（可用于后续热度统计）
            }

            # 步骤 3：生成唯一 ID（避免重复写入同一 query 时 ID 冲突）
            point_id = str(uuid.uuid5(
                uuid.NAMESPACE_DNS,
                f"{user_id}:{self._normalize(query)}"
            ))

            await self.vector_store.upsert_points(
                collection=self.CACHE_COLLECTION,
                points=[{
                    "id": point_id,
                    "vector": query_vector,
                    "payload": payload
                }]
            )
            logger.debug(
                f"[SemanticCache] L2 写入成功: user={user_id}, "
                f"query='{query[:30]}...', point_id={point_id}"
            )
        except Exception as e:
            # 缓存写入失败不能影响主流程
            logger.warning(f"[SemanticCache] L2 写入异常（忽略）: {str(e)}")
