"""
AetherMind Dense/Sparse RAG with ReRank
=======================================

设计方案:
---------
本模块负责基础高级检索管道，整合多路召回与重排序：
1. **多路召回 (Dense/Sparse Hybrid)**：
   - Multi-Query：利用大模型生成 3 个不同的意图扩展 Query，并发请求向量库。
   - HyDE (假设性文档嵌入)：利用大模型生成针对 Query 的模拟答案，以此答案向量检索真实 Chunks。
   - BM25 稀疏检索：自主实现轻量级 `SimpleBM25`，使用 `jieba` 分词对上传文档的纯文本切片进行字词级关键字频计算。
2. **重排序 (ReRank)**：
   - 合并各路召回的 Top-10 候选 Chunks，去重。
   - 利用大模型进行评分（0.0 - 1.0 相关度），过滤得分 < 0.3 的 Chunks。
   - 排序并实施 "Lost in the Middle" 解决策略（最相关 Chunks 首尾夹逼分布）。
3. **引文标记 (Citations)**：
   - 保留每个 Chunk 的 `source` 与 `chunk_id`，以便在输出中标记数据来源。

结构说明:
---------
- SimpleBM25: 纯 Python 实现的高性能 BM25 稀疏检索器。
- ReRankScore: 重排分数 Pydantic 模型。
- VectorSearcher: 混合检索引擎，包含 Multi-Query/HyDE 发生、Qdrant 检索与重排。
"""

import re
import math
import asyncio
from typing import List, Dict, Any, Tuple
import jieba
from pydantic import BaseModel, Field
from aether_mind.storage.base import VectorStore
from aether_mind.utils.client import AetherMindLLMClient
from aether_mind.utils.logging import logger


class SimpleBM25:
    """
    纯 Python 实现的轻量级 BM25 检索器，支持 Jieba 中文分词。
    """

    def __init__(self, corpus: List[Dict[str, Any]], k1: float = 1.5, b: float = 0.75):
        """
        初始化并构建 BM25 索引。

        Args:
            corpus (List[Dict[str, Any]]): 切片文档列表，每个元素格式为 {"text": str, "source": str, "chunk_id": int}。
            k1 (float): 词频饱和度控制参数。
            b (float): 文档长度归一化参数。
        """
        self.k1 = k1
        self.b = b
        self.corpus = corpus
        self.doc_count = len(corpus)
        
        self.doc_lens = []
        self.doc_term_freqs = []  # List[Dict[str, int]]
        self.df = {}  # Document Frequency
        self.avg_doc_len = 0.0
        self.idf = {}
        
        self._build_index()

    def _build_index(self) -> None:
        """
        分词并计算词频和 IDF。
        """
        if not self.corpus:
            return

        total_len = 0
        for doc in self.corpus:
            text = doc["text"]
            # 使用 jieba 精确分词过滤空格
            words = [w for w in jieba.cut(text) if w.strip()]
            self.doc_lens.append(len(words))
            total_len += len(words)
            
            # 计算当前文档词频
            tf = {}
            for w in words:
                tf[w] = tf.get(w, 0) + 1
            self.doc_term_freqs.append(tf)
            
            # 计算 df
            for w in tf.keys():
                self.df[w] = self.df.get(w, 0) + 1

        self.avg_doc_len = total_len / self.doc_count if self.doc_count > 0 else 0.0

        # 计算 IDF
        for word, freq in self.df.items():
            # 标准 BM25 IDF 公式，加 0.5 避免负值
            self.idf[word] = math.log((self.doc_count - freq + 0.5) / (freq + 0.5) + 1.0)

    def search(self, query: str, top_k: int = 5) -> List[Tuple[Dict[str, Any], float]]:
        """
        执行 BM25 相关度计算。

        Args:
            query (str): 查询文本。
            top_k (int): 检索条目数。

        Returns:
            List[Tuple[Dict[str, Any], float]]: (文档, 分数) 元组列表，按分数降序排序。
        """
        if not self.corpus:
            return []

        query_words = [w for w in jieba.cut(query) if w.strip()]
        scores = []

        for idx in range(self.doc_count):
            score = 0.0
            tf = self.doc_term_freqs[idx]
            doc_len = self.doc_lens[idx]
            
            # 遍历查询词计算 BM25 分数
            for word in query_words:
                if word not in tf:
                    continue
                
                word_idf = self.idf.get(word, 0.0)
                word_tf = tf[word]
                # 计算词频得分分母
                denom = word_tf + self.k1 * (1.0 - self.b + self.b * (doc_len / self.avg_doc_len))
                score += word_idf * (word_tf * (self.k1 + 1.0)) / denom
                
            scores.append((self.corpus[idx], score))

        # 按得分降序排序
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]


