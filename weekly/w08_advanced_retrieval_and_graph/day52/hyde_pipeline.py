"""
Day 52 参考答案：假设性文档嵌入（HyDE, Hypothetical Document Embeddings）

设计方案：
1. 设计意图：
   提供完整的 HyDE 检索管道实现。解决问答向量空间不对称（Representation Gap）痛点。
   使用 LLM 预先模拟“完美陈述句解答”以拉近拓扑距离，提升检索系统的首位命中率（Hit@1）。
   并在调用 LLM 失败时设计了自动退化为原始提问检索（Fallback to Baseline）的抗毁容错方案。

2. 核心结构：
   - `HyDEPipeline`:
     - `generate_hypothetical_document`: 调用真实大模型（Zero-Shot API）生成 150 字以内的陈述解答文档。
     - `retrieve_with_hyde`: 并发安全地提取假设文档 Embedding 并去 Qdrant 进行 query_points 查询。
     - `retrieve_normal`: 以原始提问直接检索，用于结果对比校验。
   - `if __name__ == "__main__":` 调试主入口：演示并量化对比普通检索与 HyDE 检索的结果和得分优势。

3. 防错与并发处理：
   - 对 Qdrant query_points 检索方法使用 asyncio.to_thread 委托至线程池，防止 Block Python 协程事件循环。
   - 对 generate_hypothetical_document 进行了 try-except 降级包裹，如果 API 请求超时则直接将原始 query 代替假设文档，确保不停机。
"""

import asyncio
from typing import List, Dict, Any, Tuple
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams


# 导入真实客户端
from weekly.w04_prompt_and_http.utils import LLMClient
from weekly.w06_embedding_and_vector_db.utils import EmbeddingClient


class HyDEPipeline:
    """HyDE 检索管道：实现假设答案生成与多路 RAG 基线对比"""

    def __init__(
        self,
        qdrant_client: QdrantClient,
        embedding_client: EmbeddingClient,
        llm_client: LLMClient,
        collection_name: str = "hyde_review_kb"
    ):
        """初始化 HyDE 检索管道
        
        Args:
            qdrant_client: Qdrant 客户端实例
            embedding_client: 向量编码客户端实例
            llm_client: 真实大模型客户端实例
            collection_name: 向量库集合名称
        """
        self.qdrant_client = qdrant_client
        self.embedding_client = embedding_client
        self.llm_client = llm_client
        self.collection_name = collection_name

    async def generate_hypothetical_document(self, query: str) -> str:
        """调用大模型为原始提问生成一篇假设性的答案文档 (Hypothetical Document)
        
        Args:
            query: 原始的用户问题
            
        Returns:
            生成的假设解答短文文本
            
        Raises:
            RuntimeError: LLM API 请求失败时抛出异常
        """
        messages = [
            {
                "role": "system",
                "content": (
                    "你是一个资深的后台架构调试专家。\n"
                    "你需要针对用户提出的系统报错问题，写出一篇假设性的、内容详尽且符合专业规范的技术文档片段作为回答。\n"
                    "要求：\n"
                    "1. 直接给出可能的具体故障原因与具体的优化配置命令，不需要包含任何多余前缀，只用标准的中文技术手册句式。\n"
                    "2. 使用肯定的陈述句，严禁包含任何“可能”、“这只是个假设”、“可能的原因是”等不确定语气词。\n"
                    "3. 长度严格控制在 100 到 200 字之间。\n"
                    "4. 如果你使用了思维链（如 <think> 标签），请务必在 </think> 闭合标签外部输出最终的诊断答案文本，严禁将所有诊断答案仅保留在 think 内部。"

                )
            },
            {
                "role": "user",
                "content": f"用户问题：{query}"
            }
        ]

        # 使用中等温度 0.5 保证模型生成语句在保留严谨表达的同时有适当发散能力
        hypo_text = await self.llm_client.request_llm(
            messages=messages,
            temperature=0.5,
            max_tokens=600  # 扩大 max_tokens 以防思维链被截断导致 </think> 无法闭合
        )

        # 3. 防错设计：物理剔除大模型可能自带的思维链（Reasoning）标签及思考过程
        import re
        if "<think>" in hypo_text:
            # 采用 re.DOTALL 模式进行跨行贪婪剔除
            hypo_text = re.sub(r"<think>.*?</think>", "", hypo_text, flags=re.DOTALL)

        return hypo_text.strip()


    async def retrieve_with_hyde(self, query: str, top_k: int = 2) -> Tuple[List[Dict[str, Any]], str]:
        """以生成的假设解答短文的 Embedding 向量去向量库执行语义匹配检索
        
        Args:
            query: 用户的原始问题
            top_k: 期望返回的最相似 Chunk 数量
            
        Returns:
            一个元组，包含：
            - 检索出来的真实 Chunk 列表，每个元素格式为 {"text": str, "score": float}
            - 此次生成的假设性答案文档内容 (用于对比审计)
        """
        # 1. 尝试大模型生成假设文档，如果由于网络超时失败或生成文本为空（全部缩水在 think 内部），自动降级为使用原始问题直接检索
        try:
            hypo_doc = await self.generate_hypothetical_document(query)
            if not hypo_doc.strip():
                print("⚠️ 警告: 假设文档剥离后为空，自动降级为常规检索模式。")
                hypo_doc = query
        except Exception as e:
            print(f"⚠️ HyDE 假设文档生成失败 (降级为常规检索模式): {e}")
            hypo_doc = query

        # 2. 调用真实的 EmbeddingClient 获取该假设答案的文本特征表征向量
        # 类型指定为 query 检索类型
        hypo_vector = await self.embedding_client.embed_single(hypo_doc, embed_type="query")

        # 3. 在 Qdrant 数据库中检索语义距离最近的真实切片
        # 使用 asyncio.to_thread 包装以防止 Qdrant 内存模式的同步 search 占用主协程时间片
        results = await asyncio.to_thread(
            self.qdrant_client.query_points,
            collection_name=self.collection_name,
            query=hypo_vector,
            limit=top_k
        )

        # 4. 解析结果
        chunks = []
        for hit in results.points:
            chunks.append({
                "text": hit.payload.get("text", ""),
                "score": hit.score
            })

        return chunks, hypo_doc

    async def retrieve_normal(self, query: str, top_k: int = 2) -> List[Dict[str, Any]]:
        """传统的直接检索基线：以原始问题的 Embedding 去向量库执行检索，供对比验证
        
        Args:
            query: 用户的原始问题
            top_k: 期望返回的最相似 Chunk 数量
            
        Returns:
            检索出来的真实 Chunk 列表，格式为 {"text": str, "score": float}
        """
        # 1. 直接获取原始提问的 Embedding 向量
        query_vector = await self.embedding_client.embed_single(query, embed_type="query")

        # 2. Qdrant 相似度检索
        results = await asyncio.to_thread(
            self.qdrant_client.query_points,
            collection_name=self.collection_name,
            query=query_vector,
            limit=top_k
        )

        # 3. 解析结果
        chunks = []
        for hit in results.points:
            chunks.append({
                "text": hit.payload.get("text", ""),
                "score": hit.score
            })

        return chunks


