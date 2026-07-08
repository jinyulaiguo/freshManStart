"""
微引擎 5：Qdrant 向量存储与元数据联合索引管理 (QdrantVectorStore)

设计方案：
==========
1. 设计意图：
   在大规模 RAG 知识库中，暴力相似度检索会导致响应时延剧烈暴涨，且无法满足多租户数据隔离与细粒度权限控制的需求。
   本引擎封装了 Qdrant 客户端的高级操作：
   - 自动探测本地 Docker 实例，如连接失败自动降级到 SQLite 支持的进程内内存模式 (:memory:)，确保零配置启动。
   - 提供 HNSW 索引参数调优接口（m, ef_construct），以加速高维向量检索速度。
   - 自动为关键元数据字段（user_id, permission_level, category, created_time_ts等）构建相应的 Payload 索引（Payload Indexing）。
   - 将 Pydantic 的 MetadataFilter 精准转换为 Qdrant 的底层复合 Filter，实现在底层 HNSW 检索时的联合 Pre-Filtering，保障权限隔离与高吞吐检索性能。

2. 关键方法：
   - create_collection(): 生命周期管理，配置 HNSW 参数与距离度量
   - create_payload_indexes(): 建立 Payload 索引优化查询
   - upsert_chunks(): 批量并发写入点和 Payload 数据
   - search_dense(): Pre-Filtering 向量联合检索
   - delete_by_document_id(): 根据 document_id 进行级联删除

使用方式：
    python -m weekly.w06_embedding_and_vector_db.project.vector_store
"""
from __future__ import annotations

import time
import datetime
from typing import Optional
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    HnswConfigDiff,
    PointStruct,
    SearchParams,
    CollectionStatus,
    Filter,
    FieldCondition,
    MatchValue,
    MatchAny,
    Range,
    PayloadSchemaType
)

from weekly.w06_embedding_and_vector_db.project.models import (
    ChunkWithVector,
    MetadataFilter,
    SearchResult
)


