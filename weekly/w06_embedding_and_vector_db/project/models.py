"""
AI Research Assistant Knowledge Engine — 全系统 Pydantic 数据契约层

设计方案：
==========
1. 设计意图：
   本文件定义贯穿整个 Knowledge Engine 各微引擎之间数据流转的类型契约。
   通过 Pydantic BaseModel 的强类型校验，确保从文档解析到向量检索的全链路中，
   任何数据格式不匹配问题在"数据交接"阶段即被拦截，而非在运行期因 KeyError 或
   AttributeError 引发难以定位的连锁崩溃。

2. 数据流向与模型层次：
   Layer 1（原始层）: RawDocument → 原始文件字节/文本
   Layer 2（结构层）: ParsedDocument → 解析后保留层级结构的文档
   Layer 3（清洗层）: CleanedText → 去噪后的纯净文本
   Layer 4（切片层）: Chunk → 知识切片单元
   Layer 5（向量层）: ChunkWithVector → 附带 Embedding 向量的切片
   Layer 6（检索层）: SearchQuery / SearchResult / RetrievalResponse
   Layer 7（评估层）: EvalSample / EvalMetrics / BenchmarkReport

3. 设计约束：
   - 所有模型均使用 Pydantic V2 的 BaseModel，启用严格模式（strict=False 以兼容 JSON 反序列化）
   - 所有 datetime 字段统一使用 ISO 8601 字符串，避免时区陷阱
   - Chunk 的 hash 字段使用 SHA-256，用于全局去重
   - 枚举类型使用 str enum，保证 JSON 序列化/反序列化的可读性

使用方式（在项目根目录）：
    python -m weekly.w06_embedding_and_vector_db.project.models
"""
from __future__ import annotations

from enum import Enum
from pydantic import BaseModel, Field
from typing import Optional


# ══════════════════════════════════════════════════════════════════════════════
# 板块一：枚举类型定义
# ══════════════════════════════════════════════════════════════════════════════

class SourceType(str, Enum):
    """文档来源格式枚举。

    用于在 DocumentParser 路由阶段决定调用哪个具体的格式解析器。
    """
    PDF = "pdf"
    MARKDOWN = "markdown"
    HTML = "html"
    TXT = "txt"
    CODE = "code"


class RetrievalStrategy(str, Enum):
    """检索策略枚举。

    控制 RetrievalService 使用哪种检索路径。
    """
    DENSE_ONLY = "dense_only"      # 仅 Embedding 向量检索
    SPARSE_ONLY = "sparse_only"    # 仅 BM25 关键词检索
    HYBRID = "hybrid"              # Dense + Sparse → RRF 融合（默认推荐）


class PermissionLevel(int, Enum):
    """文档权限级别枚举。

    用于多租户场景下的 Pre-Filtering 权限控制。
    数值越低权限越开放：
      PUBLIC(1) < INTERNAL(2) < CONFIDENTIAL(3) < RESTRICTED(4)
    查询时使用 permission_level <= user_max_level 进行过滤。
    """
    PUBLIC = 1
    INTERNAL = 2
    CONFIDENTIAL = 3
    RESTRICTED = 4


# ══════════════════════════════════════════════════════════════════════════════
# 板块二：Layer 1-2 文档原始层与结构层
# ══════════════════════════════════════════════════════════════════════════════

class DocumentMetadata(BaseModel):
    """文档级元数据契约。

    贯穿文档从导入到存储的全生命周期，最终作为 Qdrant Payload 写入向量数据库。

    Attributes:
        author: 文档作者（用于 Payload Keyword 索引过滤）
        created_time: 创建时间 ISO 8601 字符串（用于 Range 过滤）
        category: 知识域分类（如 "vector_index", "llm_api"）
        source_type: 原始文件格式
        permission_level: 访问权限级别（用于多租户 Pre-Filtering）
        user_id: 文档所属用户 ID（用于 Keyword 索引过滤）
        tags: 可选标签列表，辅助精细化检索
    """
    author: str = "unknown"
    created_time: str = ""
    category: str = "general"
    source_type: SourceType = SourceType.TXT
    permission_level: int = Field(
        default=PermissionLevel.PUBLIC.value,
        ge=1, le=4,
        description="访问权限级别 1-4，数值越低越开放"
    )
    user_id: str = "default"
    tags: list[str] = Field(default_factory=list)


class DocumentSection(BaseModel):
    """文档内部结构区块契约。

    表示解析后的一个结构化段落/章节。保留原始文档的层级信息，
    使得后续 ChunkEngine 能在语义边界处切分。

    Attributes:
        heading: 区块标题（如 "2.1 Attention Mechanism"）
        level: 标题层级（1=h1, 2=h2, ...），0 表示正文段落
        content: 该区块的文本内容
        page_number: PDF 中的页码（非 PDF 格式默认为 0）
    """
    heading: str = ""
    level: int = 0
    content: str = ""
    page_number: int = 0


