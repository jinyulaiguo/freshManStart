"""
Day 39 参考答案 — 分批向量化、批量插入与大模型限流 (Rate Limit) 自适应保护

设计方案：
==========
1. 设计意图：
   本文件是 Day 39 的标准参考答案实现。当系统需要向向量数据库中冷启动导入大量文本数据时，
   直接请求 Embedding API 极易因为服务商的限流规则（RPM / TPM）导致 HTTP 429 崩溃。
   本流水线在客户端主动使用 `asyncio.Semaphore` 限制并发协程，
   并在装饰器层实现带随机抖动的指数退避（Exponential Backoff with Full Jitter）重试算法，
   确保海量文档数据在面临网络抖动和限流时具备极高的自愈与自适应能力。

2. 关键组件结构：
   - async_retry_with_backoff: 通用异步指数退避与 Full Jitter 重试装饰器。
   - QdrantImportPipeline: 并发限流与退避的向量导入流水线类。
     - create_collection(): 重建/初始化 Qdrant 集合。
     - embed_batch_with_retry(): 单个 Batch 发起网络 Embedding 调用，配合 Semaphore 限制并发连接，并挂载重试装饰器实现异常自愈。
     - import_text_documents(): 拆分文档批次，通过 asyncio.gather 并发调度拉取向量，并批量写入 Qdrant。
     - delete_collection(): 清理集合释放空间。

3. 关键数据流向与 Benchmark 验证：
   - 实例化 `QdrantImportPipeline`，自动探测本地 Docker 实例，如无 Docker 降级到内存模式。
   - 生成 500 个文本段落（每段 1,000 字符，总计 50 万字符）。
   - 将文本按 batch_size = 20 分组，并设置限制并发数为 2。
   - 启动异步导入。在真实网络或触发 API 限流时，指数退避装饰器进行毫秒/秒级自适应睡眠后重试。
   - 100% 成功导入后，进行物理清理。

使用方式（在项目根目录）：
    python -m weekly.w06_embedding_and_vector_db.day39.rate_limit_pipeline
"""
from __future__ import annotations

import asyncio
import random
import functools
import time
import sys

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, CollectionStatus
from weekly.w06_embedding_and_vector_db.utils import EmbeddingClient


# ══════════════════════════════════════════════════════════════════════════════
# 板块一：通用异步指数退避重试装饰器
# ══════════════════════════════════════════════════════════════════════════════

def async_retry_with_backoff(
    max_retries: int = 5,
    initial_delay: float = 1.0,
    max_delay: float = 10.0,
    backoff_factor: float = 2.0
):
    """异步指数退避与随机抖动（Jitter）重试修饰器。

    当被修饰的异步函数抛出异常时，进行指数级延迟重试，并在延迟中混入随机抖动，避免冲突。

    Args:
        max_retries: 最大重试次数
        initial_delay: 首次重试的最大延迟时间（秒）
        max_delay: 最大延迟等待时间上限（秒）
        backoff_factor: 指数递增因子

    Returns:
        decorator: 装配完成的修饰器
    """
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            for i in range(max_retries):
                try:
                    # 尝试执行原异步函数
                    return await func(*args, **kwargs)
                except Exception as e:
                    # 如果达到最大重试次数，将异常抛出，中断程序
                    if i == max_retries - 1:
                        print(f"❌ 达到最大重试次数 ({max_retries})，任务彻底失败，最后一次报错: {e}")
                        raise e
                    
                    # 依据指数退避公式计算延迟基数（随着重试次数的增加呈指数递增）
                    base_delay = min(max_delay, initial_delay * (backoff_factor ** i))
                    
                    # Full Jitter 随机抖动：在 [0, base_delay] 中随机产生本次睡眠的时长
                    # 从而将重试的请求错峰分散在时间轴上，避免“惊群效应”
                    wait_time = random.uniform(0, base_delay)
                    
                    print(
                        f"⚠️ 协程 '{func.__name__}' 执行报错: {e}。\n"
                        f"   正在执行防御性退避重试 (第 {i+1}/{max_retries-1} 次)... "
                        f"等待挂起 {wait_time:.2f} 秒..."
                    )
                    
                    # 异步挂起，释放 CPU 和线程控制权
                    await asyncio.sleep(wait_time)
        return wrapper
    return decorator


# ══════════════════════════════════════════════════════════════════════════════
# 板块二：QdrantImportPipeline 完整实现
# ══════════════════════════════════════════════════════════════════════════════