class ReRankScore(BaseModel):
    """
    ReRank 评估分数数据模型。
    """
    score: float = Field(..., description="相关度得分，范围 0.0 - 1.0，最相关为 1.0")
    reason: str = Field(..., description="打分的理由与主要论点")


class VectorSearcher:
    """
    混合向量与文本检索引擎，包含 Multi-Query/HyDE 发生、Qdrant 密集检索与 LLM 重排。
    """

    def __init__(self, client: AetherMindLLMClient):
        """
        初始化检索引擎。

        Args:
            client (AetherMindLLMClient): 大模型客户端。
        """
        self.client = client

    async def generate_multi_queries(self, query: str) -> List[str]:
        """
        Multi-Query：生成 3 个变体查询。

        Args:
            query (str): 原始查询。

        Returns:
            List[str]: 派生查询列表。
        """
        prompt = [
            {
                "role": "system",
                "content": (
                    "你是一个资深检索 Query 优化专家。\n"
                    "你需要针对用户的原始查询，从不同视角生成 3 个含义相同或相关的扩展检索 Query。\n"
                    "要求：\n"
                    "1. 每一个 Query 独占一行。\n"
                    "2. 不要带任何编号、引导词、解释或多余符号。\n"
                    "3. 尽力捕捉核心实体的同义词、架构层关系。"
                )
            },
            {"role": "user", "content": f"原始查询：'{query}'\n请输出 3 个扩展检索 Query："}
        ]
        
        try:
            raw_text = await self.client.request_llm(prompt, temperature=0.5, max_tokens=200)
            queries = [line.strip() for line in raw_text.split("\n") if line.strip()]
            # 过滤干扰字符（如破折号、序号）
            clean_queries = []
            for q in queries[:3]:
                # 剔除首部数字和破折号
                q_clean = re.sub(r"^[0-9一二三四\.\-\s]+", "", q)
                if q_clean:
                    clean_queries.append(q_clean)
            
            # 若生成失败则兜底使用原始 query
            if not clean_queries:
                clean_queries = [query]
            return clean_queries
        except Exception as e:
            logger.error(f"[Multi-Query 异常] {str(e)}")
            return [query]

    async def generate_hyde_doc(self, query: str) -> str:
        """
        HyDE：生成假设性回答。

        Args:
            query (str): 原始查询。

        Returns:
            str: 假设性回答。
        """
        prompt = [
            {
                "role": "system",
                "content": (
                    "你是一个顶尖的研究员助理。\n"
                    "请针对用户的学术/技术问题，生成一段符合学术逻辑的、详细的假设性段落，用于语义向量检索。\n"
                    "注意：这段内容完全是模拟答案，即使你不知道真实数据，也请根据常理撰写。仅输出假设性段落文本，不要包含任何自然语言回复前缀。"
                )
            },
            {"role": "user", "content": f"问题：'{query}'\n假设性回答段落："}
        ]
        try:
            return await self.client.request_llm(prompt, temperature=0.7, max_tokens=500)
        except Exception as e:
            logger.error(f"[HyDE 发生异常] {str(e)}")
            return query

    async def hybrid_retrieve(
        self,
        query: str,
        vector_store: VectorStore,
        local_corpus: List[Dict[str, Any]],
        top_k: int = 10
    ) -> List[Dict[str, Any]]:
        """
        混合多路检索，检索候选 Top-10 文档块并去重。

        Args:
            query (str): 用户 Query。
            vector_store (VectorStore): 向量数据库连接。
            local_corpus (List[Dict[str, Any]]): 本地分块原文库。
            top_k (int): 最终候选数量。

        Returns:
            List[Dict[str, Any]]: 合并去重后的文档 Chunks。
        """
        # 并发执行三路语义召回
        # 1.1 原始 Query 向量检索
        # 1.2 Multi-Query 派生查询检索
        # 1.3 HyDE 假设检索
        
        # 派生查询
        mq_tasks = self.generate_multi_queries(query)
        hyde_task = self.generate_hyde_doc(query)
        
        mq_list, hyde_doc = await asyncio.gather(mq_tasks, hyde_task)
        
        # 合并所有检索 Query 列表
        all_queries = [query] + mq_list + [hyde_doc]
        
        # 批量向量计算与检索任务
        async def _single_search(q_text: str) -> List[Dict[str, Any]]:
            try:
                vec = await self.client.get_embedding(q_text, embed_type="query")
                return await vector_store.search_points("knowledge_collection", vec, top_k=top_k)
            except Exception as ex:
                logger.error(f"[单路向量检索异常] query: {q_text[:50]}, err: {str(ex)}")
                return []
                
        search_tasks = [_single_search(q) for q in all_queries]
        search_results = await asyncio.gather(*search_tasks)
        
        # 2. 稀疏检索 (BM25) 召回
        bm25_results = []
        if local_corpus:
            bm25 = SimpleBM25(local_corpus)
            bm25_hits = bm25.search(query, top_k=top_k)
            # 转换为统一的召回字典格式
            bm25_results = [{
                "id": None,
                "score": score,
                "payload": {
                    "text": hit["text"],
                    "source": hit["source"],
                    "chunk_id": hit["chunk_id"]
                }
            } for hit, score in bm25_hits]

        # 3. 结果合并与去重
        dedup_dict = {}
        
        # 合并向量召回
        for res_list in search_results:
            for item in res_list:
                text = item["payload"]["text"]
                # 基于文本的哈希去重
                if text not in dedup_dict:
                    dedup_dict[text] = item
                    
        # 合并 BM25 召回
        for item in bm25_results:
            text = item["payload"]["text"]
            if text not in dedup_dict:
                dedup_dict[text] = item

        candidates = list(dedup_dict.values())
        logger.info(f"[混合召回完成] 总计去重后候选块数量: {len(candidates)}")
        return candidates[:20]  # 至多保留前 20 个候选进入 ReRank

    async def rerank(self, query: str, chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        LLM 辅助 ReRank 相关度打分并过滤排序，实施“首尾夹逼”反 Lost in the Middle 分布。

        Args:
            query (str): 原始查询。
            chunks (List[Dict[str, Any]]): 候选 Chunks 列表。

        Returns:
            List[Dict[str, Any]]: 排好序的 Top-3 核心上下文块。
        """
        if not chunks:
            return []

        # 1. 批量并发对 Chunks 进行相关度打分，引入并发控制防止 429
        semaphore = asyncio.Semaphore(5)

        async def _score_chunk(chunk: Dict[str, Any]) -> Tuple[Dict[str, Any], float]:
            async with semaphore:
                text = chunk["payload"]["text"]
                prompt = [
                    {
                        "role": "system",
                        "content": (
                            "你是一个客观的技术文档相关度评估专家。\n"
                            "你需要评估给定的文档切片与用户查询问题之间的关联度，给出 0.0 - 1.0 的评分（1.0 代表最相关，0.0 代表毫无关系）。\n"
                            "评估指标：切片是否直接解答或提供了问题中的关键概念、原理解析。\n"
                            "必须严格按照 JSON Schema 格式输出，除 JSON 内容外不要包含任何其他自然语言文字。"
                        )
                    },
                    {
                        "role": "user",
                        "content": f"【用户查询】: {query}\n\n【待评估文档切片】: {text}\n\n请进行打分："
                    }
                ]
                try:
                    result = await self.client.request_llm_json(prompt, ReRankScore, temperature=0.01)
                    return chunk, result.score
                except Exception as ex:
                    logger.error(f"[ReRank 评估单条异常] {str(ex)}")
                    return chunk, 0.0  # 发生异常兜底为 0.0

        score_tasks = [_score_chunk(c) for c in chunks]
        scored_items = await asyncio.gather(*score_tasks)
        
        # 2. 过滤得分低于 0.3 的 Chunks，并按得分降序排列
        valid_items = [item for item in scored_items if item[1] >= 0.3]
        valid_items.sort(key=lambda x: x[1], reverse=True)
        
        top_chunks = [item[0] for item in valid_items[:3]]  # 至多保留最相关的 Top-3 Chunks
        
        # 3. 解决 Lost in the Middle：若有 3 个块，重排顺序为 [第1相关, 第3相关, 第2相关]
        # 这样确保最相关的两个块分别位于 Prompt 的最头部和最尾部
        final_chunks = []
        if len(top_chunks) == 3:
            final_chunks = [top_chunks[0], top_chunks[2], top_chunks[1]]
        elif len(top_chunks) == 2:
            final_chunks = [top_chunks[0], top_chunks[1]]
        else:
            final_chunks = top_chunks
            
        logger.info(f"[ReRank 完成] 保留并重排了 {len(final_chunks)} 个最相关上下文块")
        return final_chunks