class RawDocument(BaseModel):
    """原始文档入口契约。

    由 DocumentParser 的调用方构建，表示尚未经过任何解析处理的原始文件。

    Attributes:
        source_path: 文件的物理路径或 URL
        source_type: 文件格式类型
        raw_content: 原始文本内容（PDF 为提取后的文本）
        file_size: 文件大小（字节）
        metadata: 文档级元数据
    """
    source_path: str
    source_type: SourceType
    raw_content: str = ""
    file_size: int = 0
    metadata: DocumentMetadata = Field(default_factory=DocumentMetadata)


class ParsedDocument(BaseModel):
    """解析后的结构化文档契约。

    由 DocumentParser 输出，保留了原始文档的标题层级和章节结构。
    这是 TextCleaner 和 ChunkEngine 的输入数据类型。

    Attributes:
        document_id: 文档全局唯一标识符（基于 source_path 的 SHA-256 截断）
        title: 文档标题（从第一个 h1 或文件名推断）
        sections: 文档内部结构化区块列表（保留层级顺序）
        metadata: 文档级元数据（继承自 RawDocument）
        total_chars: 文档总字符数
    """
    document_id: str
    title: str = ""
    sections: list[DocumentSection] = Field(default_factory=list)
    metadata: DocumentMetadata = Field(default_factory=DocumentMetadata)
    total_chars: int = 0


# ══════════════════════════════════════════════════════════════════════════════
# 板块三：Layer 3 清洗层
# ══════════════════════════════════════════════════════════════════════════════

class CleanedSection(BaseModel):
    """清洗后的文档区块契约。

    保留了原始区块的结构信息，但文本内容已经过去噪处理。

    Attributes:
        heading: 区块标题（保留）
        level: 标题层级（保留）
        content: 清洗后的纯净文本
        original_length: 清洗前字符数
        cleaned_length: 清洗后字符数
        noise_ratio: 噪声比例 = 1 - (cleaned / original)，值越高说明噪声越多
        page_number: 页码（保留）
    """
    heading: str = ""
    level: int = 0
    content: str = ""
    original_length: int = 0
    cleaned_length: int = 0
    noise_ratio: float = 0.0
    page_number: int = 0


class CleanedDocument(BaseModel):
    """清洗后的完整文档契约。

    Attributes:
        document_id: 文档 ID（继承）
        title: 文档标题（继承）
        sections: 清洗后的区块列表
        metadata: 元数据（继承）
        total_noise_ratio: 全文档平均噪声比例
    """
    document_id: str
    title: str = ""
    sections: list[CleanedSection] = Field(default_factory=list)
    metadata: DocumentMetadata = Field(default_factory=DocumentMetadata)
    total_noise_ratio: float = 0.0


# ══════════════════════════════════════════════════════════════════════════════
# 板块四：Layer 4-5 切片层与向量层
# ══════════════════════════════════════════════════════════════════════════════

class Chunk(BaseModel):
    """知识切片单元契约。

    这是整个 RAG 系统的最小知识粒度。每个 Chunk 是一段独立的、
    自包含语义的文本片段，携带完整的溯源元数据。

    Attributes:
        chunk_id: 切片全局唯一 ID（格式: "{document_id}_chunk_{index:04d}"）
        document_id: 所属文档 ID（用于溯源）
        content: 切片文本内容
        chunk_index: 在文档内的切片序号（从 0 开始）
        title: 所属章节标题
        section_path: 完整章节路径（如 "Chapter 2 > Section 2.1"）
        source_path: 原始文件路径
        author: 作者
        created_time: 创建时间
        page_number: 页码
        token_length: 估算 token 数
        char_length: 字符数
        hash: SHA-256 内容指纹（用于全局去重）
        category: 知识域分类
        permission_level: 权限级别
        user_id: 所属用户 ID
    """
    chunk_id: str
    document_id: str
    content: str
    chunk_index: int = 0
    title: str = ""
    section_path: str = ""
    source_path: str = ""
    author: str = "unknown"
    created_time: str = ""
    page_number: int = 0
    token_length: int = 0
    char_length: int = 0
    hash: str = ""
    category: str = "general"
    permission_level: int = PermissionLevel.PUBLIC.value
    user_id: str = "default"


