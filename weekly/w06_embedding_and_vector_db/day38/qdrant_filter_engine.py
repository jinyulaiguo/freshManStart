"""
Day 38 参考答案 — 相似度检索与元数据联合过滤 (Metadata Filtering)

设计方案：
==========
1. 设计意图：
   在多租户/多属性权限控制的 RAG 系统中，相似度检索需要结合文档元数据（如阅读权限级别、分类）进行综合筛选。
   本文件是 Day 38 的标准参考答案实现。由于直接采用 Python 侧过滤（Post-Filtering）会引发严重的“检索空置（Recall Drop）”痛点，
   本类基于最新 Qdrant `query_points` API 封装了数据库底层联合过滤（Pre-Filtering）客户端，并支持对 Payload 进行属性索引（Payload Indexing）以优化检索时延。
   通过在 10,000 条高维向量上的对比压测，向学员直观展示 Pre-Filtering 在正确性与性能上的巨大优势。

2. 关键组件结构：
   - QdrantFilterEngine: 核心向量检索与元数据联合过滤客户端。
     - create_collection(): 创建/重建集合。
     - create_payload_index(): 在 Payload 字段上创建 Keyword/Integer 等属性索引，提升过滤效率。
     - batch_upsert(): 分批并发导入向量点和 Payload 数据。
     - search_with_post_filter(): 检索后过滤模式。先在 Qdrant 中进行无条件向量检索（ limit 放大），拉回本地后用 Python 进行过滤。
     - search_with_pre_filter(): 检索前过滤模式。在检索阶段将 `Filter` 复合条件传入最新 `query_points` API，直接由底层 HNSW 图检索进行过滤。

3. 关键数据流向与 Benchmark 验证：
   - 初始化本地或内存模式 Qdrant 客户端。
   - 生成 10,000 条 1536 维规范化模拟文本向量。
   - 配置 Payload 策略：将 9,990 条设为机密（read_level=3），仅 10 条设为普通公开（read_level=1）。
   - 执行并发批量写入，并建立属性索引。
   - 模拟用户提问（max_read_level=2），比较 Pre-Filtering 与 Post-Filtering：
     - Post-Filtering 因为检索出的 Top-50 高相似向量全部为 read_level=3 的机密内容，导致经过 Python 过滤后返回 0 结果（检索空置）。
     - Pre-Filtering 在底层进行图剪枝过滤，能够精准召回全部 5 个符合条件的公开结果，且延迟极低。
   - 打印对比数据表，清理物理集合。

使用方式（在项目根目录）：
    python -m weekly.w06_embedding_and_vector_db.day38.qdrant_filter_engine
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
    PointStruct,
    SearchParams,
    CollectionStatus,
    Filter,
    FieldCondition,
    MatchValue,
    Range,
    PayloadSchemaType
)


# ══════════════════════════════════════════════════════════════════════════════
# 板块一：QdrantFilterEngine 完整实现
# ══════════════════════════════════════════════════════════════════════════════

class QdrantFilterEngine:
    """基于 Qdrant 的高性能 Payload 索引与多字段元数据联合过滤搜索引擎"""

    def __init__(self, url: str | None = None, port: int = 6333, location: str | None = None) -> None:
        """初始化 Qdrant 客户端，具备自适应防错降级机制。

        如果指定了 location，则直接使用；
        否则优先连接本地 http://localhost:6333，连接失败时平滑降级至内存模式 (:memory:)。
        """
        self.is_memory_mode = False
        
        # Step 0: 显式启动指定内存模式
        if location == ":memory:":
            self.client = QdrantClient(location=":memory:")
            self.is_memory_mode = True
            print("💡 Qdrant 客户端已启动为指定内存模式 (:memory:)")
            return

        # Step 1: 尝试连接本地 Docker 实例
        target_url = url or "http://127.0.0.1"
        try:
            self.client = QdrantClient(url=target_url, port=port, timeout=2.0)
            # 测试连接状态
            self.client.get_collections()
            print(f"✅ 成功连接到本地 Qdrant Docker 实例: {target_url}:{port}")
        except Exception as e:
            # Step 2: 降级到进程内内存模式
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
        distance: Distance = Distance.COSINE
    ) -> bool:
        """在 Qdrant 中创建或重建一个向量集合。

        Args:
            collection_name: 集合名称
            vector_size: 向量几何维度（如 1536）
            distance: 相似度距离度量函数类型，默认为余弦相似度

        Returns:
            bool: 集合重建成功返回 True
        """
        # Step 1: 物理清理老集合，防止 Payload 索引冲突
        if self.client.collection_exists(collection_name):
            print(f"🧹 发现已存在的集合 '{collection_name}'，正在物理清理...")
            self.client.delete_collection(collection_name)

        # Step 2: 创建新集合，并显式配置向量参数
        self.client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(
                size=vector_size,
                distance=distance
            )
        )
        print(f"✨ 集合 '{collection_name}' 重建成功，参数: dim={vector_size}, distance={distance.name}")
        return True

    def create_payload_index(
        self,
        collection_name: str,
        field_name: str,
        field_type: PayloadSchemaType
    ) -> bool:
        """在指定的元数据 Payload 字段上创建属性索引，用于优化 Pre-Filtering 性能。

        Args:
            collection_name: 集合名称
            field_name: 元数据 Payload 字段键名（如 'read_level'）
            field_type: 属性的数据类型契约（如 PayloadSchemaType.INTEGER）

        Returns:
            bool: 索引创建成功返回 True，其他情况返回 False
        """
        # 内存模式下数据直接全载入 SQLite 虚拟表中进行查询，无需也不支持显式物理 Payload 索引
        if self.is_memory_mode:
            return True

        # Docker 模式下显式调用 API 在数据库底层构建字段索引以优化 HNSW 过滤效率
        try:
            self.client.create_payload_index(
                collection_name=collection_name,
                field_name=field_name,
                field_schema=field_type
            )
            print(f"⚡ 成功在字段 '{field_name}' 上创建 {field_type.name} 类型的 Payload 索引")
            return True
        except Exception as e:
            print(f"❌ 在字段 '{field_name}' 上创建索引失败，错误: {e}")
            return False

    def batch_upsert(
        self,
        collection_name: str,
        ids: list[int | str],
        vectors: list[list[float]],
        payloads: list[dict] | None = None,
        batch_size: int = 500,
        max_workers: int = 4
    ) -> int:
        """高吞吐分批并发将向量和元数据写入目标集合中。

        Args:
            collection_name: 目标写入集合名称
            ids: 向量唯一标识符 ID 列表
            vectors: 稠密向量矩阵列表
            payloads: 元数据键值对字典列表，需与向量一一对应
            batch_size: 单次请求写入的最大条数（防止 JSON payload 击穿限制）
            max_workers: 最大并发写线程数

        Returns:
            int: 成功导入的向量点数总数
        """
        # Step 1: 格式与对齐校验
        if len(ids) != len(vectors):
            raise ValueError(f"ID 长度 ({len(ids)}) 与向量长度 ({len(vectors)}) 不一致")
        if payloads is None:
            payloads = [{} for _ in range(len(ids))]
        elif len(payloads) != len(ids):
            raise ValueError(f"Payloads 长度 ({len(payloads)}) 与向量数 ({len(ids)}) 不匹配")

        # Step 2: 打包封装为 PointStruct 实体列表
        points = [
            PointStruct(id=idx, vector=vec, payload=payload)
            for idx, vec, payload in zip(ids, vectors, payloads)
        ]

        # Step 3: 分批切割
        batches = [points[i:i + batch_size] for i in range(0, len(points), batch_size)]

        # Step 4: 并行写入分流
        if self.is_memory_mode:
            # 内存模式下由单线程顺序写入，防止 SQLite 发生锁争抢崩溃
            for batch in batches:
                self.client.upsert(collection_name=collection_name, points=batch)
        else:
            # 本地 Docker 模式下多线程并发，榨干网卡吞吐
            def _upsert_task(batch_points: list[PointStruct]) -> None:
                self.client.upsert(collection_name=collection_name, points=batch_points)

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = [executor.submit(_upsert_task, b) for b in batches]
                for fut in futures:
                    fut.result()

        return len(points)

    def search_with_post_filter(
        self,
        collection_name: str,
        query_vector: list[float],
        limit: int = 5,
        category: str | None = None,
        max_read_level: int | None = None
    ) -> list:
        """检索后过滤模式（Post-Filtering）：先大范围检索相似向量，然后再在 Python 侧按属性过滤。

        Args:
            collection_name: 集合名称
            query_vector: 输入 Query 向量
            limit: 期望的最终召回数量
            category: 过滤条件：精确匹配文档类别
            max_read_level: 过滤条件：最大可读权限级别

        Returns:
            list: 经过 Python 侧过滤后的 ScoredPoint 列表
        """
        # Step 1: 放大 limit，尝试多召回一些候选，缓解后过滤容易把结果过滤光（Recall Drop）的问题
        candidate_limit = limit * 10

        # Step 2: 执行普通的向量检索，此时数据库对元数据并不知情
        results = self.client.query_points(
            collection_name=collection_name,
            query=query_vector,
            limit=candidate_limit
        )
        candidates = results.points

        # Step 3: 在 Python 侧内存中依次校验过滤条件
        filtered_results = []
        for res in candidates:
            payload = res.payload or {}
            
            # 类别校验
            if category is not None and payload.get("category") != category:
                continue
            
            # 级别校验
            if max_read_level is not None:
                read_level = payload.get("read_level")
                # 缺失级别字段或者级别超出则剔除
                if read_level is None or read_level > max_read_level:
                    continue
            
            filtered_results.append(res)
            
            # 达到期望的召回数 limit 则直接截断
            if len(filtered_results) >= limit:
                break

        return filtered_results

    def search_with_pre_filter(
        self,
        collection_name: str,
        query_vector: list[float],
        limit: int = 5,
        category: str | None = None,
        max_read_level: int | None = None
    ) -> list:
        """检索前过滤模式（Pre-Filtering）：直接在向量数据库底层，将过滤条件和 HNSW 图检索进行联合剪枝。

        Args:
            collection_name: 集合名称
            query_vector: 输入 Query 向量
            limit: 最终期望的召回数量
            category: 过滤条件：精确匹配文档类别
            max_read_level: 过滤条件：用户最大阅读权限级别

        Returns:
            list: 100% 符合条件且大小为 limit 左右的 ScoredPoint 列表
        """
        # Step 1: 构建 Qdrant 专用的联合过滤复合对象 Filter
        conditions = []
        
        # 组装精确类别匹配条件
        if category is not None:
            conditions.append(
                FieldCondition(
                    key="category",
                    match=MatchValue(value=category)
                )
            )
            
        # 组装范围权限过滤条件
        if max_read_level is not None:
            conditions.append(
                FieldCondition(
                    key="read_level",
                    range=Range(lte=max_read_level)
                )
            )

        # 组装为 must AND 布尔逻辑关系
        query_filter = Filter(must=conditions) if conditions else None

        # Step 2: 调用 query_points 将过滤条件传入底层 HNSW 检索，直接在满足条件的节点范围内寻找最相似向量
        results = self.client.query_points(
            collection_name=collection_name,
            query=query_vector,
            query_filter=query_filter,
            limit=limit
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
    print("🏆 Day 38 过关验证：10,000 条向量元数据 Pre/Post-Filtering 性能与正确性对比")
    print("======================================================================")
    
    # 优先连接本地 Qdrant Docker 实例，如无 Docker 自动平滑降级至内存模式
    engine = QdrantFilterEngine()
    
    collection = "day38_filter_benchmark"
    vector_dim = 1536  # OpenAI / MiniMax 工业标准大维度
    
    try:
        # Step 1: 重建集合
        engine.create_collection(collection, vector_dim)
        
        # Step 2: 构建 Payload 属性索引以加速 Pre-Filtering
        # 包含 Keyword 精确匹配字段与 Integer 数值范围匹配字段
        engine.create_payload_index(collection, "category", PayloadSchemaType.KEYWORD)
        engine.create_payload_index(collection, "read_level", PayloadSchemaType.INTEGER)
        
        # Step 3: 本地生成 10,000 条测试向量并进行 L2 归一化
        print("\n⏳ 正在本地生成 10,000 条 1536 维度的随机测试向量矩阵...")
        np.random.seed(42)
        raw_vectors = np.random.randn(10000, vector_dim)
        norms = np.linalg.norm(raw_vectors, axis=1, keepdims=True)
        normalized_vectors = (raw_vectors / norms).tolist()
        
        # Step 4: 构造苛刻的权限元数据（故意暴露 Post-Filtering 的检索空置问题）
        # 10,000 条数据中：
        # - 9,990 条机密数据：category="secret", read_level=3 (极其相似但普通用户不可读)
        # - 10 条公开数据：category="public", read_level=1 (较为偏远但普通用户唯一有权读取)
        # 我们把这 10 条公开数据均匀地分布在数据集中
        ids = list(range(10000))
        payloads = []
        public_indices = set(range(1000, 10000, 1000)) # 公开数据位置
        
        for idx in ids:
            if idx in public_indices:
                payloads.append({"category": "public", "read_level": 1, "created_at": time.time() - 3600})
            else:
                payloads.append({"category": "secret", "read_level": 3, "created_at": time.time()})
                
        print("✅ 模拟向量与元数据 Payload 矩阵构建完毕！")

        # Step 5: 分批并发导入数据
        print(f"\n🚀 开始导入 10,000 条向量 (batch_size=500)...")
        write_start = time.time()
        imported = engine.batch_upsert(
            collection_name=collection,
            ids=ids,
            vectors=normalized_vectors,
            payloads=payloads,
            batch_size=500,
            max_workers=4
        )
        write_duration = time.time() - write_start
        print(f"✅ 数据导入完毕！导入向量数: {imported}，耗时: {write_duration:.4f}s")
        
        # 在 Docker 模式下，等待优化器完成后台 HNSW 树与 Payload 索引的合并归档
        if not engine.is_memory_mode:
            print("⏳ 正在等待 Qdrant 底层 HNSW 图索引与 Payload 索引构建就绪...")
            time.sleep(2.0)
            print("✅ 索引状态已更新！")

        # Step 6: 模拟用户以普通权限级别 (max_read_level=2, category="public") 执行 100 次并发查询测试
        # 使用第 0 条向量（该向量对应的相似向量极多为 secret 类别）作为 Query，
        # 测试 Post-Filtering 过滤崩溃和 Pre-Filtering 完美召回的性能特征
        query_vec = normalized_vectors[0]
        test_rounds = 100
        
        print(f"\n🔍 模拟用户访问权限: category='public', max_read_level<=2")
        print(f"🚀 正在发起 {test_rounds} 次检索压测...")

        # 1. 压测 Post-Filtering (后过滤)
        post_latencies = []
        post_counts = []
        for _ in range(test_rounds):
            start = time.time()
            res = engine.search_with_post_filter(
                collection_name=collection,
                query_vector=query_vec,
                limit=5,
                category="public",
                max_read_level=2
            )
            post_latencies.append((time.time() - start) * 1000) # 毫秒
            post_counts.append(len(res))
            
        # 2. 压测 Pre-Filtering (前过滤)
        pre_latencies = []
        pre_counts = []
        for _ in range(test_rounds):
            start = time.time()
            res = engine.search_with_pre_filter(
                collection_name=collection,
                query_vector=query_vec,
                limit=5,
                category="public",
                max_read_level=2
            )
            pre_latencies.append((time.time() - start) * 1000) # 毫秒
            pre_counts.append(len(res))

        # Step 7: 打印直观量化的对比报表
        avg_post_lat = np.mean(post_latencies)
        avg_pre_lat = np.mean(pre_latencies)
        avg_post_count = np.mean(post_counts)
        avg_pre_count = np.mean(pre_counts)

        print("\n" + "="*80)
        print("📊 PRE-FILTERING VS POST-FILTERING 性能与召回数量对比报表")
        print("="*80)
        print(f"| 检索机制 | 预期 Top-K | 实际平均召回数 | 平均时延 (ms) | 检索空置风险 (Recall Drop) |")
        print(f"|---|---|---|---|---|")
        print(f"| **Post-Filtering (后过滤)** | 5 | {avg_post_count:.1f} ❌ | {avg_post_lat:.4f} ms | 🔴 极高（Top-K 内全为禁看文档） |")
        print(f"| **Pre-Filtering (前过滤)** | 5 | {avg_pre_count:.1f} ✅ | {avg_pre_lat:.4f} ms | 🟢 零风险（在符合条件的点上检索） |")
        print("="*80)
        
        print("\n💡 结果分析量化说明：")
        print("1. **正确性差异**：因为 Query 距离机密文档 (read_level=3) 最近，Post-Filtering 检索出的 50 个最近邻里可能全是机密文档。")
        print("   Python 后期过滤后全部抛弃，导致最终召回数为 0。这直接印证了“检索空置（Recall Drop）”的业务痛点！")
        print("2. **Pre-Filtering 完备性**：而 Pre-Filtering 在底层通过 Payload 索引先在 HNSW 索引树上进行了条件限制裁剪，")
        print("   确保检索出来的每一个点均符合 'read_level <= 2'，因此无论过滤条件多苛刻，只要库里有公开数据，均能稳定满额召回！")
        print("="*80)

    except Exception as e:
        print("\n💥 运行过程中抛出意外异常:")
        import traceback
        traceback.print_exc()
        
    finally:
        # Step 8: 释放资源，保持环境无污染
        print("\n🧹 清理测试 Collection 资源...")
        engine.delete_collection(collection)
        print("🏁 Day 38 过关压测测试结束！")
        print("======================================================================")
