"""
微引擎 6：BM25 稀疏检索引擎 (SparseRetriever)

设计方案：
==========
1. 设计意图：
   纯 Dense（Embedding 向量）检索对精确关键词匹配能力弱。当用户查询
   "HNSW ef_construct 参数" 时，Embedding 向量检索可能返回语义相近但
   不含该精确术语的文档。BM25 稀疏检索通过词频 × 逆文档频率（TF-IDF
   变体）的统计匹配机制，恰好补齐这个短板。
   本引擎基于 `rank_bm25.BM25Okapi`，支持中英文混合分词，构建内存倒排索引，
   为 RetrievalService 的 Hybrid 检索提供稀疏检索通道。

2. 关键组件结构：
   - _tokenize(): 中英文混合分词函数（jieba + 空格分割）
   - SparseRetriever: BM25 稀疏检索引擎
     - build_index(): 对 Chunk 列表进行分词并构建 BM25 倒排索引
     - search(): 对查询文本执行 BM25 检索，返回 Top-K Chunk
     - get_index_stats(): 获取索引统计信息

3. 关键数据流：
   list[Chunk] → build_index() → BM25 倒排索引（内存）
   query_text → _tokenize() → BM25.get_scores() → Top-K Chunk 排序

使用方式（在项目根目录）：
    python -m weekly.w06_embedding_and_vector_db.project.sparse_retriever
"""
from __future__ import annotations

import re
from rank_bm25 import BM25Okapi

from weekly.w06_embedding_and_vector_db.project.models import Chunk, SearchResult


# ══════════════════════════════════════════════════════════════════════════════
# 板块一：分词工具函数
# ══════════════════════════════════════════════════════════════════════════════

# 中文字符正则（CJK 统一表意字符）
_CJK_PATTERN = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]+")

# 停用词集合（高频无语义词）
_STOPWORDS = {
    # 英文停用词
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "shall",
    "should", "may", "might", "can", "could", "in", "on", "at", "to",
    "for", "of", "with", "by", "from", "and", "or", "not", "no", "but",
    "if", "then", "so", "it", "its", "this", "that", "these", "those",
    # 中文停用词
    "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一",
    "一个", "上", "也", "很", "到", "说", "要", "去", "你", "会", "着",
    "没有", "看", "好", "自己", "这", "他", "她", "它", "们",
}


def _tokenize(text: str) -> list[str]:
    """对文本进行中英文混合分词。

    分词策略：
    1. 检测文本中是否包含中文字符
    2. 包含中文 → 使用 jieba 精确模式分词
    3. 纯英文 → 使用空格 + 标点分割 + 小写化
    4. 过滤停用词和过短 token（长度 < 2）

    Args:
        text: 待分词的文本

    Returns:
        list[str]: 分词结果列表（已去停用词、已小写化）
    """
    if not text.strip():
        return []

    tokens: list[str] = []

    # 检测是否包含中文
    has_cjk = bool(_CJK_PATTERN.search(text))

    if has_cjk:
        # 使用 jieba 分词
        import jieba
        raw_tokens = jieba.lcut(text)
        for token in raw_tokens:
            token = token.strip().lower()
            if len(token) >= 1 and token not in _STOPWORDS:
                tokens.append(token)
    else:
        # 纯英文：按非字母数字字符分割
        raw_tokens = re.split(r"[^a-zA-Z0-9_]+", text.lower())
        for token in raw_tokens:
            if len(token) >= 2 and token not in _STOPWORDS:
                tokens.append(token)

    return tokens


# ══════════════════════════════════════════════════════════════════════════════
# 板块二：SparseRetriever — BM25 稀疏检索引擎
# ══════════════════════════════════════════════════════════════════════════════