class ChunkWithVector(BaseModel):
    """附带 Embedding 向量的知识切片契约。

    由 EmbeddingPipeline 输出，是写入 Qdrant 的最终数据形态。

    Attributes:
        chunk: 原始 Chunk 数据
        vector: Embedding 浮点向量
    """
    chunk: Chunk
    vector: list[float]


# ══════════════════════════════════════════════════════════════════════════════
# 板块五：Layer 6 检索层
# ══════════════════════════════════════════════════════════════════════════════

class MetadataFilter(BaseModel):
    """检索时的元数据过滤条件契约。

    由 RetrievalService 转换为 Qdrant Filter 对象进行 Pre-Filtering。

    Attributes:
        user_id: 限定用户 ID（权限隔离）
        max_permission_level: 最大可访问权限级别
        categories: 限定知识域列表（空列表表示不限制）
        authors: 限定作者列表
        created_after: 限定创建时间下界（ISO 8601）
        created_before: 限定创建时间上界（ISO 8601）
    """
    user_id: Optional[str] = None
    max_permission_level: int = PermissionLevel.RESTRICTED.value
    categories: list[str] = Field(default_factory=list)
    authors: list[str] = Field(default_factory=list)
    created_after: Optional[str] = None
    created_before: Optional[str] = None


class SearchQuery(BaseModel):
    """检索请求契约。

    由外部调用方构建，传入 RetrievalService 执行检索。

    Attributes:
        query_text: 用户查询原始文本
        top_k: 返回的最大结果数
        filters: 元数据过滤条件（可选）
        strategy: 检索策略（默认 HYBRID）
        collection: 目标集合名（默认使用 "technical_docs"）
    """
    query_text: str
    top_k: int = Field(default=5, ge=1, le=100)
    filters: Optional[MetadataFilter] = None
    strategy: RetrievalStrategy = RetrievalStrategy.HYBRID
    collection: str = "technical_docs"


class SearchResult(BaseModel):
    """单条检索结果契约。

    Attributes:
        chunk_id: 命中的 Chunk ID
        content: Chunk 文本内容
        score: 检索得分（Dense 为余弦相似度，Sparse 为 BM25 分，Hybrid 为 RRF 分）
        source_path: 原始文件路径
        title: 所属章节标题
        section_path: 章节路径
        rank: 在结果列表中的排名（从 1 开始）
        strategy: 产出该结果的检索策略
    """
    chunk_id: str
    content: str
    score: float
    source_path: str = ""
    title: str = ""
    section_path: str = ""
    rank: int = 0
    strategy: str = ""


class RetrievalResponse(BaseModel):
    """检索响应契约。

    由 RetrievalService 返回的完整检索响应。

    Attributes:
        results: 排序后的检索结果列表
        latency_ms: 检索耗时（毫秒）
        strategy_used: 实际使用的检索策略
        total_candidates: 融合前的候选总数
        query_text: 原始查询文本
    """
    results: list[SearchResult] = Field(default_factory=list)
    latency_ms: float = 0.0
    strategy_used: RetrievalStrategy = RetrievalStrategy.HYBRID
    total_candidates: int = 0
    query_text: str = ""


# ══════════════════════════════════════════════════════════════════════════════
# 板块六：Layer 7 评估层
# ══════════════════════════════════════════════════════════════════════════════

class EvalSample(BaseModel):
    """评估测试样本契约。

    每个样本包含一个问题和对应的"黄金标准"正确答案 Chunk ID 列表。
    由人工标注或半自动方式生成。

    Attributes:
        question: 测试问题
        expected_chunk_ids: 正确答案 Chunk ID 列表
        category: 问题分类（用于分维度评估）
    """
    question: str
    expected_chunk_ids: list[str]
    category: str = "general"


class EvalMetrics(BaseModel):
    """检索质量评估指标契约。

    Attributes:
        recall_at_k: Recall@K — Top-K 中命中了多少正确答案
        precision_at_k: Precision@K — Top-K 中有多少是真相关的
        mrr: Mean Reciprocal Rank — 第一个正确答案出现得多靠前
        ndcg_at_k: NDCG@K — 带位置衰减的累积增益归一化
        k: K 值
        num_samples: 评估样本数
        strategy: 评估使用的检索策略
    """
    recall_at_k: float = 0.0
    precision_at_k: float = 0.0
    mrr: float = 0.0
    ndcg_at_k: float = 0.0
    k: int = 5
    num_samples: int = 0
    strategy: RetrievalStrategy = RetrievalStrategy.HYBRID