class QdrantVectorStore:
    """基于 Qdrant 的高性能向量存储与 Payload 联合过滤引擎"""

    def __init__(self, url: str | None = None, port: int = 6333, location: str | None = None) -> None:
        """初始化 Qdrant 客户端，具备自适应防错降级机制。

        如果指定了 location，则直接使用；
        否则优先连接本地 http://localhost:6333，连接失败时平滑降级至内存模式 (:memory:)。
        """
        self.is_memory_mode = False
        
        # 优先使用显式指定的内存模式
        if location == ":memory:":
            self.client = QdrantClient(location=":memory:")
            self.is_memory_mode = True
            print("💡 [VectorStore] Qdrant 客户端已启动为指定内存模式 (:memory:)")
            return

        target_url = url or "http://127.0.0.1"
        try:
            # 缩短超时时间以便快速检测 Docker 是否存活
            self.client = QdrantClient(url=target_url, port=port, timeout=2.0)
            # 发起探测请求
            self.client.get_collections()
            print(f"🚀 [VectorStore] Qdrant 客户端已成功连接到 Docker 服务端 ({target_url}:{port})")
        except Exception:
            print(f"⚠️ [VectorStore] 连接 Qdrant 服务端失败，已平滑、自适应降级到 SQLite 内存模式 (:memory:)")
            self.client = QdrantClient(location=":memory:")
            self.is_memory_mode = True

    def create_collection(
        self,
        collection_name: str,
        dimension: int = 1536,
        distance: Distance = Distance.COSINE,
        m: int = 16,
        ef_construct: int = 200
    ) -> None:
        """物理重建或初始化 Qdrant 集合，并配置 HNSW 索引调优参数。

        Args:
            collection_name: 集合名称
            dimension: 向量维度（默认 1536，MiniMax / OpenAI 大模型标准）
            distance: 相似度距离度量，默认余弦相似度 COSINE
            m: HNSW 图中每个节点的最大连接边数（默认 16，越大索引越密检索越慢但越准）
            ef_construct: 构建索引时的邻居搜索范围（默认 200，越大构建越慢检索越准）
        """
        # 如果集合已存在，先删除重建
        if self.client.collection_exists(collection_name):
            self.client.delete_collection(collection_name)
            print(f"🗑️ [VectorStore] 集合 {collection_name} 已存在，已物理删除重建")

        # 配置 HNSW 参数
        hnsw_config = HnswConfigDiff(
            m=m,
            ef_construct=ef_construct,
            on_disk=False  # 内存模式不支持磁盘存储，Docker 模式下视配置而定
        )

        self.client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=dimension, distance=distance),
            hnsw_config=hnsw_config
        )
        print(
            f"✅ [VectorStore] 集合 {collection_name} 创建成功。维度: {dimension}, "
            f"距离度量: {distance.value}, HNSW Config: M={m}, ef_construct={ef_construct}"
        )

    def create_payload_indexes(self, collection_name: str) -> None:
        """在 Payload 常用字段上显式创建过滤索引（Payload Index），提升 Pre-Filtering 速度。

        Args:
            collection_name: 集合名称
        """
        # local SQLite 内存模式不支持创建 payload 索引（但在真实 server 模式中是有效的，会发出 Warning 但不报错）
        # Keyword 索引：适合 category 精确分类过滤
        self.client.create_payload_index(
            collection_name=collection_name,
            field_name="category",
            field_schema=PayloadSchemaType.KEYWORD
        )
        
        # Keyword 索引：适合 user_id 租户隔离精确过滤
        self.client.create_payload_index(
            collection_name=collection_name,
            field_name="user_id",
            field_schema=PayloadSchemaType.KEYWORD
        )

        # Keyword 索引：适合 author 精确过滤
        self.client.create_payload_index(
            collection_name=collection_name,
            field_name="author",
            field_schema=PayloadSchemaType.KEYWORD
        )

        # Integer 索引：适合 permission_level 权限级别范围过滤
        self.client.create_payload_index(
            collection_name=collection_name,
            field_name="permission_level",
            field_schema=PayloadSchemaType.INTEGER
        )

        # Float 索引：适合 created_time_ts 时间戳范围过滤
        self.client.create_payload_index(
            collection_name=collection_name,
            field_name="created_time_ts",
            field_schema=PayloadSchemaType.FLOAT
        )
        print(f"⚡ [VectorStore] 已为集合 {collection_name} 关键元数据字段构建 Payload Index")

    def upsert_chunks(self, collection_name: str, chunks_with_vectors: list[ChunkWithVector]) -> None:
        """将向量及对应的 Chunk 详细 Payload 批量 upsert 到 Qdrant 数据库中。

        Args:
            collection_name: 集合名称
            chunks_with_vectors: 附带高维向量的 Chunk 列表
        """
        if not chunks_with_vectors:
            return

        points = []
        for cv in chunks_with_vectors:
            chunk = cv.chunk
            
            # 尝试将 ISO 时间解析为 float 时间戳以便进行 Range 过滤
            created_time_ts = None
            if chunk.created_time:
                try:
                    cleaned_time = chunk.created_time.replace("Z", "+00:00")
                    created_time_ts = datetime.datetime.fromisoformat(cleaned_time).timestamp()
                except Exception:
                    pass

            # 组装 Payload 字典
            payload = {
                "chunk_id": chunk.chunk_id,
                "document_id": chunk.document_id,
                "content": chunk.content,
                "title": chunk.title,
                "section_path": chunk.section_path,
                "source_path": chunk.source_path,
                "author": chunk.author,
                "created_time": chunk.created_time,
                "created_time_ts": created_time_ts,  # 用于高效数值范围过滤
                "page_number": chunk.page_number,
                "token_length": chunk.token_length,
                "char_length": chunk.char_length,
                "hash": chunk.hash,
                "category": chunk.category,
                "permission_level": chunk.permission_level,
                "user_id": chunk.user_id,
            }
            
            # 使用 chunk_id 字符串生成点 ID，Qdrant 接受 UUID 字符串或无符号 64 位整数
            import uuid
            point_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, chunk.chunk_id))

            points.append(
                PointStruct(
                    id=point_uuid,
                    vector=cv.vector,
                    payload=payload
                )
            )

        # 执行 Qdrant 批量写入
        self.client.upsert(
            collection_name=collection_name,
            points=points,
            wait=True  # 阻塞等待直到数据刷盘写入
        )
        print(f"📥 [VectorStore] 成功写入 {len(points)} 个知识切片到集合 {collection_name}")

    def _convert_metadata_filter(self, meta_filter: Optional[MetadataFilter]) -> Optional[Filter]:
        """将 Pydantic 过滤契约转换为 Qdrant 专用的 Filter 条件。

        Args:
            meta_filter: 业务 MetadataFilter 对象

        Returns:
            Optional[Filter]: Qdrant Filter 复合对象
        """
        if not meta_filter:
            return None

        conditions = []

        # 权限过滤：只能查询小于等于用户最大权限级别的文档
        conditions.append(
            FieldCondition(
                key="permission_level",
                range=Range(lte=meta_filter.max_permission_level)
            )
        )

        # 多租户租户隔离：如果指定了 user_id
        if meta_filter.user_id:
            conditions.append(
                FieldCondition(
                    key="user_id",
                    match=MatchValue(value=meta_filter.user_id)
                )
            )

        # 文档领域分类过滤
        if meta_filter.categories:
            conditions.append(
                FieldCondition(
                    key="category",
                    match=MatchAny(any=meta_filter.categories)
                )
            )

        # 作者过滤
        if meta_filter.authors:
            conditions.append(
                FieldCondition(
                    key="author",
                    match=MatchAny(any=meta_filter.authors)
                )
            )

        # 时间戳过滤
        if meta_filter.created_after or meta_filter.created_before:
            range_cond = Range()
            has_time_filter = False
            if meta_filter.created_after:
                try:
                    cleaned_after = meta_filter.created_after.replace("Z", "+00:00")
                    range_cond.gte = datetime.datetime.fromisoformat(cleaned_after).timestamp()
                    has_time_filter = True
                except Exception:
                    pass
            if meta_filter.created_before:
                try:
                    cleaned_before = meta_filter.created_before.replace("Z", "+00:00")
                    range_cond.lte = datetime.datetime.fromisoformat(cleaned_before).timestamp()
                    has_time_filter = True
                except Exception:
                    pass
            
            if has_time_filter:
                conditions.append(
                    FieldCondition(
                        key="created_time_ts",
                        range=range_cond
                    )
                )

        return Filter(must=conditions) if conditions else None

    def search_dense(
        self,
        collection_name: str,
        query_vector: list[float],
        limit: int = 5,
        filters: Optional[MetadataFilter] = None
    ) -> list[SearchResult]:
        """执行 Pre-Filtering 向量联合检索。

        Args:
            collection_name: 集合名称
            query_vector: 用户查询向量
            limit: 召回的 Top-K 数量
            filters: 权限/元数据过滤条件

        Returns:
            list[SearchResult]: 结构化检索结果列表
        """
        # 1. 转换过滤条件
        query_filter = self._convert_metadata_filter(filters)

        # 2. 调用 Qdrant query_points 底层联合检索，并在 search_params 中配置合理检索范围
        search_params = SearchParams(
            hnsw_ef=64  # 查询阶段 of ef，越大越精准但越慢
        )
        
        results = self.client.query_points(
            collection_name=collection_name,
            query=query_vector,
            query_filter=query_filter,
            search_params=search_params,
            limit=limit
        )

        # 3. 封装为业务 SearchResult 对象
        search_results = []
        for rank, point in enumerate(results.points, start=1):
            payload = point.payload or {}
            search_results.append(
                SearchResult(
                    chunk_id=payload.get("chunk_id", ""),
                    content=payload.get("content", ""),
                    score=round(float(point.score), 4),
                    source_path=payload.get("source_path", ""),
                    title=payload.get("title", ""),
                    section_path=payload.get("section_path", ""),
                    rank=rank,
                    strategy="dense"
                )
            )

        return search_results

    def delete_by_document_id(self, collection_name: str, doc_id: str) -> None:
        """根据 document_id 执行级联物理删除，支持冷启动去重覆盖与增量更新。

        Args:
            collection_name: 集合名称
            doc_id: 文档唯一标识符
        """
        delete_filter = Filter(
            must=[
                FieldCondition(
                    key="document_id",
                    match=MatchValue(value=doc_id)
                )
            ]
        )
        self.client.delete(
            collection_name=collection_name,
            points_selector=delete_filter
        )
        print(f"🗑️ [VectorStore] 已将文档 {doc_id} 相关的全部向量点从集合 {collection_name} 中物理清除")

    def delete_collection(self, collection_name: str) -> None:
        """彻底注销删除一个集合。

        Args:
            collection_name: 集合名称
        """
        if self.client.collection_exists(collection_name):
            self.client.delete_collection(collection_name)
            print(f"🗑️ [VectorStore] 集合 {collection_name} 已彻底销毁释放空间")


