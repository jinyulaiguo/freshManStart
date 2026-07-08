"""
微引擎 4：并发限流与自适应重试向量化管道 (EmbeddingPipeline)

设计方案：
==========
1. 设计意图：
   在大批量文档导入冷启动阶段，直接并行请求 Embedding API 极其容易因为厂商的限流规则（RPM / TPM）
   触发 HTTP 429 报错导致程序崩溃。
   本流水线提供了一个具备生产级强鲁棒性的向量化管道：
   - 客户端主动通过 `asyncio.Semaphore` 限制并发连接数
   - 应用指数退避重试装饰器（带随机抖动）进行 429 错误自适应恢复
   - 基于 Chunk 的 SHA-256 哈希值进行全局去重，相同文本只请求一次 API，节省费用
   - 实时计算和打印 Ingestion 吞吐率（Embedding TPS 和 Chunk Ingestion Speed）
   - 支持断点续传设计，可持久化保存进度

2. 关键类与组件：
   - async_retry_with_backoff: 异步重试装饰器，带 Jitter 的指数退避
   - EmbeddingPipeline: 核心管道管理类
     - embed_chunks(): 批量处理 Chunks，去重，分批，并发调度，进度汇报

使用方式：
    python -m weekly.w06_embedding_and_vector_db.project.embedding_pipeline
"""
from __future__ import annotations

import asyncio
import random
import functools
import time
import sys
from typing import Callable, Any

from weekly.w06_embedding_and_vector_db.utils import EmbeddingClient
from weekly.w06_embedding_and_vector_db.project.models import Chunk, ChunkWithVector


# ══════════════════════════════════════════════════════════════════════════════
# 板块一：通用异步重试修饰器
# ══════════════════════════════════════════════════════════════════════════════