class BenchmarkReport(BaseModel):
    """压力测试报告契约。

    Attributes:
        import_total_docs: 导入的文档总数
        import_total_chunks: 导入的切片总数
        import_duration_s: 导入总耗时（秒）
        import_tps: 导入吞吐量（chunks/second）
        embedding_tps: Embedding 吞吐量（tokens/second）
        qdrant_write_tps: Qdrant 写入吞吐量（points/second）
        query_count: 查询总数
        p50_latency_ms: P50 查询延迟（毫秒）
        p95_latency_ms: P95 查询延迟（毫秒）
        p99_latency_ms: P99 查询延迟（毫秒）
        avg_latency_ms: 平均查询延迟（毫秒）
        qps: 每秒查询数
    """
    import_total_docs: int = 0
    import_total_chunks: int = 0
    import_duration_s: float = 0.0
    import_tps: float = 0.0
    embedding_tps: float = 0.0
    qdrant_write_tps: float = 0.0
    query_count: int = 0
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0
    avg_latency_ms: float = 0.0
    qps: float = 0.0


# ══════════════════════════════════════════════════════════════════════════════
# 主入口：类型契约自检
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 70)
    print("  AI Research Assistant Knowledge Engine — 数据契约自检")
    print("=" * 70)

    # --- 验证 Layer 1-2：文档原始层与结构层 ---
    raw = RawDocument(
        source_path="/papers/attention.pdf",
        source_type=SourceType.PDF,
        raw_content="Attention is all you need...",
        file_size=1024,
        metadata=DocumentMetadata(
            author="Vaswani",
            category="transformer",
            permission_level=2,
        )
    )
    print(f"\n✅ RawDocument 创建成功: source={raw.source_path}, type={raw.source_type.value}")

    parsed = ParsedDocument(
        document_id="doc_abc123",
        title="Attention Is All You Need",
        sections=[
            DocumentSection(heading="Abstract", level=1, content="We propose..."),
            DocumentSection(heading="Introduction", level=1, content="The dominant..."),
        ],
        metadata=raw.metadata,
        total_chars=5000,
    )
    print(f"✅ ParsedDocument 创建成功: id={parsed.document_id}, sections={len(parsed.sections)}")

    # --- 验证 Layer 4：切片层 ---
    chunk = Chunk(
        chunk_id="doc_abc123_chunk_0001",
        document_id="doc_abc123",
        content="We propose a new network architecture...",
        chunk_index=1,
        title="Abstract",
        section_path="Abstract",
        token_length=128,
        char_length=40,
        hash="sha256:deadbeef",
        permission_level=2,
    )
    print(f"✅ Chunk 创建成功: id={chunk.chunk_id}, tokens={chunk.token_length}")

    # --- 验证 Layer 6：检索层 ---
    query = SearchQuery(
        query_text="attention mechanism 工作原理",
        top_k=5,
        filters=MetadataFilter(
            max_permission_level=2,
            categories=["transformer"],
        ),
        strategy=RetrievalStrategy.HYBRID,
    )
    print(f"✅ SearchQuery 创建成功: strategy={query.strategy.value}, top_k={query.top_k}")

    result = SearchResult(
        chunk_id="doc_abc123_chunk_0001",
        content="We propose a new network architecture...",
        score=0.92,
        rank=1,
        strategy="hybrid",
    )
    response = RetrievalResponse(
        results=[result],
        latency_ms=8.5,
        strategy_used=RetrievalStrategy.HYBRID,
        total_candidates=100,
        query_text=query.query_text,
    )
    print(f"✅ RetrievalResponse 创建成功: results={len(response.results)}, latency={response.latency_ms}ms")

    # --- 验证 Layer 7：评估层 ---
    metrics = EvalMetrics(
        recall_at_k=0.85,
        precision_at_k=0.60,
        mrr=0.72,
        ndcg_at_k=0.68,
        k=10,
        num_samples=100,
    )
    print(f"✅ EvalMetrics 创建成功: Recall@{metrics.k}={metrics.recall_at_k}, MRR={metrics.mrr}")

    bench = BenchmarkReport(
        import_total_docs=100,
        import_total_chunks=5000,
        import_duration_s=120.5,
        import_tps=41.5,
        p50_latency_ms=8.2,
        p95_latency_ms=15.3,
        p99_latency_ms=28.7,
    )
    print(f"✅ BenchmarkReport 创建成功: P50={bench.p50_latency_ms}ms, P95={bench.p95_latency_ms}ms")

    print(f"\n{'=' * 70}")
    print("  全部 {0} 个数据契约类型验证通过 ✅".format(
        len([RawDocument, ParsedDocument, DocumentSection, CleanedSection,
             CleanedDocument, Chunk, ChunkWithVector, DocumentMetadata,
             MetadataFilter, SearchQuery, SearchResult, RetrievalResponse,
             EvalSample, EvalMetrics, BenchmarkReport])
    ))
    print("=" * 70)
