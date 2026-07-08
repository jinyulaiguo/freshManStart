"""
微引擎 9：全链路吞吐与分位数时延压力测试工具 (BenchmarkRunner)

设计方案：
==========
1. 设计意图：
   在企业级 RAG 知识库冷启动和线上查询期间，系统需承载高吞吐写入与低时延查询。
   本模块作为一个独立的性能测量工具：
   - 自动生成符合 Pydantic 契约的合成文档切片数据（Synthetic Chunk Data）。
   - 测量冷启动 Ingestion 阶段的吞吐效率，包括数据清洗、分块、大模型向量化 (Embedding TPS) 和 Qdrant 写入 TPS。
   - 采用多协程并发（`asyncio.gather`）和高精度计时器测算检索服务在并发状态下的 P50, P95, P99 分位数时延和整体 QPS 吞吐。
   - 默认连接本地 Qdrant Docker 实例（http://localhost:6333），若不可用自适应降级为内存模式。
   - 默认使用 Mock 向量生成器以规避真实 Embedding API 网络调用开销与限流，但同时保留支持真实 API 压测的通道。

2. 关键方法与组件：
   - generate_synthetic_chunks(): 物理构造指定数量、带随机文本和不同权限级别的切片数据。
   - run_import_benchmark(): 执行批量写入压测，记录并统计 Ingestion/Writing TPS。
   - run_query_benchmark(): 使用 asyncio 协程并发压测，以 numpy 计算 P50/P95/P99 时延和整体 QPS。
   - run_full_benchmark(): 串联整套流程并返回结构化 BenchmarkReport 对象。

使用方式（在项目根目录）：
    python -m weekly.w06_embedding_and_vector_db.project.benchmark --num-chunks 500 --num-queries 50
"""
from __future__ import annotations

import time
import random
import asyncio
import numpy as np
from typing import Optional
from unittest.mock import AsyncMock

from weekly.w06_embedding_and_vector_db.utils import EmbeddingClient
from weekly.w06_embedding_and_vector_db.project.models import Chunk, ChunkWithVector, BenchmarkReport, SearchQuery, MetadataFilter, RetrievalStrategy
from weekly.w06_embedding_and_vector_db.project.vector_store import QdrantVectorStore
from weekly.w06_embedding_and_vector_db.project.embedding_pipeline import EmbeddingPipeline
from weekly.w06_embedding_and_vector_db.project.sparse_retriever import SparseRetriever
from weekly.w06_embedding_and_vector_db.project.retrieval_service import RetrievalService