class QdrantImportPipeline:
    """具备并发控制与限流自愈功能的向量导入流水线类"""

    def __init__(
        self,
        qdrant_url: str | None = None,
        qdrant_port: int = 6333,
        qdrant_location: str | None = None,
        concurrency_limit: int = 3
    ) -> None:
        """初始化客户端并配置信号量控制。"""
        self.is_memory_mode = False
        
        # 初始化 Qdrant 客户端
        if qdrant_location == ":memory:":
            self.qdrant_client = QdrantClient(location=":memory:")
            self.is_memory_mode = True
            print("💡 Qdrant 客户端已启动为指定内存模式 (:memory:)")
        else:
            target_url = qdrant_url or "http://127.0.0.1"
            try:
                self.qdrant_client = QdrantClient(url=target_url, port=qdrant_port, timeout=2.0)
                self.qdrant_client.get_collections()
                print(f"✅ 成功连接到本地 Qdrant Docker 实例: {target_url}:{qdrant_port}")
            except Exception as e:
                print(
                    f"⚠ 无法连接到 Qdrant Docker 服务 ({target_url}:{qdrant_port})，"
                    f"错误原因: {e}。\n"
                    f"👉 导入流水线自适应降级到本地内存模式 (:memory:)...",
                    file=sys.stderr
                )
                self.qdrant_client = QdrantClient(location=":memory:")
                self.is_memory_mode = True

        # 初始化文本向量化客户端（内含 load_env 加载）
        self.embedding_client = EmbeddingClient()
        
        # 协程并发信号量：卡控最大同时活跃的网络请求，硬限流
        self.semaphore = asyncio.Semaphore(concurrency_limit)

    def create_collection(
        self,
        collection_name: str,
        vector_size: int,
        distance: Distance = Distance.COSINE
    ) -> bool:
        """在 Qdrant 中创建或重建集合。"""
        if self.qdrant_client.collection_exists(collection_name):
            self.qdrant_client.delete_collection(collection_name)
        self.qdrant_client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=vector_size, distance=distance)
        )
        return True

    # 挂载带有 Full Jitter 的重试修饰器
    # 遇到 429 报错或网络抖动会自动执行指数退避重试，最大重试 5 次
    @async_retry_with_backoff(max_retries=5, initial_delay=1.0, max_delay=8.0)
    async def embed_batch_with_retry(self, texts: list[str]) -> list[list[float]]:
        """获取并发信号量后调用 API 获取向量，并在失败时自动重试。"""
        # Step 1: 竞争信号量锁，如果当前活跃请求达到 concurrency_limit，在此非阻塞挂起等待
        async with self.semaphore:
            # Step 2: 发起真实 HTTP 网络调用
            return await self.embedding_client.embed_texts(texts, embed_type="db")

    async def import_text_documents(
        self,
        collection_name: str,
        documents: list[str],
        ids: list[int | str],
        batch_size: int = 20
    ) -> int:
        """异步并发、安全无损地将海量文档向量化并存入 Qdrant 集合。

        Args:
            collection_name: Qdrant 写入目标集合
            documents: 待向量化的文本段落列表
            ids: 向量的 ID 列表
            batch_size: 单批拉取向量的文本条数

        Returns:
            int: 成功导入的点数总和
        """
        # Step 1: 输入防御性检查
        if len(documents) != len(ids):
            raise ValueError(f"文档数 ({len(documents)}) 与 ID 数 ({len(ids)}) 不匹配！")

        # Step 2: 切片大文档与 ID 列表为多个 batches
        batched_docs = [documents[i:i + batch_size] for i in range(0, len(documents), batch_size)]
        batched_ids = [ids[i:i + batch_size] for i in range(0, len(ids), batch_size)]

        # Step 3: 创建并发任务列表
        tasks = []
        for idx, doc_batch in enumerate(batched_docs):
            # 将每个 batch 交给 embed_batch_with_retry 管理
            # 注意：这里还没有开始真正执行网络调用，只是包装成了 coroutine
            tasks.append(self.embed_batch_with_retry(doc_batch))

        print(f"🚀 流水线启动！共切分为 {len(tasks)} 个 Batches，每批大小 {batch_size} 条...")
        start_time = time.time()
        
        # Step 4: 通过 asyncio.gather 统一并发并发调度
        # 由于 embed_batch_with_retry 内部装配了信号量，虽然我们在 gather 里一次性发起了全部任务，
        # 但底层最多只会有 concurrency_limit 个协程同时跟 API 进行网络交互。
        all_vectors = await asyncio.gather(*tasks)
        
        print(f"✅ 并发网络向量化全部拉取完毕！总耗时: {time.time() - start_time:.2f}s")

        # Step 5: 扁平化拉回的向量
        flat_vectors = []
        for vec_batch in all_vectors:
            flat_vectors.extend(vec_batch)

        if len(flat_vectors) != len(documents):
            raise RuntimeError(f"预期生成向量数 ({len(documents)}) 与实际拉回数 ({len(flat_vectors)}) 不一致！")

        # Step 6: 组装 PointStruct 并导入数据库
        print(f"⏳ 正在向 Qdrant 写入 {len(flat_vectors)} 条向量...")
        points = [
            PointStruct(
                id=idx,
                vector=vec,
                payload={"content": doc}
            )
            for idx, vec, doc in zip(ids, flat_vectors, documents)
        ]

        # 写入数据库，Qdrant 官方 upsert 内置了批量导入的优化
        self.qdrant_client.upsert(collection_name=collection_name, points=points)
        return len(points)

    def delete_collection(self, collection_name: str) -> bool:
        """注销并删除集合。"""
        if self.qdrant_client.collection_exists(collection_name):
            self.qdrant_client.delete_collection(collection_name)
            print(f"🧹 成功删除集合 '{collection_name}' 并物理清理资源")
            return True
        return False