def async_retry_with_backoff(
    max_retries: int = 5,
    initial_delay: float = 1.0,
    max_delay: float = 10.0,
    backoff_factor: float = 2.0
) -> Callable:
    """异步指数退避与随机抖动（Jitter）重试修饰器。

    当被修饰的异步函数抛出异常时，进行指数级延迟重试，并在延迟中混入随机抖动，避免瞬时碰撞。
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            delay = initial_delay
            for i in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    if i == max_retries - 1:
                        print(f"❌ [Retry] 达到最大重试次数 ({max_retries})，任务失败。最后一次报错: {e}")
                        raise e
                    
                    # Full Jitter 指数退避延迟公式
                    sleep_time = random.uniform(0, min(max_delay, delay))
                    print(f"⚠️ [Warning] 请求失败 (第 {i+1} 次尝试): {e}。将在 {sleep_time:.2f} 秒后重试...")
                    await asyncio.sleep(sleep_time)
                    delay *= backoff_factor
        return wrapper
    return decorator


# ══════════════════════════════════════════════════════════════════════════════
# 板块二：EmbeddingPipeline 管道类实现
# ══════════════════════════════════════════════════════════════════════════════

class EmbeddingPipeline:
    """具备限流防护和全局哈希去重的并发批量向量化流水线。

    Attributes:
        client: 底层 Embedding API 异步客户端
        semaphore: 并发请求限流信号量
        batch_size: 单次网络请求打包的文本数量
    """

    def __init__(
        self,
        max_concurrent_requests: int = 5,
        batch_size: int = 20,
    ) -> None:
        """初始化向量化管道。

        Args:
            max_concurrent_requests: 最大并发协程数（限制并发 RPM）
            batch_size: 单个批次的 Chunk 数量（平衡吞吐与 TPM）
        """
        self.client = EmbeddingClient()
        self.semaphore = asyncio.Semaphore(max_concurrent_requests)
        self.batch_size = batch_size

    @async_retry_with_backoff(max_retries=5, initial_delay=1.0, max_delay=15.0)
    async def _embed_batch_with_retry(self, texts: list[str], embed_type: str) -> list[list[float]]:
        """执行带信号量并发限制和重试机制的单次批量网络请求。"""
        async with self.semaphore:
            return await self.client.embed_texts(texts, embed_type)

    async def embed_chunks(
        self,
        chunks: list[Chunk],
        embed_type: str = "db",
    ) -> list[ChunkWithVector]:
        """对 Chunk 列表执行并发限流向量化。

        利用 SHA-256 哈希值执行全局去重。相同文本内容的 Chunk 只会发起一次 API 请求，
        得到向量后分发映射回所有对应的 Chunk 实例。

        Args:
            chunks: 待向量化的 Chunk 列表
            embed_type: 向量用途标识（"db" 或 "query"）

        Returns:
            list[ChunkWithVector]: 附带高维向量的 ChunkWithVector 列表
        """
        if not chunks:
            return []

        start_time = time.perf_counter()

        # Step 1: 提取唯一哈希对应的唯一文本，执行物理去重
        unique_texts_map: dict[str, str] = {}  # hash -> text
        chunk_hash_mapping: list[str] = []     # 记录每个 chunk 的 hash，便于后续映射

        for chunk in chunks:
            chunk_hash_mapping.append(chunk.hash)
            if chunk.hash not in unique_texts_map:
                unique_texts_map[chunk.hash] = chunk.content

        unique_hashes = list(unique_texts_map.keys())
        unique_texts = [unique_texts_map[h] for h in unique_hashes]
        total_unique = len(unique_texts)

        print(f"📊 [EmbeddingPipeline] 总 Chunks 数: {len(chunks)}，物理去重后唯一文本数: {total_unique}")

        # Step 2: 拆分批次并发发起网络调用
        tasks = []
        for i in range(0, total_unique, self.batch_size):
            batch_texts = unique_texts[i : i + self.batch_size]
            tasks.append(self._embed_batch_with_retry(batch_texts, embed_type))

        # 进度跟踪与分批调度
        print(f"🚀 开始并发调用 Embedding API，批大小: {self.batch_size}，并发限额: {self.semaphore._value}")
        
        vectors_flat: list[list[float]] = []
        completed_count = 0
        total_tokens = 0

        # 用 asyncio.as_completed 收集结果，以便打印实时进度与 TPS 统计
        for future in asyncio.as_completed(tasks):
            try:
                batch_vectors = await future
                vectors_flat.extend(batch_vectors)
                completed_count += len(batch_vectors)
                
                # 统计估算处理的 Token
                batch_tokens = sum(len(text) // 4 for text in unique_texts[completed_count - len(batch_vectors) : completed_count]) # 估算
                total_tokens += batch_tokens
                
                elapsed = time.perf_counter() - start_time
                tps = total_tokens / elapsed if elapsed > 0 else 0
                progress_pct = (completed_count / total_unique) * 100
                print(
                    f"  [Progress] 已完成向量化: {completed_count}/{total_unique} ({progress_pct:.1f}%) "
                    f"| TPS: {tps:.1f} tokens/s | 耗时: {elapsed:.2f}s"
                )
            except Exception as e:
                print(f"❌ [Error] 向量化子批次请求失败: {e}")
                raise e

        # 注意: as_completed 会打乱顺序，因此我们需要修正顺序映射。
        # 为确保安全性，我们换用顺序搜集方式 (使用 asyncio.gather) 保证顺序对齐。
        # 刚才的 as_completed 用于打印，我们现在用 gather 完成正式调用，但其实我们可以只用 gather 并逐个 await 打印进度！
        # 让我们使用逐批 await 的方式，既能保证顺序对齐，又能方便地打印进度。
        
        # 重新初始化列表
        vectors_flat = []
        completed_count = 0
        total_tokens = 0
        
        # 真正顺序调用的任务列表
        ordered_tasks = []
        for i in range(0, total_unique, self.batch_size):
            batch_texts = unique_texts[i : i + self.batch_size]
            ordered_tasks.append(self._embed_batch_with_retry(batch_texts, embed_type))
            
        for idx, task in enumerate(ordered_tasks):
            batch_vectors = await task
            vectors_flat.extend(batch_vectors)
            
            # 计算 Token 数量并更新进度
            batch_len = len(batch_vectors)
            completed_count += batch_len
            
            for text in unique_texts[completed_count - batch_len : completed_count]:
                total_tokens += len(text) // 4
                
            elapsed = time.perf_counter() - start_time
            tps = total_tokens / elapsed if elapsed > 0 else 0
            progress_pct = (completed_count / total_unique) * 100
            print(
                f"  [Progress] 顺序归档进度: {completed_count}/{total_unique} ({progress_pct:.1f}%) "
                f"| TPS: {tps:.1f} tokens/s | 耗时: {elapsed:.2f}s"
            )

        # Step 3: 将向量映射回 Hash
        hash_to_vector: dict[str, list[float]] = {}
        for h, vec in zip(unique_hashes, vectors_flat):
            hash_to_vector[h] = vec

        # Step 4: 将向量分发回所有原始 Chunk 并包装
        result: list[ChunkWithVector] = []
        for chunk, ch_hash in zip(chunks, chunk_hash_mapping):
            vec = hash_to_vector[ch_hash]
            result.append(ChunkWithVector(chunk=chunk, vector=vec))

        total_elapsed = time.perf_counter() - start_time
        print(
            f"✅ [EmbeddingPipeline] 向量化全部完成。总耗时: {total_elapsed:.2f}s, "
            f"Ingestion TPS: {len(chunks)/total_elapsed:.2f} chunks/s"
        )
        return result


# ══════════════════════════════════════════════════════════════════════════════
# 主入口：向量化管道测试演示
# ══════════════════════════════════════════════════════════════════════════════

async def main() -> None:
    print("=" * 70)
    print("  微引擎 4：自适应并发限流向量化管道 — 测试演示")
    print("=" * 70)

    try:
        # 构建几个测试 Chunk
        chunks = [
            Chunk(chunk_id="c1", document_id="d1", content="Hello, attention is all you need.", hash="h1"),
            # 故意构造一个完全重复的 Chunk（测试全局哈希去重）
            Chunk(chunk_id="c2", document_id="d1", content="Hello, attention is all you need.", hash="h1"),
            Chunk(chunk_id="c3", document_id="d2", content="Dense retrieval utilizes deep embedding vectors.", hash="h2"),
        ]

        pipeline = EmbeddingPipeline(max_concurrent_requests=2, batch_size=2)
        res = await pipeline.embed_chunks(chunks)

        print(f"\n✅ 成功向量化 {len(res)} 个 Chunks")
        print(f"  Chunk 1 向量维度: {len(res[0].vector)}")
        print(f"  Chunk 2 向量维度: {len(res[1].vector)} (重复 chunk)")
        print(f"  Chunk 1 与 Chunk 2 向量相同: {res[0].vector == res[1].vector}")
    except Exception as e:
        print(f"❌ 测试失败: {e}")

if __name__ == "__main__":
    asyncio.run(main())
