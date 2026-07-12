"""
AetherMind RAG & GraphRAG Coordinator Engine
============================================

设计方案:
---------
本模块实现的高级检索引擎 `RAGEngine` 作为主控，整合了：
1. **文档切片与双索引构建 (Indexing)**：
   - 接收上传的文献，使用字符滑动窗口（切片大小 500 字符，重叠边界 200 字符）进行物理分块。
   - 对每个分块并行计算 Dense 向量，并将 `text`/`source`/`chunk_id` 等元数据上传至 Qdrant `knowledge_collection`。
   - 异步将该分块交给 `GraphRAGEngine`，提取实体与关系边建立全局 NetworkX 图拓扑。
   - 在所有分块处理完毕后，触发 `GraphRAGEngine.build_communities()` 进行社区发现并生成主题汇总报告。
2. **多路协调检索 (Retrieval)**：
   - 调用 `VectorSearcher` 进行多路语义混合召回（Multi-Query + HyDE + Dense + BM25）与 ReRank。
   - 并行调用 `GraphRAGEngine` 执行 Local Search（邻域关联遍历）与 Global Search（社区报告 Map-Reduce 聚合）。
   - 将向量检索到的 Top-3 核心块与图检索到的关联链综述进行汇总合并，提供给 `ContextBuilder` 进行 Prompt 组装。
3. **图谱快照持久化 (Graph Snapshot Persistence)**：
   - NetworkX 图是纯内存结构，进程退出即丢失。为避免每次重启都重新用 LLM 提取实体关系，
     引擎在图构建完成后将图的全部节点、边与社区报告序列化为 `graph_snapshot.json` 物理存储。
   - 重启时优先读取快照并与 Qdrant 中的 Chunk ID 集合做差分对比：
     若完全一致，直接从快照恢复图结构（纯内存操作，毫秒级）；
     若 Qdrant 中有新增 Chunk，仅对增量 Chunk 调用 LLM 进行实体提取。

结构说明:
---------
- RAGEngine: 高级检索系统主控类。
  - _snapshot_path: 图谱快照文件物理路径。
  - _save_graph_snapshot(): 将 NetworkX 图 + 社区报告持久化为 JSON。
  - _load_graph_snapshot(): 从 JSON 快照恢复 NetworkX 图结构。
  - _batch_extract_graphs(): 分批并发 LLM 实体提取内部工具方法。
"""

import os
import json
import time
import asyncio
from typing import List, Dict, Any, Tuple, Set
from aether_mind.storage.base import VectorStore
from aether_mind.rag.vector_search import VectorSearcher
from aether_mind.rag.graph_search import GraphRAGEngine
from aether_mind.utils.client import AetherMindLLMClient
from aether_mind.utils.logging import logger, TraceContext


