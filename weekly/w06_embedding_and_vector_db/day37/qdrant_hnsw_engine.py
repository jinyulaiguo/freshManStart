"""
Day 37 参考答案 — Chroma / Qdrant 向量数据库原理与本地 HNSW 索引部署

设计方案：
==========
1. 设计意图：
   本文件是 Day 37 的标准参考答案实现。针对在大大规模 Agent 知识库（RAG）场景下，暴力检索带来的高时延与高 CPU 负载痛点，
   本类封装了基于 Qdrant 的高吞吐量数据导入及 HNSW 索引调优客户端。
   为了保证学员在无 Docker 运行环境下的平滑学习，本类在构造函数中实现了自动ping探测连接，若本地 Docker 不可用，
   则平滑、零中断地自动降级到 SQLite 支持的进程内内存模式 (`:memory:`)。

2. 关键组件结构：
   - QdrantHnswEngine: 核心向量存储与检索类
     - create_collection(): 生命周期管理，配置 HNSW 参数 (m, ef_construct)
     - batch_upsert(): 分批并发写入，且针对内存模式做线程锁避让设计
     - wait_for_indexing(): 轮询检测优化器是否已将 HNSW 树全部归档并进入 GREEN 就绪状态
     - search(): 动态带 ef 参数的近似最近邻 (ANN) 检索（基于最新的 query_points API 实现）
     - delete_collection(): 集合物理注销

3. 关键数据流向：
   测试主入口：
   1. 自动探针确定连接模式 (Docker vs 内存)
   2. 随机生成 10,000 条 1536 维度的模拟文本向量（避免产生真实 API 费用）
   3. 并发写入数据库，按 batch_size = 2000 切片，ThreadPoolExecutor 并发（Docker 模式下）
   4. 测量 HNSW 索引合并就绪的时延
   5. 模拟 Agent 进行 10 次 ANN 检索，计算并打印平均响应时延
   6. 物理清理资源，保证测试环境无污染。

使用方式（在项目根目录）：
    python -m weekly.w06_embedding_and_vector_db.day37.qdrant_hnsw_engine
"""
from __future__ import annotations

import time
import sys
import numpy as np
from concurrent.futures import ThreadPoolExecutor

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    HnswConfigDiff,
    PointStruct,
    SearchParams,
    CollectionStatus
)


# ══════════════════════════════════════════════════════════════════════════════
# 板块一：QdrantHnswEngine 完整实现
# ══════════════════════════════════════════════════════════════════════════════