# ══════════════════════════════════════════════════════════════════════════════
# 板块三：真实 API 导入压测与自适应验证入口
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("======================================================================")
    print("🏆 Day 39 过关验证：50 万字并发导入压测与 API 限流（Rate Limit）退避自愈")
    print("======================================================================")

    # 优先连接本地 Qdrant Docker 实例，如无 Docker 自动平滑降级至内存模式
    # 并发信号量限制为 2，以稳定速率向前拉取 API
    pipeline = QdrantImportPipeline(concurrency_limit=2)
    
    collection = "day39_rate_limit_benchmark"
    vector_dim = 1536  # embo-01 模型维度
    
    async def main():
        try:
            # Step 1: 创建集合
            pipeline.create_collection(collection, vector_dim)

            # Step 2: 构造包含 50 万字符的文本语料
            # 共 500 个段落，每个段落约 1,000 个中文字符，模拟大规模数据冷启动
            print("\n⏳ 正在本地生成 500 个段落（共 500,000 字符）测试数据...")
            base_text = (
                "这一段文本用于模拟AI研究助手底座系统的冷启动大规模数据处理压测。在真实环境下，"
                "大批量的自然语言文档会被切分成多个Chunk片段，随后请求大模型的Embedding接口获取高维语义向量。"
                "由于厂商接口有严格的每分钟请求限制和Token限制，高强度的并发会频繁触发429限流状态。"
                "利用自适应指数退避和 Full Jitter 随机抖动重试机制，能够将请求波峰物理平滑化，最终达到100%成功入库的目的。"
                "我们需要确保该流水线在高并发压力下依然稳定前行，不抛出异常，不丢失数据。"
            )
            # 重复 5 次刚好接近 1000 字
            para = base_text * 5
            documents = [f"[段落 {i+1}] " + para for i in range(500)]
            ids = list(range(1000, 1500))
            print("✅ 50 万字模拟语料生成就绪！")

            # Step 3: 开始运行并发导入
            # 单批拉取 20 条，并发运行 500 / 20 = 25 个并发批次
            print(f"\n🚀 开始执行高并发分批文本向量化导入...")
            start_time = time.time()
            
            imported_count = await pipeline.import_text_documents(
                collection_name=collection,
                documents=documents,
                ids=ids,
                batch_size=20
            )
            
            duration = time.time() - start_time
            print(f"\n🎉 导入工作流圆满成功！")
            print(f"📈 累计成功写入向量: {imported_count} 条")
            print(f"⏱ 累计耗时: {duration:.2f} 秒")
            print(f"📊 平均写入速度: {imported_count / duration:.2f} 条/秒")

            # Step 4: 数据库实际量校验
            print("\n📊 集合最终运行期指标详情:")
            info = pipeline.qdrant_client.get_collection(collection)
            print(f"   - 向量数量 (Points Count): {info.points_count}")
            print(f"   - 集合状态 (Collection Status): {info.status.name}")

        except Exception as e:
            print("\n💥 运行过程中抛出意外异常:")
            import traceback
            traceback.print_exc()
            
        finally:
            # Step 5: 清理现场
            print("\n🧹 清理测试 Collection 资源...")
            pipeline.delete_collection(collection)
            print("🏁 Day 39 过关压测测试结束！")
            print("======================================================================")

    # 启动异步事件循环
    asyncio.run(main())
