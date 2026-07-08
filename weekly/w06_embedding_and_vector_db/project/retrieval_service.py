"""
微引擎 7：双路混合检索与 RRF 分数融合服务 (RetrievalService)

设计方案：
==========
1. 设计意图：
   纯向量检索（Dense Retrieval）能捕捉语义相似度，但对精确关键词（如特定参数、错误码）匹配偏弱；
   纯倒排检索（Sparse Retrieval）能实现精确字面匹配，但无法理解近义词和上下文。
   本服务实现了生产级双路 Hybrid 检索方案：
   - 整合底层 Qdrant 向量检索与本地内存 BM25 稀疏检索。
   - 对两路独立检索使用一致的 MetadataFilter 条件进行 Pre-Filtering，严格保证租户隔离与权限边界。
   - 应用业界经典的倒数排名融合（Reciprocal Rank Fusion, RRF）算法，消除了两种检索评分机制的量纲差异，输出全局最优的 Top-K 排行。
   - 提供标准的上下文组装工具，将检索结果格式化拼接为 LLM System Prompt 所需的 Context 文本。

2. 关键组件结构：
   - RetrievalService: 核心混合检索调度与融合类
     - _match_filter(): 内存 Pre-Filtering 元数据过滤核心方法
     - _sparse_search_with_filter(): 附带 Pre-Filtering 的本地 BM25 检索
     - retrieve(): 检索主入口，支持 DENSE_ONLY, SPARSE_ONLY, HYBRID 策略路由
     - build_context_string(): 检索上下文一键拼接组装函数

3. 关键数据流向：
   SearchQuery ──> 提取 query_text 与 MetadataFilter
     ├──> [通道 1] 调用 EmbeddingClient 获取向量 ──> Qdrant Pre-Filtering 检索
     ├──> [通道 2] _match_filter() 剪枝 ──> 在候选子集上计算 BM25 检索
     └──> [RRF 融合] 按照 1 / (60 + rank) 累加评分 ──> 降序排序输出 Top-K

使用方式（在项目根目录）：
    python -m weekly.w06_embedding_and_vector_db.project.retrieval_service
"""
from __future__ import annotations

import time
import datetime
from typing import Optional

from weekly.w06_embedding_and_vector_db.utils import EmbeddingClient
from weekly.w06_embedding_and_vector_db.project.vector_store import QdrantVectorStore
from weekly.w06_embedding_and_vector_db.project.sparse_retriever import SparseRetriever, _tokenize
from weekly.w06_embedding_and_vector_db.project.models import (
    Chunk,
    SearchQuery,
    SearchResult,
    RetrievalResponse,
    RetrievalStrategy,
    MetadataFilter,
    PermissionLevel
)