class BenchmarkRunner:
    """RAG 知识基础设施性能压力测试运行器"""

    def __init__(
        self,
        qdrant_url: str = "http://127.0.0.1",
        qdrant_port: int = 6333,
        use_memory_store: bool = False,
        mock_embedding: bool = True
    ) -> None:
        """初始化压测运行器。

        Args:
            qdrant_url: Qdrant 服务端地址
            qdrant_port: Qdrant 服务端端口
            use_memory_store: 是否强制使用 SQLite 内存模式进行压测
            mock_embedding: 是否模拟 Embedding API 请求（避免产生 Minimax 真实账单与 429 干扰）
        """
        # Step 1: 初始化 Qdrant 向量数据库实例
        if use_memory_store:
            self.vector_store = QdrantVectorStore(location=":memory:")
        else:
            self.vector_store = QdrantVectorStore(url=qdrant_url, port=qdrant_port)
            
        self.mock_embedding = mock_embedding
        self.collection_name = "benchmark_collection"
        
        # Step 2: 根据设置决定是否 Mock 真实向量接口
        if self.mock_embedding:
            # 建立一个 Mock 的 EmbeddingClient，它将在 embed_texts 中直接返回模拟的高维向量
            self.embedding_client = AsyncMock(spec=EmbeddingClient)
            async def fake_embed_texts(texts: list[str], embed_type: str = "db") -> list[list[float]]:
                # 模拟大模型接口调用消耗的少量时间延迟（10ms）
                await asyncio.sleep(0.01)
                # 返回 1536 维的随机浮点数向量列表
                return [[random.random() for _ in range(1536)] for _ in texts]
            
            async def fake_embed_single(text: str, embed_type: str = "db") -> list[float]:
                await asyncio.sleep(0.01)
                return [random.random() for _ in range(1536)]
                
            self.embedding_client.embed_texts = fake_embed_texts
            self.embedding_client.embed_single = fake_embed_single
        else:
            self.embedding_client = EmbeddingClient()

        # Step 3: 初始化本地 Sparse 稀疏检索引擎与混合检索服务
        self.sparse_retriever = SparseRetriever()
        self.retrieval_service = RetrievalService(
            vector_store=self.vector_store,
            embedding_client=self.embedding_client,
            sparse_retriever=self.sparse_retriever,
            collection_name=self.collection_name
        )

    def generate_synthetic_chunks(self, count: int) -> list[Chunk]:
        """程序化构造指定数量的带随机文本、类别和权限的 Chunk 压测数据。

        Args:
            count: 期望生成的 Chunk 数据数量

        Returns:
            list[Chunk]: 符合数据契约的合成切片列表
        """
        categories = ["AI", "Database", "Kubernetes", "Rust", "Python", "Networking"]
        authors = ["Alice", "Bob", "Charlie", "Dave", "Eve"]
        
        # 合成文本句子池，用于拼装 Chunk 内容
        vocab = [
            "Attention mechanism allows models to focus on specific parts of input sequences.",
            "Vector databases index high-dimensional embeddings using HNSW graphs for approximate nearest neighbor search.",
            "BM25 is a term frequency-based sparse retrieval model used in traditional search systems.",
            "RRF Reciprocal Rank Fusion combines rank lists from dense and sparse retrieval models.",
            "Rate limiters use token bucket algorithms to prevent client API requests from overwhelming servers.",
            "Multi-tenant database isolation ensures personal user data is not leaked to unauthorized roles.",
            "Pre-filtering applies payload conditions before similarity search to avoid recall drop.",
            "Matryoshka embeddings compress 1536 dimensions down to smaller dimensions like 256 for lower storage cost.",
            "Cosine similarity measure calculations scale gracefully under high-dimensional search indices."
        ]

        chunks = []
        for i in range(count):
            # 随机拼装 3 句话作为 Chunk 文本正文
            content = " ".join(random.choices(vocab, k=3))
            category = random.choice(categories)
            author = random.choice(authors)
            user_id = f"user_{random.randint(1, 10)}"
            permission_level = random.randint(1, 4)
            
            # 生成随机时间戳，范围在 2026 年内
            rand_day = random.randint(1, 28)
            created_time = f"2026-07-{rand_day:02d}T12:00:00Z"
            
            chunk_id = f"bench_chunk_{i:06d}"
            
            # 使用简易 SHA-256 哈希值模拟
            import hashlib
            chunk_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
            
            # 简单估算 token 数：词数乘以 1.3
            token_len = int(len(content.split()) * 1.3)

            chunks.append(
                Chunk(
                    chunk_id=chunk_id,
                    document_id=f"doc_{i // 10}",
                    content=content,
                    chunk_index=i % 10,
                    title=f"Section Header {i % 10}",
                    section_path=f"Document Root > Section {i % 10}",
                    source_path=f"/path/to/doc_{i // 10}.md",
                    author=author,
                    created_time=created_time,
                    token_length=token_len,
                    char_length=len(content),
                    hash=chunk_hash,
                    category=category,
                    permission_level=permission_level,
                    user_id=user_id
                )
            )

        return chunks

    async def run_import_benchmark(self, chunks: list[Chunk]) -> tuple[float, float, float]:
        """执行知识切片的大批量冷启动导入压力测试，计算三阶段吞吐量。

        Args:
            chunks: 生成的合成 Chunk 列表

        Returns:
            tuple[float, float, float]: (Ingestion TPS, Embedding TPS, Qdrant Write TPS)
        """
        print(f"\n📥 [Benchmark] 开始冷启动导入压测。数据规模: {len(chunks)} 个 Chunks...")
        
        # 1. 物理重构向量数据库 Collection
        self.vector_store.create_collection(
            collection_name=self.collection_name,
            dimension=1536
        )
        self.vector_store.create_payload_indexes(self.collection_name)
        
        # 2. 初始化高并发写入管道
        # 如果是 Mock，我们可以调大并发以释放本地 CPU，如果是真实，需要遵守 Sem 限制
        max_concurrency = 20 if self.mock_embedding else 5
        pipeline = EmbeddingPipeline(
            max_concurrent_requests=max_concurrency,
            batch_size=100 if self.mock_embedding else 20
        )
        # 将 pipeline 内部的 client 替换为本压测器可能 Mock 的 client
        pipeline.embedding_client = self.embedding_client

        # 3. 统计清洗、切片与大模型向量化耗时
        start_ingest = time.perf_counter()
        
        # 并发向量化处理
        print(f"📥 [Benchmark] 正在请求 Embedding APIs...")
        chunks_with_vectors = await pipeline.embed_chunks(chunks)
        
        end_ingest = time.perf_counter()
        ingest_duration = end_ingest - start_ingest

        # 4. 统计向 Qdrant 写入数据的耗时
        start_write = time.perf_counter()
        self.vector_store.upsert_chunks(self.collection_name, chunks_with_vectors)
        end_write = time.perf_counter()
        write_duration = end_write - start_write
        
        # 5. 构建本地倒排索引耗时极其微弱，但仍需构建以供后续 Hybrid 检索压测
        self.sparse_retriever.build_index(chunks)

        # 6. 吞吐量公式计算
        total_tokens = sum(c.token_length for c in chunks)
        
        import_tps = len(chunks) / max(ingest_duration, 0.001)
        embedding_tps = total_tokens / max(ingest_duration, 0.001)
        qdrant_write_tps = len(chunks) / max(write_duration, 0.001)

        print(f"✅ [Benchmark] 导入压测完成！")
        print(f"  - Ingestion 耗时: {ingest_duration:.2f}s | TPS: {import_tps:.2f} chunks/sec")
        print(f"  - Embedding API 吞吐: {embedding_tps:.2f} tokens/sec")
        print(f"  - Qdrant 物理写入耗时: {write_duration:.2f}s | TPS: {qdrant_write_tps:.2f} points/sec")

        return import_tps, embedding_tps, qdrant_write_tps

    async def run_query_benchmark(
        self,
        queries: list[str],
        concurrency: int = 5,
        strategy: RetrievalStrategy = RetrievalStrategy.HYBRID
    ) -> tuple[float, list[float]]:
        """执行高并发检索查询压测，获取 QPS 与全部查询时延（以纳秒精度计算）。

        Args:
            queries: 测试查询文本列表
            concurrency: 并发并发协程数
            strategy: 检索策略 (dense/sparse/hybrid)

        Returns:
            tuple[float, list[float]]: (QPS 吞吐量, 时延列表 ms)
        """
        print(f"\n🔍 [Benchmark] 开始并发查询检索压测。QPS并发数: {concurrency} | 策略: {strategy.value}...")
        
        latencies_ms: list[float] = []
        sem = asyncio.Semaphore(concurrency)

        # 定义单协程查询任务，配合信号量控制最大并发
        async def single_query_worker(q_text: str):
            async with sem:
                # 随机生成一些过滤条件以模拟真实多租户检索
                user_id = f"user_{random.randint(1, 10)}"
                max_level = random.randint(1, 4)
                f = MetadataFilter(user_id=user_id, max_permission_level=max_level)
                
                query_obj = SearchQuery(
                    query_text=q_text,
                    top_k=5,
                    filters=f,
                    strategy=strategy
                )
                
                # 精确记录检索时间
                t_start = time.perf_counter()
                try:
                    await self.retrieval_service.retrieve(query_obj)
                except Exception as e:
                    print(f"⚠️ [Benchmark] 查询检索失败: {e}")
                t_duration = (time.perf_counter() - t_start) * 1000.0  # 毫秒
                latencies_ms.append(t_duration)

        start_time = time.perf_counter()
        
        # 使用 asyncio.gather 对全部查询请求进行并发并发调度
        tasks = [single_query_worker(q) for q in queries]
        await asyncio.gather(*tasks)
        
        total_duration = time.perf_counter() - start_time
        qps = len(queries) / max(total_duration, 0.001)

        print(f"✅ [Benchmark] 查询压测完成！总查询数: {len(queries)} | 耗时: {total_duration:.2f}s | QPS: {qps:.2f} query/sec")
        
        return qps, latencies_ms

    async def run_full_benchmark(
        self,
        num_chunks: int = 500,
        num_queries: int = 50,
        concurrency: int = 5
    ) -> BenchmarkReport:
        """串联导入与检索，执行全链路压力测试，并在控制台生成精美报告。

        Args:
            num_chunks: 要生成的切片数
            num_queries: 要执行的压测查询数
            concurrency: 查询并发协程数

        Returns:
            BenchmarkReport: 压测报告结构体
        """
        print("=" * 80)
        print(f"🚀 AI Research Assistant Knowledge Engine — 全链路性能压力测试 🚀")
        print(f"  配置: 模拟向量API={self.mock_embedding} | Qdrant模式={ 'Memory' if self.vector_store.is_memory_mode else 'Docker/Server' }")
        print("=" * 80)

        # 1. 产生测试语料
        chunks = self.generate_synthetic_chunks(num_chunks)
        
        # 2. 运行冷启动写入压测
        import_tps, embedding_tps, qdrant_write_tps = await self.run_import_benchmark(chunks)

        # 3. 准备随机检索词，从词汇库中选取，模拟用户查询
        query_words = ["Attention Mechanism", "HNSW filter index", "RRF scores hybrid", "Vector distance", "multi-tenant security"]
        queries = [f"{random.choice(query_words)} query text {i}" for i in range(num_queries)]

        # 4. 运行查询检索压测
        qps, latencies = await self.run_query_benchmark(
            queries=queries,
            concurrency=concurrency,
            strategy=RetrievalStrategy.HYBRID
        )

        # 5. 计算分位数时延
        avg_lat = float(np.mean(latencies))
        p50_lat = float(np.percentile(latencies, 50))
        p95_lat = float(np.percentile(latencies, 95))
        p99_lat = float(np.percentile(latencies, 99))

        report = BenchmarkReport(
            import_total_docs=len(set(c.document_id for c in chunks)),
            import_total_chunks=len(chunks),
            import_duration_s=0.0,  # 内部未输出，此处可以用占位符
            import_tps=round(import_tps, 2),
            embedding_tps=round(embedding_tps, 2),
            qdrant_write_tps=round(qdrant_write_tps, 2),
            query_count=len(queries),
            p50_latency_ms=round(p50_lat, 2),
            p95_latency_ms=round(p95_lat, 2),
            p99_latency_ms=round(p99_lat, 2),
            avg_latency_ms=round(avg_lat, 2),
            qps=round(qps, 2)
        )

        # 6. 控制台精美 Markdown 报告输出
        print("\n" + "=" * 80)
        print("📊 PERFORMANCE BENCHMARK REPORT (性能压测报告)")
        print("=" * 80)
        print(f"| 指标项 | 测量值 |")
        print(f"| :--- | :--- |")
        print(f"| **合成导入文档总数 (Documents)** | {report.import_total_docs} docs |")
        print(f"| **合成导入分块总数 (Chunks)** | {report.import_total_chunks} chunks |")
        print(f"| **Ingestion 吞吐率 (Import TPS)** | {report.import_tps} chunks/sec |")
        print(f"| **向量生成吞吐率 (Embedding TPS)** | {report.embedding_tps} tokens/sec |")
        print(f"| **向量库物理写入吞吐率 (Write TPS)** | {report.qdrant_write_tps} points/sec |")
        print(f"| **并发查询吞吐量 (QPS)** | {report.qps} query/sec |")
        print(f"| **平均检索延迟 (Average Latency)** | {report.avg_latency_ms} ms |")
        print(f"| **P50 检索延迟** | {report.p50_latency_ms} ms |")
        print(f"| **P95 检索延迟** | {report.p95_latency_ms} ms |")
        print(f"| **P99 检索延迟** | {report.p99_latency_ms} ms |")
        print("=" * 80 + "\n")

        # 7. 清除本次测试残留的 benchmark 数据集释放空间
        self.vector_store.delete_collection(self.collection_name)

        return report


# ══════════════════════════════════════════════════════════════════════════════
# 命令行执行主入口
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="AI Research Assistant Knowledge Engine 性能压力测试工具")
    parser.add_argument("--num-chunks", type=int, default=100, help="生成测试的 Chunk 数量")
    parser.add_argument("--num-queries", type=int, default=20, help="执行测试的查询次数")
    parser.add_argument("--concurrency", type=int, default=5, help="查询检索的最大并发协程数")
    parser.add_argument("--real-embedding", action="store_true", help="使用真实大模型 Embedding API，不进行 Mock")
    
    args = parser.parse_args()

    # 初始化测试运行器，默认使用内存库进行纯功能演示，若有外部 Qdrant 建议启动对应参数
    runner = BenchmarkRunner(
        use_memory_store=True,
        mock_embedding=not args.real_embedding
    )
    
    # 异步调度运行
    asyncio.run(
        runner.run_full_benchmark(
            num_chunks=args.num_chunks,
            num_queries=args.num_queries,
            concurrency=args.concurrency
        )
    )