# ══════════════════════════════════════════════════════════════════════════════
# 主入口：向量存储功能测试演示
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 70)
    print("  微引擎 5：Qdrant 向量存储联合检索 — 功能演示")
    print("=" * 70)

    # 1. 初始化客户端，使用内存模式模拟，避免本地 Docker 强依赖
    store = QdrantVectorStore(location=":memory:")
    col_name = "test_col"
    
    # 2. 创建集合与 Payload 索引
    store.create_collection(col_name, dimension=4, m=16, ef_construct=100)
    store.create_payload_indexes(col_name)

    # 3. 准备几个带向量与 Payload 的 Chunk
    from weekly.w06_embedding_and_vector_db.project.models import Chunk
    
    cvs = [
        ChunkWithVector(
            chunk=Chunk(
                chunk_id="chunk_1", document_id="doc_A", content="Hello public content",
                category="AI", permission_level=1, user_id="user_1", created_time="2026-07-01T00:00:00Z"
            ),
            vector=[1.0, 0.0, 0.0, 0.0]
        ),
        ChunkWithVector(
            chunk=Chunk(
                chunk_id="chunk_2", document_id="doc_A", content="Confidential AI content",
                category="AI", permission_level=3, user_id="user_1", created_time="2026-07-02T00:00:00Z"
            ),
            vector=[0.9, 0.1, 0.0, 0.0]
        ),
        ChunkWithVector(
            chunk=Chunk(
                chunk_id="chunk_3", document_id="doc_B", content="User 2 private content",
                category="Database", permission_level=1, user_id="user_2", created_time="2026-07-03T00:00:00Z"
            ),
            vector=[0.0, 1.0, 0.0, 0.0]
        ),
    ]

    # 4. 批量 Upsert
    store.upsert_chunks(col_name, cvs)

    # 5. 执行 Pre-Filtering 联合条件检索
    # 模拟 user_1 发起查询，只拥有 Level 2 的读取权限，期望查到 chunk_1，而过滤掉权限不足的 chunk_2
    print("\n🔍 联合检索测试 1：用户 user_1 (权限等级 2)")
    f1 = MetadataFilter(user_id="user_1", max_permission_level=2)
    res1 = store.search_dense(col_name, query_vector=[1.0, 0.0, 0.0, 0.0], limit=5, filters=f1)
    
    for r in res1:
        print(f"  #{r.rank} [{r.score}] {r.chunk_id}: {r.content}")
    assert len(res1) == 1
    assert res1[0].chunk_id == "chunk_1"

    # 模拟 user_1 提升权限到 Level 3，应该可以查到 chunk_1 和 chunk_2
    print("\n🔍 联合检索测试 2：用户 user_1 (权限等级 3)")
    f2 = MetadataFilter(user_id="user_1", max_permission_level=3)
    res2 = store.search_dense(col_name, query_vector=[1.0, 0.0, 0.0, 0.0], limit=5, filters=f2)
    for r in res2:
        print(f"  #{r.rank} [{r.score}] {r.chunk_id}: {r.content}")
    assert len(res2) == 2

    # 测试时间范围过滤
    print("\n🔍 联合检索测试 3：时间范围过滤 (创建时间在 2026-07-01T12:00:00Z 之后)")
    f3 = MetadataFilter(created_after="2026-07-01T12:00:00Z")
    res3 = store.search_dense(col_name, query_vector=[1.0, 0.0, 0.0, 0.0], limit=5, filters=f3)
    for r in res3:
        print(f"  #{r.rank} [{r.score}] {r.chunk_id}: {r.content}")
    assert len(res3) == 2  # chunk_2 和 chunk_3 都应该符合

    # 测试删除整个 document_id
    print("\n🗑️ 测试级联级删除文档 doc_A")
    store.delete_by_document_id(col_name, "doc_A")
    # 再次查询，应该只剩 doc_B 的 chunk_3
    f4 = MetadataFilter(user_id="user_2", max_permission_level=3)
    res4 = store.search_dense(col_name, query_vector=[1.0, 0.0, 0.0, 0.0], limit=5, filters=f4)
    print(f"  删除后查询结果数: {len(res4)}")
    assert len(res4) == 1  # 应该只剩 doc_B 的 chunk_3

    # 物理销毁
    store.delete_collection(col_name)
    print(f"\n{'=' * 70}")
    print("  Qdrant 向量存储联合检索功能演示完成 ✅")
    print("=" * 70)