class QdrantHnswEngine:
    """基于 Qdrant 的高性能 HNSW 向量检索与索引分析引擎（标准版）

    封装了 Collection 管理、高吞吐批量并发写入、状态就绪轮询及 ANN 查询逻辑。
    支持自动探测并自适应降级至内存模式。

    Attributes:
        client: QdrantClient 实例
        is_memory_mode: 是否运行在进程内内存模式下
    """

    def __init__(self, url: str | None = None, port: int = 6333, location: str | None = None) -> None:
        """初始化 Qdrant 客户端，具备自适应防错降级机制。

        如果指定了 location，则直接使用（例如 ":memory:"）；
        否则优先连接本地 http://localhost:6333，若连接失败则自动降级到内存模式 (:memory:)。
        """
        self.is_memory_mode = False
        
        # Step 0: 显式指定内存模式
        if location == ":memory:":
            self.client = QdrantClient(location=":memory:")
            self.is_memory_mode = True
            print("💡 Qdrant 客户端已启动为指定内存模式 (:memory:)")
            return

        # Step 1: 尝试连接外部本地 Docker 实例
        target_url = url or "http://127.0.0.1"
        try:
            # 建立一个短超时的客户端进行连接探测
            self.client = QdrantClient(url=target_url, port=port, timeout=2.0)
            # 调用轻量级方法以验证连接是否畅通
            self.client.get_collections()
            print(f"✅ 成功连接到本地 Qdrant Docker 实例: {target_url}:{port}")
        except Exception as e:
            # Step 2: 降级防御
            print(
                f"⚠ 无法连接到 Qdrant Docker 服务 ({target_url}:{port})，"
                f"错误原因: {e}。\n"
                f"👉 引擎自适应降级到本地内存模式 (:memory:)...",
                file=sys.stderr
            )
            self.client = QdrantClient(location=":memory:")
            self.is_memory_mode = True

    def create_collection(
        self,
        collection_name: str,
        vector_size: int,
        distance: Distance = Distance.COSINE,
        m: int = 16,
        ef_construct: int = 100
    ) -> bool:
        """在 Qdrant 中创建或重建一个向量集合，并配置 HNSW 索引参数。

        Args:
            collection_name: 集合名称
            vector_size: 向量的几何维度（如 1536）
            distance: 距离度量函数类型（如 Distance.COSINE 或 Distance.EUCLID）
            m: HNSW 节点最大连接数（默认 16）
            ef_construct: HNSW 构建期邻居搜索范围（默认 100）

        Returns:
            bool: 创建成功返回 True
        """
        # Step 1: 防御性清理老集合
        if self.client.collection_exists(collection_name):
            print(f"🧹 发现已存在的同名集合 '{collection_name}'，正在执行物理清理...")
            self.client.delete_collection(collection_name)
        
        # Step 2: 创建新集合并显式配置 HNSW 参数与向量参数
        self.client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(
                size=vector_size,
                distance=distance
            ),
            hnsw_config=HnswConfigDiff(
                m=m,
                ef_construct=ef_construct
            )
        )
        print(f"✨ 集合 '{collection_name}' 创建成功，参数: dim={vector_size}, distance={distance.name}, m={m}, ef_construct={ef_construct}")
        return True

    def batch_upsert(
        self,
        collection_name: str,
        ids: list[int | str],
        vectors: list[list[float]],
        payloads: list[dict] | None = None,
        batch_size: int = 500,
        max_workers: int = 4
    ) -> int:
        """高吞吐分批写入向量数据到指定集合中。

        Args:
            collection_name: 写入目标集合名称
            ids: 向量的唯一标识符 ID 列表（整数或 UUID 字符串）
            vectors: 稠密向量矩阵列表
            payloads: 可选的元数据字典列表
            batch_size: 每一个 batch 写入的向量数（默认 1000）
            max_workers: 最大并发写线程数（默认 4）

        Returns:
            int: 成功导入的向量点数总计
        """
        # Step 1: 输入校验防御
        if len(ids) != len(vectors):
            raise ValueError(f"向量 ID 列表长度 ({len(ids)}) 与向量数据列表长度 ({len(vectors)}) 不一致")
        
        # Step 2: 规范化 payloads，若为空则补齐空字典以保证打包正常
        if payloads is None:
            payloads = [{} for _ in range(len(ids))]
        elif len(payloads) != len(ids):
            raise ValueError(f"元数据 payloads 列表长度 ({len(payloads)}) 与向量数 ({len(ids)}) 不匹配")

        # Step 3: 拼装 PointStruct 列表
        points = [
            PointStruct(id=idx, vector=vec, payload=payload)
            for idx, vec, payload in zip(ids, vectors, payloads)
        ]

        # Step 4: 将大列表切片为多个 batches
        batches = [points[i:i + batch_size] for i in range(0, len(points), batch_size)]

        # Step 5: 根据运行模式执行不同并发写入策略
        # 在内存模式 (:memory:) 下，底层由 SQLite/进程内组件驱动，高并发写会导致锁竞争异常，因此必须采用顺序写入
        if self.is_memory_mode:
            print("🚀 检测到内存模式，正在以单线程方式顺序写入 batches...")
            for idx, batch in enumerate(batches):
                start = time.time()
                self.client.upsert(collection_name=collection_name, points=batch)
                duration = time.time() - start
                print(f"   - Batch {idx+1}/{len(batches)} 写入成功，包含 {len(batch)} 条向量，耗时: {duration:.4f}s")
        else:
            # 外部 Docker 模式下，可以利用 ThreadPoolExecutor 实现多线程分批并发请求，从而榨干 Qdrant 网卡和硬件吞吐
            print(f"⚡ 检测到本地 Docker 服务，正在启动 ThreadPoolExecutor (max_workers={max_workers}) 并发写入 batches...")
            
            def _upsert_single_batch(batch_idx: int, batch_points: list[PointStruct]) -> None:
                start = time.time()
                self.client.upsert(collection_name=collection_name, points=batch_points)
                duration = time.time() - start
                print(f"   - Batch {batch_idx+1} 并发写入完成，包含 {len(batch_points)} 条向量，耗时: {duration:.4f}s")

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = [
                    executor.submit(_upsert_single_batch, idx, batch)
                    for idx, batch in enumerate(batches)
                ]
                # 阻塞等待所有并发 batch 完成
                for fut in futures:
                    fut.result()

        return len(points)

    def wait_for_indexing(self, collection_name: str, timeout: float = 30.0) -> bool:
        """轮询监控集合的后台优化器状态，直到 HNSW 索引构建就绪（CollectionStatus.GREEN）。

        Args:
            collection_name: 待监控的集合名称
            timeout: 最大轮询等待秒数（默认 30.0）

        Returns:
            bool: 索引正常就绪返回 True，超时未就绪返回 False
        """
        # 内存模式下，数据写入是即时索引化的，没有复杂的段（Segments）后台异步优化和合并，直接返回 True
        if self.is_memory_mode:
            print("💡 内存模式下索引即时可用。")
            return True

        start_time = time.time()
        print(f"⏱ 开始监控集合 '{collection_name}' 索引构建状态 (最大超时: {timeout}s)...")
        
        while time.time() - start_time < timeout:
            try:
                collection_info = self.client.get_collection(collection_name)
                status = collection_info.status
                
                # Qdrant 集合状态：GREEN 表示所有挂起的优化任务（如 HNSW 树合并）已完成，索引完全就绪
                if status == CollectionStatus.GREEN:
                    duration = time.time() - start_time
                    print(f"✅ HNSW 索引构建全部完成！状态: {status.name}，耗时: {duration:.2f}s")
                    return True
                else:
                    print(f"   - 优化器合并中... 当前状态: {status.name}，已等待 {time.time() - start_time:.1f}s")
            except Exception as e:
                print(f"⚠ 轮询探测异常: {e}")
            
            time.sleep(0.5)
            
        print(f"❌ HNSW 索引构建等待超时，未在 {timeout}s 内达到 GREEN 状态。")
        return False

    def search(
        self,
        collection_name: str,
        query_vector: list[float],
        limit: int = 5,
        ef: int | None = None
    ) -> list:
        """在指定集合中执行近似最近邻（ANN）相似度搜索，支持动态修改 ef 参数。

        ⚠️ 注意：使用最新的 client.query_points() API 替代已废弃的 client.search()！

        Args:
            collection_name: 目标集合名称
            query_vector: 检索用 Query 向量
            limit: 期望召回的最相似结果数
            ef: 检索期的 HNSW 搜索窗口大小（调大可提升召回，但增大延迟）

        Returns:
            list: Qdrant 的 ScoredPoint 列表
        """
        # 构造查询配置
        search_params = None
        if ef is not None:
            # 动态调整检索阶段 HNSW 搜索窗口的大小，增大 ef 会提高精度但会带来额外 CPU 计算开销
            search_params = SearchParams(hnsw_ef=ef)

        # 执行相似度搜索
        results = self.client.query_points(
            collection_name=collection_name,
            query=query_vector,
            limit=limit,
            search_params=search_params
        )
        return results.points

    def delete_collection(self, collection_name: str) -> bool:
        """从 Qdrant 中物理删除指定名称的向量集合，释放空间。

        Args:
            collection_name: 待删除的集合名称

        Returns:
            bool: 成功删除返回 True，原来就不存在或删除失败返回 False
        """
        if self.client.collection_exists(collection_name):
            self.client.delete_collection(collection_name)
            print(f"🧹 成功删除集合 '{collection_name}' 并物理清理资源")
            return True
        print(f"💡 集合 '{collection_name}' 不存在，无需物理清理")
        return False


