import pytest
import asyncio
from unittest.mock import AsyncMock, patch

from weekly.w06_embedding_and_vector_db.project.models import Chunk, ChunkWithVector, SearchQuery, MetadataFilter, RetrievalStrategy
from weekly.w06_embedding_and_vector_db.project.vector_store import QdrantVectorStore
from weekly.w06_embedding_and_vector_db.project.sparse_retriever import SparseRetriever
from weekly.w06_embedding_and_vector_db.project.retrieval_service import RetrievalService


@pytest.fixture
def test_chunks():
    """准备几个不同属性的测试切片"""
    return [
        Chunk(
            chunk_id="c_1",
            document_id="doc_A",
            content="Attention is all you need for transformer models.",
            title="Transformer Overview",
            source_path="doc_A",
            category="AI",
            permission_level=1,
            user_id="user_1",
            created_time="2026-07-01T00:00:00Z"
        ),
        Chunk(
            chunk_id="c_2",
            document_id="doc_A",
            content="HNSW construct parameters ef_construct and m control graph query accuracy.",
            title="Vector DB Optimizations",
            source_path="doc_A",
            category="Database",
            permission_level=3,
            user_id="user_1",
            created_time="2026-07-02T00:00:00Z"
        ),
        Chunk(
            chunk_id="c_3",
            document_id="doc_B",
            content="RAG hybrid search combines vector distance with BM25 keyword match scores.",
            title="Hybrid Retrieval Design",
            source_path="doc_B",
            category="Database",
            permission_level=1,
            user_id="user_2",
            created_time="2026-07-03T00:00:00Z"
        )
    ]


@pytest.fixture
def mock_embedding_client():
    """Mock 的 Embedding 客户端，返回固定的高维测试向量"""
    client = AsyncMock()
    # 模拟 embed_single，对于含有 'transformer' 词的，偏向 c_1，其向量与 c_1 更近
    # query: "attention mechanism"
    client.embed_single = AsyncMock(return_value=[1.0, 0.0, 0.0, 0.0])
    return client


@pytest.mark.asyncio
async def test_retrieval_service_flows(test_chunks, mock_embedding_client):
    # 1. 初始化 Qdrant 内存库并写入向量点
    store = QdrantVectorStore(location=":memory:")
    col_name = "test_hybrid_col"
    store.create_collection(col_name, dimension=4)
    
    # 我们为 3 个 Chunk 指定简易高维向量
    cvs = [
        ChunkWithVector(chunk=test_chunks[0], vector=[1.0, 0.0, 0.0, 0.0]),  # "Attention is all..."
        ChunkWithVector(chunk=test_chunks[1], vector=[0.0, 1.0, 0.0, 0.0]),  # "HNSW construct..."
        ChunkWithVector(chunk=test_chunks[2], vector=[0.8, 0.6, 0.0, 0.0]),  # "RAG hybrid..."
    ]
    store.upsert_chunks(col_name, cvs)

    # 2. 初始化本地 Sparse 索引
    sparse = SparseRetriever()
    sparse.build_index(test_chunks)

    # 3. 构造混合检索服务
    service = RetrievalService(
        vector_store=store,
        embedding_client=mock_embedding_client,
        sparse_retriever=sparse,
        collection_name=col_name
    )

    # 4. 测试 DENSE_ONLY 模式（向量夹角最接近 [1.0, 0.0, 0.0, 0.0]）
    # 查询 query_vector = [1.0, 0.0, 0.0, 0.0]，预计 c_1 得分最高 (1.0)，其次为 c_3 (0.8)，再次为 c_2 (0.0)
    # 我们使用 filters 限制只能读取 permission_level <= 2 的文档 (过滤掉 c_2)
    query_dense = SearchQuery(
        query_text="attention model",
        top_k=5,
        filters=MetadataFilter(max_permission_level=2),
        strategy=RetrievalStrategy.DENSE_ONLY
    )
    
    resp_dense = await service.retrieve(query_dense)
    assert resp_dense.strategy_used == RetrievalStrategy.DENSE_ONLY
    assert len(resp_dense.results) == 2  # c_1, c_3
    assert resp_dense.results[0].chunk_id == "c_1"
    assert resp_dense.results[1].chunk_id == "c_3"

    # 5. 测试 SPARSE_ONLY 模式并带前置过滤
    # 查询 "HNSW ef_construct"，由于 c_2 (level 3) 权限被卡控 (用户 max level 为 2)
    # 尽管 c_2 关键词完全匹配，但由于 Pre-Filtering，检索结果应该为 0
    query_sparse_restricted = SearchQuery(
        query_text="HNSW ef_construct",
        top_k=5,
        filters=MetadataFilter(max_permission_level=2),
        strategy=RetrievalStrategy.SPARSE_ONLY
    )
    resp_sparse_r = await service.retrieve(query_sparse_restricted)
    assert len(resp_sparse_r.results) == 0

    # 提升权限到 3 后，再次检索，应该成功召回 c_2
    query_sparse_allowed = SearchQuery(
        query_text="HNSW ef_construct",
        top_k=5,
        filters=MetadataFilter(max_permission_level=3),
        strategy=RetrievalStrategy.SPARSE_ONLY
    )
    resp_sparse_a = await service.retrieve(query_sparse_allowed)
    assert len(resp_sparse_a.results) == 1
    assert resp_sparse_a.results[0].chunk_id == "c_2"

    # 6. 测试 HYBRID 模式与 RRF 融合
    # 用户无任何过滤条件，查询 "RAG hybrid keyword"
    # - Dense 路：输入 query 向量被 mock 为 [1.0, 0.0, 0.0, 0.0]。
    #   Dense 距离排名为：1. c_1 (1.0), 2. c_3 (0.8), 3. c_2 (0.0)
    # - Sparse 路：分词匹配到 "RAG hybrid keyword"，只有 c_3 包含了 "RAG", "hybrid" 两个关键词词组。
    #   Sparse 匹配排名为：1. c_3, 2. (无)
    # - RRF 计算 (k=60)：
    #   c_1 排名：Dense=1 (分数 1/61 ≈ 0.01639), Sparse=None (分数 0.0) -> RRF = 0.01639
    #   c_3 排名：Dense=2 (分数 1/62 ≈ 0.01613), Sparse=1 (分数 1/61 ≈ 0.01639) -> RRF = 0.03252
    #   c_2 排名：Dense=3 (分数 1/63 ≈ 0.01587), Sparse=None (分数 0.0) -> RRF = 0.01587
    # 期望混合融合后：c_3 (RRF=0.03252) 逆袭排在第一名！c_1 降为第二名，c_2 为第三名。
    query_hybrid = SearchQuery(
        query_text="RAG hybrid keyword",
        top_k=5,
        filters=MetadataFilter(max_permission_level=3),
        strategy=RetrievalStrategy.HYBRID
    )
    resp_hybrid = await service.retrieve(query_hybrid)
    assert resp_hybrid.strategy_used == RetrievalStrategy.HYBRID
    assert len(resp_hybrid.results) == 3
    assert resp_hybrid.results[0].chunk_id == "c_3"  # RRF 融合使 c_3 排名升至第一！
    assert resp_hybrid.results[1].chunk_id == "c_1"
    assert resp_hybrid.results[2].chunk_id == "c_2"

    # 7. 测试 Context 字符串拼接
    context_str = service.build_context_string(resp_hybrid.results)
    assert "[Source 1] Title: Hybrid Retrieval Design" in context_str
    assert "Path: doc_B > Root" in context_str
    assert "RAG hybrid search" in context_str

    # 8. 清理资源
    store.delete_collection(col_name)