class RAGEngine:
    """
    RAG 与 GraphRAG 检索引擎主控类，协调文本切片、多路检索及图结构生成。

    核心改进：
    - 图谱快照持久化：避免重启时全量重建，显著降低 API 消耗与启动延迟。
    - 增量图构建：仅对 Qdrant 中新增的 Chunk 触发 LLM 实体提取。
    """

    # 图谱快照文件的固定存储路径（相对于服务启动的 CWD，即 aether_mind/ 项目根目录）
    _snapshot_path: str = "graph_snapshot.json"

    def __init__(self, client: AetherMindLLMClient):
        """
        初始化 RAG 主控引擎。

        Args:
            client (AetherMindLLMClient): 大模型客户端。
        """
        self.client = client
        self.vector_searcher = VectorSearcher(client)
        self.graph_engine = GraphRAGEngine(client)
        # 本地在内存中缓存的全部 Chunks 列表，用于 BM25 检索
        self.local_corpus: List[Dict[str, Any]] = []


    def _save_graph_snapshot(self, indexed_chunk_ids: Set[int]) -> None:
        """
        将当前内存中的 NetworkX 图结构与社区报告持久化到 graph_snapshot.json。

        数据结构:
        - indexed_chunk_ids: 已完成图谱提取的 Chunk ID 集合（用于增量差分比对）
        - nodes: 节点列表（含 name 与所有属性，set 类型的 source_chunks 转为 list）
        - edges: 边列表（含 source、target 与所有属性）
        - community_reports: 社区主题报告列表

        Args:
            indexed_chunk_ids (Set[int]): 当前图谱已处理的所有 Chunk ID 集合。
        """
        try:
            graph = self.graph_engine.graph
            # 序列化节点（将 set 类型的 source_chunks 转为 list，以支持 JSON 序列化）
            nodes_data = []
            for node, attrs in graph.nodes(data=True):
                node_entry = {"name": node}
                for k, v in attrs.items():
                    node_entry[k] = list(v) if isinstance(v, set) else v
                nodes_data.append(node_entry)

            # 序列化边
            edges_data = []
            for src, tgt, attrs in graph.edges(data=True):
                edges_data.append({"source": src, "target": tgt, **attrs})

            snapshot = {
                "indexed_chunk_ids": list(indexed_chunk_ids),
                "nodes": nodes_data,
                "edges": edges_data,
                "community_reports": self.graph_engine.community_reports
            }
            with open(self._snapshot_path, "w", encoding="utf-8") as f:
                json.dump(snapshot, f, ensure_ascii=False, indent=2)
            logger.info(
                f"[图谱快照] 已保存快照至 {self._snapshot_path}，"
                f"节点数: {len(nodes_data)}，边数: {len(edges_data)}，"
                f"已索引 Chunk 数: {len(indexed_chunk_ids)}"
            )
        except Exception as e:
            logger.warning(f"[图谱快照] 快照保存失败（非致命）: {str(e)}")

    def _load_graph_snapshot(self) -> Tuple[bool, Set[int]]:
        """
        从 graph_snapshot.json 恢复 NetworkX 图结构到内存。

        Returns:
            Tuple[bool, Set[int]]:
                - bool: 是否成功加载快照
                - Set[int]: 快照中已完成提取的 Chunk ID 集合（空集表示加载失败）
        """
        if not os.path.exists(self._snapshot_path):
            logger.info("[图谱快照] 未检测到历史快照文件，将执行全量图谱构建。")
            return False, set()

        try:
            with open(self._snapshot_path, "r", encoding="utf-8") as f:
                snapshot = json.load(f)

            self.graph_engine.graph.clear()

            # 恢复节点（将 source_chunks list 还原为 set）
            for node_data in snapshot.get("nodes", []):
                name = node_data.pop("name")
                for k, v in node_data.items():
                    if k == "source_chunks" and isinstance(v, list):
                        node_data[k] = set(v)
                self.graph_engine.graph.add_node(name, **node_data)

            # 恢复边
            for edge_data in snapshot.get("edges", []):
                src = edge_data.pop("source")
                tgt = edge_data.pop("target")
                self.graph_engine.graph.add_edge(src, tgt, **edge_data)

            # 恢复社区报告
            self.graph_engine.community_reports = snapshot.get("community_reports", [])

            indexed_ids = set(snapshot.get("indexed_chunk_ids", []))
            logger.info(
                f"[图谱快照] ✅ 快照恢复成功。"
                f"节点数: {self.graph_engine.graph.number_of_nodes()}，"
                f"边数: {self.graph_engine.graph.number_of_edges()}，"
                f"已索引 Chunk 数: {len(indexed_ids)}"
            )
            return True, indexed_ids
        except Exception as e:
            logger.warning(f"[图谱快照] 快照加载失败，将降级为全量重建: {str(e)}")
            return False, set()

    async def _batch_extract_graphs(self, chunks: List[Tuple[int, str]], batch_size: int = 5) -> Set[int]:
        """
        分批并发执行图谱实体关系提取（通用内部方法）。

        并发安全说明:
        - asyncio 是单线程协作式调度，图节点/边的写操作为纯同步代码，await 点之间不会被打断。
        - 因此并发写 NetworkX 图不存在竞态条件（Race Condition），并发设计完全安全。
        - 每批 batch_size 个并发，在 LLM API 吞吐量与并发限速之间取得工程平衡。

        Args:
            chunks (List[Tuple[int, str]]): 待处理的 (chunk_id, text) 列表。
            batch_size (int): 每批并发请求数量，默认 5。

        Returns:
            Set[int]: 真正成功提取关系并写入图谱的 chunk_id 集合。
        """
        successful_ids: Set[int] = set()
        total = len(chunks)
        for batch_start in range(0, total, batch_size):
            batch = chunks[batch_start: batch_start + batch_size]
            batch_end = min(batch_start + batch_size, total)
            logger.info(f"[图谱提取] 正在处理 Chunk [{batch_start+1}~{batch_end}] / {total}...")
            tasks = [
                self.graph_engine.extract_and_build_graph(chunk_id, text)
                for chunk_id, text in batch
            ]
            results = await asyncio.gather(*tasks)
            # 收集该批次中成功织入图谱的 chunk_id
            for (chunk_id, _), success in zip(batch, results):
                if success:
                    successful_ids.add(chunk_id)
        return successful_ids

    async def reload_corpus_from_store(self, vector_store: VectorStore) -> None:
        """
        防重启设计：从向量数据库中无损加载已有的全部知识片段，用于重建 BM25 索引和 Graph 图谱。

        性能优化（v3 — 快照持久化 + 增量提取）：
        - v1（原始）：逐个串行 await，168 个 Chunks ≈ ~14 分钟。
        - v2：批量并发 asyncio.gather，每批 15 个，≈ ~1~2 分钟。
        - v3（当前）：
            1. 优先从 graph_snapshot.json 加载已有图谱（毫秒级，不调用 LLM）。
            2. 对比 Qdrant 中的 Chunk ID 集合与快照中的已处理集合，找出增量 Chunk。
            3. 仅对增量 Chunk 触发 LLM 实体关系提取（批量并发）。
            4. 快照不存在时，降级为全量批量并发构建，完成后保存快照供下次使用。

        Args:
            vector_store (VectorStore): 向量数据库适配器。
        """
        try:
            # 1. 从 Qdrant 拉取所有已存 Chunks（纯向量检索，不调用 LLM）
            dummy_vector = [0.0] * 1536
            results = await vector_store.search_points(
                collection="knowledge_collection",
                query_vector=dummy_vector,
                top_k=1000
            )

            self.local_corpus = []
            all_chunks: List[Tuple[int, str]] = []

            for item in results:
                payload = item["payload"]
                text = payload["text"]
                source = payload["source"]
                chunk_id = payload["chunk_id"]
                self.local_corpus.append({"text": text, "source": source, "chunk_id": chunk_id})
                all_chunks.append((chunk_id, text))

            qdrant_chunk_ids: Set[int] = {cid for cid, _ in all_chunks}
            total = len(all_chunks)
            logger.info(f"[图谱重建] 从 Qdrant 拉取到 {total} 个 Chunks。")

            # 2. 尝试从快照加载已有图谱（核心优化：避免重复构建）
            snapshot_loaded, indexed_chunk_ids = self._load_graph_snapshot()

            # 3. 差分比对：找出 Qdrant 中有但快照中没有处理过的增量 Chunk
            new_chunk_ids = qdrant_chunk_ids - indexed_chunk_ids
            incremental_chunks = [(cid, txt) for cid, txt in all_chunks if cid in new_chunk_ids]

            if snapshot_loaded and not incremental_chunks:
                # ✅ 完全命中缓存：直接使用快照，跳过所有 LLM 调用
                logger.info(
                    f"[图谱重建] ✅ 快照完全命中，跳过全部 LLM 图构建调用。"
                    f"（节点数: {self.graph_engine.graph.number_of_nodes()}，"
                    f"社区数: {len(self.graph_engine.community_reports)}）"
                )
            elif snapshot_loaded and incremental_chunks:
                # ⚡ 部分命中缓存：仅对新增 Chunk 执行增量提取
                logger.info(
                    f"[图谱重建] ⚡ 快照命中，发现 {len(incremental_chunks)} 个新增 Chunk，执行增量图构建..."
                )
                successful_new_ids = await self._batch_extract_graphs(incremental_chunks)
                indexed_chunk_ids.update(successful_new_ids)
                # 触发社区重发现（新节点可能改变社区划分）
                await self.graph_engine.build_communities(vector_store)
                # 持久化更新后的快照（仅保存成功索引的 Chunk）
                self._save_graph_snapshot(indexed_chunk_ids)
            else:
                # 🔄 无快照缓存：全量构建（首次启动或快照损坏）
                logger.info(f"[图谱重建] 🔄 执行全量图谱构建（共 {total} 个 Chunks）...")
                self.graph_engine.graph.clear()
                successful_ids = await self._batch_extract_graphs(all_chunks)
                await self.graph_engine.build_communities(vector_store)
                # 持久化新建快照供后续重启复用（仅保存成功索引的 Chunk）
                self._save_graph_snapshot(successful_ids)

            logger.info(f"[RAG初始化完成] 成功从 Qdrant 加载重建了 {len(self.local_corpus)} 个文档切片，完成图谱重建")
        except Exception as e:
            logger.error(f"[RAG初始化异常] 从 Qdrant 重建 Corpus 失败: {str(e)}")

    async def index_document(self, file_name: str, content: str, vector_store: VectorStore) -> int:
        """
        解析并切片单篇文献，构建 Dense/Sparse/Graph 多路索引。

        Args:
            file_name (str): 文献文件名/来源标识。
            content (str): 文献完整纯文本内容。
            vector_store (VectorStore): 向量数据库适配器。

        Returns:
            int: 成功切片写入的 Chunks 数量。
        """
        start_time = time.time()

        # 1. 分块策略：滑动字符窗口切片（大小 500，重叠 200）
        chunk_size = 500
        overlap = 200
        chunks = []

        start = 0
        while start < len(content):
            end = start + chunk_size
            chunk_text = content[start:end].strip()
            if chunk_text:
                chunks.append(chunk_text)
            start += (chunk_size - overlap)

        if not chunks:
            return 0

        logger.info(f"[文档切片] 文件 '{file_name}' 成功切分为 {len(chunks)} 个片段。")

        # 2. 批量并发计算嵌入并写入 Qdrant 向量库
        embeddings = await self.client.get_embeddings(chunks, embed_type="db")

        points = []
        new_chunk_ids: Set[int] = set()
        for idx, (text, vec) in enumerate(zip(chunks, embeddings)):
            chunk_id = int(time.time() * 1000) + idx  # 生成微秒级唯一 ID
            payload = {
                "text": text,
                "source": file_name,
                "chunk_id": chunk_id,
                "hash": str(hash(text))
            }
            points.append({"id": chunk_id, "vector": vec, "payload": payload})
            new_chunk_ids.add(chunk_id)

            # 加入本地 BM25 Corpus
            self.local_corpus.append({"text": text, "source": file_name, "chunk_id": chunk_id})

        # 物理写入 Qdrant
        await vector_store.upsert_points("knowledge_collection", points)

        # 3. 图谱实体关系增量提取（批量并发，返回提取成功的 chunk 集合）
        new_chunks_list = [(p["id"], p["payload"]["text"]) for p in points]
        successful_new_ids = await self._batch_extract_graphs(new_chunks_list)

        # 4. 重建网络社区并生成社区总结报告
        await self.graph_engine.build_communities(vector_store)

        # 5. 更新图谱快照（仅将成功构建图谱的新 Chunk IDs 合入已有快照记录）
        _, existing_indexed_ids = self._load_graph_snapshot()
        existing_indexed_ids.update(successful_new_ids)
        self._save_graph_snapshot(existing_indexed_ids)

        duration = int((time.time() - start_time) * 1000)
        logger.info(f"[索引构建成功] 文件 '{file_name}' 索引构建完成，耗时 {duration}ms")
        return len(chunks)

    async def retrieve(
        self,
        query: str,
        vector_store: VectorStore,
        top_k: int = 5,
        on_trace=None
    ) -> Tuple[List[Dict[str, Any]], str]:
        """
        执行联合多路检索。并发完成 RAG 混合密集/稀疏匹配与 GraphRAG 局部/全局图检索。

        Args:
            query (str): 用户问题。
            vector_store (VectorStore): 向量数据库。
            top_k (int): 最多召回候选数。
            on_trace (Optional[Callable]): 异步回调，用于向 SSE 层上报子步骤进度事件。
                签名: async on_trace(step: str, content: str, duration_ms: int)

        Returns:
            Tuple[List[Dict[str, Any]], str]:
                - List[Dict[str, Any]]: 经过 ReRank 重排后的 Top-3 核心文档 Chunks。
                - str: GraphRAG 检索生成的全局与局部关系综述文本。
        """
        start_time = time.time()

        async def _trace(content: str, duration_ms: int = 0):
            if on_trace:
                await on_trace("retrieval", content, duration_ms)

        # ── 步骤 1：Multi-Query + HyDE 扩展 Query 生成 ──
        await _trace("⏳ [1/5] Multi-Query & HyDE 扩展 Query 生成中...")
        mq_start = time.time()
        mq_tasks = self.vector_searcher.generate_multi_queries(query)
        hyde_task = self.vector_searcher.generate_hyde_doc(query)
        mq_list, hyde_doc = await asyncio.gather(mq_tasks, hyde_task)
        mq_dur = int((time.time() - mq_start) * 1000)
        await _trace(
            f"✅ [1/5] Multi-Query 生成 {len(mq_list)} 个扩展 Query，HyDE 假设文档已生成。",
            mq_dur
        )

        # ── 步骤 2：多路向量检索 + BM25 稀疏检索 ──
        await _trace("⏳ [2/5] 多路向量检索（Dense×5 + BM25 稀疏）并发执行中...")
        vec_start = time.time()
        all_queries = [query] + mq_list + [hyde_doc]

        async def _single_search(q_text: str):
            try:
                vec = await self.vector_searcher.client.get_embedding(q_text, embed_type="query")
                return await vector_store.search_points("knowledge_collection", vec, top_k=top_k * 2)
            except Exception as ex:
                logger.error(f"[单路向量检索异常] query: {q_text[:50]}, err: {str(ex)}")
                return []

        search_results = await asyncio.gather(*[_single_search(q) for q in all_queries])

        bm25_results = []
        from aether_mind.rag.vector_search import SimpleBM25
        if self.local_corpus:
            bm25 = SimpleBM25(self.local_corpus)
            bm25_hits = bm25.search(query, top_k=top_k * 2)
            bm25_results = [{
                "id": None,
                "score": score,
                "payload": {"text": hit["text"], "source": hit["source"], "chunk_id": hit["chunk_id"]}
            } for hit, score in bm25_hits]

        dedup_dict = {}
        for res_list in search_results:
            for item in res_list:
                text = item["payload"]["text"]
                if text not in dedup_dict:
                    dedup_dict[text] = item
        for item in bm25_results:
            text = item["payload"]["text"]
            if text not in dedup_dict:
                dedup_dict[text] = item
        candidates = list(dedup_dict.values())[:20]
        vec_dur = int((time.time() - vec_start) * 1000)
        logger.info(f"[混合召回完成] 总计去重后候选块数量: {len(candidates)}")
        await _trace(
            f"✅ [2/5] 向量+稀疏混合召回完成，去重后候选块数量: {len(candidates)} 个。",
            vec_dur
        )

        # ── 步骤 3：GraphRAG Local Search ──
        await _trace("⏳ [3/5] GraphRAG 局部图拓扑检索中...")
        local_start = time.time()
        local_graph_res = await self.graph_engine.local_search(query)
        local_dur = int((time.time() - local_start) * 1000)
        await _trace(
            f"✅ [3/5] Local Search 完成，返回 {len(local_graph_res)} 字符的邻域关联线索。",
            local_dur
        )

        # ── 步骤 4：GraphRAG Global Search (Map-Reduce) ──
        comm_count = len(self.graph_engine.community_reports)
        await _trace(f"⏳ [4/5] GraphRAG 全局 Map-Reduce 检索中（{comm_count} 个社区报告）...")
        global_start = time.time()
        global_graph_res = await self.graph_engine.global_search(query, vector_store)
        global_dur = int((time.time() - global_start) * 1000)
        await _trace(
            f"✅ [4/5] Global Search 完成，融合综述长度: {len(global_graph_res)} 字符。",
            global_dur
        )

        # ── 步骤 5：LLM ReRank 二次精排 ──
        await _trace(f"⏳ [5/5] LLM ReRank 对 {len(candidates)} 个候选块进行相关度精排中...")
        rerank_start = time.time()
        final_vector_chunks = await self.vector_searcher.rerank(query, candidates)
        rerank_dur = int((time.time() - rerank_start) * 1000)
        await _trace(
            f"✅ [5/5] ReRank 完成，精选出 Top-{len(final_vector_chunks)} 核心上下文块。",
            rerank_dur
        )

        # 4. 合并 GraphRAG 文本上下文线索
        graph_parts = []
        if local_graph_res:
            graph_parts.append(local_graph_res)
        if global_graph_res:
            graph_parts.append(global_graph_res)
        graph_context = "\n\n".join(graph_parts)

        duration = int((time.time() - start_time) * 1000)
        TraceContext.add_step(
            "retrieval",
            f"联合检索召回完成。向量库相关 Chunks 数: {len(final_vector_chunks)}，图谱检索线索字数: {len(graph_context)}",
            duration
        )

        return final_vector_chunks, graph_context