# ══════════════════════════════════════════════════════════════════════════════
# 板块二：Benchmark 压力测试与过关验证入口
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("======================================================================")
    print("🏆 Day 37 过关验证：10,000 条向量并发写入与 HNSW 索引构建压测")
    print("======================================================================")
    
    # 优先连接本地 Qdrant Docker 实例，如未运行，则平滑降级到 :memory:
    engine = QdrantHnswEngine()
    
    collection = "day37_hnsw_benchmark"
    vector_dim = 1536  # 使用真实工业标准的 OpenAI/MiniMax 大维度向量进行压测
    
    try:
        # Step 1: 创建集合，定制 HNSW 参数（m=16, ef_construct=100）
        engine.create_collection(
            collection_name=collection,
            vector_size=vector_dim,
            distance=Distance.COSINE,
            m=16,
            ef_construct=100
        )
        
        # Step 2: 产生 10,000 条高维模拟测试向量（不调用大模型 API 节省额度）
        print("\n⏳ 正在本地生成 10,000 条 1536 维度的随机测试向量矩阵...")
        np.random.seed(42)
        raw_vectors = np.random.randn(10000, vector_dim)
        
        # 对向量进行 L2 归一化以模拟经过规范化处理的高清 Embedding
        norms = np.linalg.norm(raw_vectors, axis=1, keepdims=True)
        normalized_vectors = (raw_vectors / norms).tolist()
        
        ids = list(range(10000))
        payloads = [{"doc_id": i, "content_preview": f"document_chunk_number_{i}"} for i in ids]
        print("✅ 模拟向量集生成完成！")
        
        # Step 3: 开始记录时间并批量并发写入
        print(f"\n🚀 开始导入 10,000 条向量 (batch_size=500)...")
        write_start = time.time()
        
        imported_count = engine.batch_upsert(
            collection_name=collection,
            ids=ids,
            vectors=normalized_vectors,
            payloads=payloads,
            batch_size=500,
            max_workers=4
        )
        
        write_duration = time.time() - write_start
        print(f"✅ 数据导入完毕！总计导入 {imported_count} 条，总耗时: {write_duration:.4f}s")
        print(f"📈 写入吞吐量: {imported_count / write_duration:.2f} 向量/秒")
        
        # Step 4: 等待 HNSW 后台优化器及索引归档构建就绪
        ready_start = time.time()
        is_ready = engine.wait_for_indexing(collection, timeout=60.0)
        ready_duration = time.time() - ready_start
        
        if is_ready:
            print(f"🎉 Qdrant 索引已就绪！")
            if not engine.is_memory_mode:
                print(f"⏱ 纯 HNSW 索引后台构建耗时: {ready_duration:.2f}s")
        else:
            print("⚠ 提示：HNSW 索引仍处于未完全就绪状态")
            
        # Step 5: 并行检索测试与延迟计算（模拟 10 次在线检索）
        print(f"\n🔎 模拟 Agent 检索，随机执行 10 次相似度查询 (ef=64, limit=5)...")
        query_latencies = []
        for i in range(10):
            query_vec = np.random.randn(vector_dim)
            query_vec /= np.linalg.norm(query_vec)
            
            q_start = time.time()
            res = engine.search(
                collection_name=collection,
                query_vector=query_vec.tolist(),
                limit=5,
                ef=64
            )
            q_lat = (time.time() - q_start) * 1000  # 毫秒精度
            query_latencies.append(q_lat)
            
        avg_latency = np.mean(query_latencies)
        print(f"🎯 检索时延测算完毕：")
        print(f"   - 平均查询响应时延: {avg_latency:.4f} ms")
        print(f"   - 最大查询响应时延: {max(query_latencies):.4f} ms")
        print(f"   - 最小查询响应时延: {min(query_latencies):.4f} ms")
        
        # Step 6: 获取数据库集合实际状态指标进行二次验证
        print("\n📊 集合最终运行期指标详情:")
        info = engine.client.get_collection(collection)
        print(f"   - 向量数量 (Points Count): {info.points_count}")
        print(f"   - 集合状态 (Collection Status): {info.status.name}")
        print(f"   - 优化器状态 (Optimizer Status): {info.optimizer_status}")
        
    except Exception as e:
        print("\n💥 运行过程中抛出意外异常:")
        import traceback
        traceback.print_exc()
        
    finally:
        # Step 7: 清理现场
        print("\n🧹 清理测试 Collection 资源...")
        engine.delete_collection(collection)
        print("🏁 Day 37 过关压测测试结束！")
        print("======================================================================")