class RetrievalService:
    """双路混合检索与 RRF 排名融合服务"""

    def __init__(
        self,
        vector_store: QdrantVectorStore,
        embedding_client: EmbeddingClient,
        sparse_retriever: SparseRetriever,
        collection_name: str = "technical_docs"
    ) -> None:
        """初始化混合检索服务。

        Args:
            vector_store: 封装的 Qdrant 向量存储实例
            embedding_client: Embedding 异步 API 客户端
            sparse_retriever: BM25 稀疏检索引擎实例
            collection_name: 向量检索所指向的 Qdrant 集合名称
        """
        self.vector_store = vector_store
        self.embedding_client = embedding_client
        self.sparse_retriever = sparse_retriever
        self.collection_name = collection_name

    def _match_filter(self, chunk: Chunk, filters: Optional[MetadataFilter]) -> bool:
        """判断单条 Chunk 是否满足所给定的 MetadataFilter 过滤要求（用于本地 Sparse Pre-Filtering）。

        Args:
            chunk: 待检测的 Chunk 知识切片
            filters: 检索过滤条件，若为 None 则默认通过

        Returns:
            bool: 是否满足过滤条件
        """
        if not filters:
            return True

        # Step 1: 租户隔离检验
        if filters.user_id is not None and chunk.user_id != filters.user_id:
            return False

        # Step 2: 访问权限级别判定（Chunk 自身等级 <= 用户最大许可等级）
        if chunk.permission_level > filters.max_permission_level:
            return False

        # Step 3: 知识分类精确过滤
        if filters.categories and chunk.category not in filters.categories:
            return False

        # Step 4: 作者信息过滤
        if filters.authors and chunk.author not in filters.authors:
            return False

        # Step 5: 时间范围过滤（基于 ISO 格式字符串的字母表序比对，自然等价于时间先后顺序）
        if filters.created_after and chunk.created_time < filters.created_after:
            return False
        if filters.created_before and chunk.created_time > filters.created_before:
            return False

        return True

    def _sparse_search_with_filter(
        self,
        query_text: str,
        limit: int = 100,
        filters: Optional[MetadataFilter] = None
    ) -> list[SearchResult]:
        """附带 Pre-Filtering 前置过滤的本地内存 BM25 检索。

        先过滤出安全的 Chunk 候选集，再借用 BM25 实例计算其词频分数，
        完美杜绝 Post-Filtering 带来的 Recall Drop。

        Args:
            query_text: 查询文本
            limit: 检索候选结果数量
            filters: 元数据与权限过滤条件

        Returns:
            list[SearchResult]: 过滤并打分排序后的稀疏检索结果
        """
        if not self.sparse_retriever._is_indexed or self.sparse_retriever._bm25 is None:
            return []

        # Step 1: 对查询文本进行中文/英文混合分词
        query_tokens = _tokenize(query_text)
        if not query_tokens:
            return []

        # Step 2: 获取全局 Chunks 的 BM25 分数
        scores = self.sparse_retriever._bm25.get_scores(query_tokens)

        # Step 3: 根据 filters 在内存中执行前置过滤（Pre-Filtering）
        scored_candidates = []
        for idx, chunk in enumerate(self.sparse_retriever._chunks):
            # 只有通过权限与元数据筛选，且分数值大于 0 的 Chunk 才能参与候选
            if self._match_filter(chunk, filters):
                score = scores[idx]
                if score > 0:
                    scored_candidates.append((chunk, score))

        # Step 4: 对通过过滤的候选集按 BM25 分数降序排列，截取 limit 大小
        scored_candidates.sort(key=lambda x: x[1], reverse=True)
        top_candidates = scored_candidates[:limit]

        # Step 5: 转换为 SearchResult 列表并标注 strategy
        results = []
        for rank, (chunk, score) in enumerate(top_candidates, start=1):
            results.append(
                SearchResult(
                    chunk_id=chunk.chunk_id,
                    content=chunk.content,
                    score=round(float(score), 4),
                    source_path=chunk.source_path,
                    title=chunk.title,
                    section_path=chunk.section_path,
                    rank=rank,
                    strategy="sparse"
                )
            )

        return results

    async def retrieve(self, query: SearchQuery) -> RetrievalResponse:
        """执行多路联合检索，支持策略路由与 RRF 算法融合。

        Args:
            query: 结构化查询请求契约

        Returns:
            RetrievalResponse: 结构化检索响应，包含融合后的结果及检索时延
        """
        start_time = time.perf_counter()

        strategy = query.strategy
        results: list[SearchResult] = []
        total_candidates = 0

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 通路 1: 仅向量检索 (DENSE_ONLY)
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        if strategy == RetrievalStrategy.DENSE_ONLY:
            # 1. 异步请求 Embedding API 获取查询词向量
            query_vector = await self.embedding_client.embed_single(
                query.query_text,
                embed_type="query"
            )
            # 2. 调用 Qdrant 执行 Pre-Filtering ANN 检索
            results = self.vector_store.search_dense(
                collection_name=self.collection_name,
                query_vector=query_vector,
                limit=query.top_k,
                filters=query.filters
            )
            total_candidates = len(results)

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 通路 2: 仅稀疏检索 (SPARSE_ONLY)
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        elif strategy == RetrievalStrategy.SPARSE_ONLY:
            # 执行带有本地内存前置过滤的 BM25 检索
            results = self._sparse_search_with_filter(
                query_text=query.query_text,
                limit=query.top_k,
                filters=query.filters
            )
            total_candidates = len(results)

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # 通路 3: 混合双路检索与 RRF 分数融合 (HYBRID)
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        elif strategy == RetrievalStrategy.HYBRID:
            # 1. 获取 Dense 通信候选集（limit 放大至 100 以确保充足融合覆盖率）
            query_vector = await self.embedding_client.embed_single(
                query.query_text,
                embed_type="query"
            )
            dense_candidates = self.vector_store.search_dense(
                collection_name=self.collection_name,
                query_vector=query_vector,
                limit=100,
                filters=query.filters
            )

            # 2. 获取 Sparse 通信候选集（limit 同样放大至 100）
            sparse_candidates = self._sparse_search_with_filter(
                query_text=query.query_text,
                limit=100,
                filters=query.filters
            )

            total_candidates = len(dense_candidates) + len(sparse_candidates)

            # 3. 运行 RRF (Reciprocal Rank Fusion) 倒数排名融合算法
            # RRF 常量，业界通用默认 60，用于平滑极高排名的得分影响
            k_rrf = 60
            
            # 使用字典聚合所有候选 Chunk 的 RRF 累积分数，Key 为 chunk_id
            # 并使用单独的映射表缓存命中 Chunk 的属性信息，用于重建结果
            rrf_scores: dict[str, float] = {}
            chunk_cache: dict[str, SearchResult] = {}

            # 第一路 Dense 计分：根据排位依次累加
            for rank_idx, s_res in enumerate(dense_candidates):
                c_id = s_res.chunk_id
                # 倒数排名分数累计：1 / (60 + rank)
                rrf_scores[c_id] = rrf_scores.get(c_id, 0.0) + (1.0 / (k_rrf + (rank_idx + 1)))
                chunk_cache[c_id] = s_res

            # 第二路 Sparse 计分
            for rank_idx, s_res in enumerate(sparse_candidates):
                c_id = s_res.chunk_id
                rrf_scores[c_id] = rrf_scores.get(c_id, 0.0) + (1.0 / (k_rrf + (rank_idx + 1)))
                # 即使没有被 Dense 命中，也能在这里入缓存
                if c_id not in chunk_cache:
                    chunk_cache[c_id] = s_res

            # 4. 根据累积后的 RRF 分数进行全局降序排序
            sorted_by_rrf = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)

            # 5. 截取最终前 top_k 个融合结果，重新包装并设置策略为 "hybrid"
            results = []
            for rank, (c_id, rrf_score) in enumerate(sorted_by_rrf[:query.top_k], start=1):
                cached_chunk = chunk_cache[c_id]
                results.append(
                    SearchResult(
                        chunk_id=c_id,
                        content=cached_chunk.content,
                        score=round(rrf_score, 6),  # 记录 RRF 的相对归一分值
                        source_path=cached_chunk.source_path,
                        title=cached_chunk.title,
                        section_path=cached_chunk.section_path,
                        rank=rank,
                        strategy="hybrid"
                    )
                )

        # 记录全链路检索用时（毫秒）
        duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)

        return RetrievalResponse(
            results=results,
            latency_ms=duration_ms,
            strategy_used=strategy,
            total_candidates=total_candidates,
            query_text=query.query_text
        )

    def build_context_string(self, results: list[SearchResult]) -> str:
        """一键将检索到的 Top-K 结果组装拼接为符合 LLM 输入规范的 Context 上下文大字符串。

        Args:
            results: 检索结果列表

        Returns:
            str: 格式化的 Context 拼接文本
        """
        if not results:
            return "No relevant context found based on the query."

        context_blocks = []
        for idx, res in enumerate(results, start=1):
            block = (
                f"[Source {idx}] Title: {res.title or 'Unknown'}\n"
                f"Path: {res.source_path or 'Unknown'} > {res.section_path or 'Root'}\n"
                f"Content: {res.content.strip()}\n"
                f"---"
            )
            context_blocks.append(block)

        return "\n\n".join(context_blocks)


# ══════════════════════════════════════════════════════════════════════════════
# 主入口：混合检索功能演示
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 70)
    print("  微引擎 7：双路混合检索与 RRF 融合服务 — 功能演示")
    print("=" * 70)
    print("提示: 请运行测试用例以进行闭环验证")