# =====================================================================
# 🛠️ 预置测试数据注入与调试运行入口
# =====================================================================

async def prepare_mock_database(qdrant_client: QdrantClient, embedding_client: EmbeddingClient, collection_name: str):
    """辅助函数：在内存向量库中预置测试知识库数据，模拟架构异常规范库"""
    kb_documents = [
        "当 Redis 服务接收到过大的高并发连接请求，而 Linux 系统的 net.core.somaxconn（内核监听队列上限）以及 redis.conf 中的 maxclients（最大连接数限制）过低时，系统会因为排队队列溢出，在客户端物理抛出 'Connection refused' 的并发网络异常报错。",
        "当 Redis 物理内存耗尽，且未配置 maxmemory 驱逐策略时，写入操作会触发 OOM 异常。应当配置 maxmemory-policy volatile-lru 并开启 AOF 压缩以释放空间，防止引擎挂起崩溃。",
        "PostgreSQL 在遇到高并发写事务冲突时，会发生内部行级锁竞争（Row-level Lock Contention）。应在应用层使用乐观锁或在 SQL 侧使用 SELECT FOR UPDATE NOWAIT 快速失败机制。"
    ]
    
    # 物理重建集合架构
    qdrant_client.recreate_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(size=1536, distance=Distance.COSINE) # MiniMax 编码器为 1536 维
    )
    
    # 并发计算 Embedding 并批量 Upsert
    vectors = await embedding_client.embed_texts(kb_documents, embed_type="db")
    from qdrant_client.models import PointStruct
    points = [
        PointStruct(
            id=idx,
            vector=vector,
            payload={"text": doc}
        )
        for idx, (doc, vector) in enumerate(zip(kb_documents, vectors))
    ]
    qdrant_client.upsert(collection_name=collection_name, points=points)
    print("-> 内存向量数据库初始化成功，已成功写入 3 条异常参考规范文档 Chunks。\n")


async def main():
    """本地手动调试主入口"""
    print("=== 开始 Day 52 HyDE 检索管道本地调试 (标准答案) ===\n")
    
    # 1. 初始化依赖服务
    try:
        llm = LLMClient()
        embed = EmbeddingClient()
        qdrant = QdrantClient(location=":memory:")
        collection_name = "hyde_review_kb"
        
        await prepare_mock_database(qdrant, embed, collection_name)
    except Exception as e:
        print(f"依赖服务初始化失败 (检查 .env 配置文件): {e}")
        return

    pipeline = HyDEPipeline(qdrant, embed, llm, collection_name)

    # 原始问题（口语问句，与陈述性规范存在表示差异）
    query = "如何解决 Redis 抛出 'Connection refused' 的并发网络报错？"
    print(f"原始提问: '{query}'\n")

    # 2. 执行双路检索并对比打分差异
    try:
        # A. 常规检索基线
        print("--- 正在执行 [方案 A] 传统直接向量检索 (基线对比) ---")
        normal_results = await pipeline.retrieve_normal(query, top_k=2)
        for i, chunk in enumerate(normal_results):
            print(f"[{i+1}] (余弦相似度得分: {chunk['score']:.4f}):\n   {chunk['text'][:90]}...")
            
        # B. HyDE 检索
        print("\n--- 正在执行 [方案 B] HyDE 假设文档对齐检索 ---")
        hyde_results, hypo_doc = await pipeline.retrieve_with_hyde(query, top_k=2)
        print(f"\n[大模型生成的假设解答文档]:\n{hypo_doc}\n")
        
        print("--- HyDE 最终召回结果 ---")
        for i, chunk in enumerate(hyde_results):
            print(f"[{i+1}] (余弦相似度得分: {chunk['score']:.4f}):\n   {chunk['text'][:90]}...")
            
    except Exception as e:
        print(f"\n❌ 运行发生未预期错误: {e}")


if __name__ == "__main__":
    asyncio.run(main())