class SparseRetriever:
    """基于 BM25Okapi 的稀疏关键词检索引擎。

    BM25 (Best Matching 25) 是信息检索领域的经典统计排序算法，
    通过词频 (TF)、逆文档频率 (IDF) 和文档长度归一化来计算查询与文档的相关性。
    相比 Embedding 向量检索，BM25 在精确关键词匹配场景下表现更优。

    Attributes:
        _chunks: 已索引的 Chunk 列表（保持与 BM25 内部索引的下标对齐）
        _bm25: BM25Okapi 实例
        _tokenized_corpus: 分词后的语料库（用于调试）
        _is_indexed: 索引是否已构建
    """

    def __init__(self) -> None:
        """初始化稀疏检索引擎（索引延迟构建）。"""
        self._chunks: list[Chunk] = []
        self._bm25: BM25Okapi | None = None
        self._tokenized_corpus: list[list[str]] = []
        self._is_indexed: bool = False

    def build_index(self, chunks: list[Chunk]) -> None:
        """对 Chunk 列表进行分词并构建 BM25 倒排索引。

        Args:
            chunks: 待索引的 Chunk 列表

        Raises:
            ValueError: chunks 为空列表
        """
        if not chunks:
            raise ValueError("chunks 列表不能为空")

        self._chunks = list(chunks)

        # Step 1: 对每个 Chunk 的内容进行分词
        self._tokenized_corpus = []
        for chunk in self._chunks:
            # 将标题和内容拼接后分词（标题也是检索信号）
            full_text = f"{chunk.title} {chunk.content}" if chunk.title else chunk.content
            tokens = _tokenize(full_text)
            self._tokenized_corpus.append(tokens)

        # Step 2: 构建 BM25Okapi 索引
        self._bm25 = BM25Okapi(self._tokenized_corpus)
        self._is_indexed = True

    def search(self, query_text: str, top_k: int = 5) -> list[SearchResult]:
        """对查询文本执行 BM25 检索。

        Args:
            query_text: 用户查询文本
            top_k: 返回的最大结果数

        Returns:
            list[SearchResult]: 按 BM25 分数降序排列的检索结果

        Raises:
            RuntimeError: 索引未构建
        """
        if not self._is_indexed or self._bm25 is None:
            raise RuntimeError("BM25 索引未构建，请先调用 build_index()")

        # Step 1: 对查询文本分词
        query_tokens = _tokenize(query_text)
        if not query_tokens:
            return []

        # Step 2: 计算所有文档的 BM25 分数
        scores = self._bm25.get_scores(query_tokens)

        # Step 3: 按分数降序排列，取 Top-K
        # 使用 enumerate 保持与 _chunks 的下标对齐
        scored_indices = sorted(
            enumerate(scores),
            key=lambda x: x[1],
            reverse=True,
        )[:top_k]

        # Step 4: 构建 SearchResult 列表
        results: list[SearchResult] = []
        for rank, (idx, score) in enumerate(scored_indices, start=1):
            if score <= 0:
                continue  # BM25 分数为 0 表示完全不匹配
            chunk = self._chunks[idx]
            results.append(SearchResult(
                chunk_id=chunk.chunk_id,
                content=chunk.content,
                score=round(float(score), 4),
                source_path=chunk.source_path,
                title=chunk.title,
                section_path=chunk.section_path,
                rank=rank,
                strategy="sparse",
            ))

        return results

    def get_index_stats(self) -> dict:
        """获取索引统计信息。

        Returns:
            dict: 包含文档数、总 token 数、平均 token 数等统计信息
        """
        if not self._is_indexed:
            return {"status": "未构建"}

        total_tokens = sum(len(tokens) for tokens in self._tokenized_corpus)
        avg_tokens = total_tokens / len(self._tokenized_corpus) if self._tokenized_corpus else 0

        return {
            "status": "已构建",
            "document_count": len(self._chunks),
            "total_tokens": total_tokens,
            "avg_tokens_per_doc": round(avg_tokens, 1),
        }


# ══════════════════════════════════════════════════════════════════════════════
# 主入口：BM25 稀疏检索功能演示
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 70)
    print("  微引擎 6：BM25 稀疏检索引擎 — 功能演示")
    print("=" * 70)

    # 构建测试 Chunk 列表
    test_chunks = [
        Chunk(
            chunk_id="chunk_001", document_id="doc_001",
            content="HNSW 索引的 ef_construct 参数控制索引构建时的搜索范围，值越大构建越慢但检索精度越高。",
            title="HNSW 参数调优",
        ),
        Chunk(
            chunk_id="chunk_002", document_id="doc_001",
            content="Qdrant 向量数据库支持 Cosine 和 Euclidean 两种距离度量方式。",
            title="距离度量",
        ),
        Chunk(
            chunk_id="chunk_003", document_id="doc_002",
            content="BM25 是基于 TF-IDF 变体的经典稀疏检索算法，在精确关键词匹配场景下表现优异。",
            title="BM25 原理",
        ),
        Chunk(
            chunk_id="chunk_004", document_id="doc_002",
            content="Pre-Filtering 在向量数据库底层将元数据过滤与 HNSW 图检索结合，避免检索空置。",
            title="Pre-Filtering",
        ),
        Chunk(
            chunk_id="chunk_005", document_id="doc_003",
            content="Transformer 的自注意力机制通过计算 Query、Key、Value 的点积来建立序列内的全局依赖关系。",
            title="Self-Attention",
        ),
        Chunk(
            chunk_id="chunk_006", document_id="doc_003",
            content="指数退避算法在遇到 429 限流报错时，按 1s→2s→4s→8s 的间隔递增重试时间。",
            title="指数退避重试",
        ),
    ]

    # 构建索引
    retriever = SparseRetriever()
    retriever.build_index(test_chunks)
    stats = retriever.get_index_stats()
    print(f"\n  索引统计: {stats}")

    # 测试查询
    queries = [
        "HNSW ef_construct 参数如何影响检索性能",
        "BM25 稀疏检索算法",
        "429 限流重试策略",
        "Transformer attention mechanism",
    ]

    for query in queries:
        print(f"\n  🔍 查询: \"{query}\"")
        results = retriever.search(query, top_k=3)
        if not results:
            print("    (无匹配结果)")
        for r in results:
            print(f"    #{r.rank} [BM25={r.score:.4f}] {r.chunk_id}: {r.content[:60]}...")

    print(f"\n{'=' * 70}")
    print("  BM25 稀疏检索引擎功能演示完成 ✅")
    print("=" * 70)
