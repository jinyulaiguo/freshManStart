"""
Day 45 参考标准答案：Retrieve -> Augment -> Generate 经典 RAG 工作流原生编排

设计方案：
本模块提供经典 RAG 控制器管道的具体实现。系统打通了从向量生成、内存向量库写入，到相似度召回、
硬性边界相似度阈值拦截与大模型强契约生成的完整流程。

类与函数结构：
- RAGPipeline: 核心编排控制器类。
  - initialize_knowledge_base(): 自动化数据入库引擎，对每段文献执行 embed_single 向量化并批量 Upsert 进 Qdrant。
  - retrieve_context(): 检索引擎，获取用户 Query 向量并调用向量存储的 search_dense 进行联合过滤搜索。
  - answer(): 控制器总线。负责相似度分值安全判定（低于 0.6 执行 Null Fallback），并拼装 System 契约提示词调用大模型。

关键数据流：
1. 知识库加载：解析原始文本，计算高维向量，并发写入内存向量库。
2. Query 召回：用户 Query 向量化后，在内存库检索 Top-K。
3. 安全判定：获取 Top-1 块的相似度得分。若得分低于 0.6，则短路中断流程，直接返回降级提示，不进行大模型 API 调用。
4. 强约束生成：若得分达标，将检索到的片段格式化注入 System Prompt，设定温度值限制（temperature=0.01），调用大模型输出精准答案。
"""

import asyncio
from typing import List, Optional

# 导入必要的底层配置与网络请求类，严禁 Mock
from weekly.w04_prompt_and_http.utils import LLMClient
from weekly.w06_embedding_and_vector_db.utils import EmbeddingClient
from weekly.w06_embedding_and_vector_db.project.vector_store import QdrantVectorStore
from weekly.w06_embedding_and_vector_db.project.models import Chunk, ChunkWithVector, MetadataFilter

# 测试用的固定背景知识库
KNOWLEDGE_DOCUMENTS = [
    {"id": "fact_1", "content": "Antigravity 是由 Google Deepmind 团队设计开发的一款高性能高级 AI 编码智能体。", "title": "智能体介绍"},
    {"id": "fact_2", "content": "Python 3.12 在 2023 年正式发布，引入了简化的泛型语法、更清晰的类型别名以及高效的 f-string 解析机制。", "title": "Python新特性"},
    {"id": "fact_3", "content": "Qdrant 是一款使用 Rust 语言编写的高性能向量搜索引擎，支持高并发的 HNSW 检索与复杂的 Payload Pre-Filtering 联合过滤。", "title": "向量库介绍"}
]


class RAGPipeline:
    """经典 RAG 编排控制器，包含相似度边界拦截与空检索兜底降级逻辑"""
    
    def __init__(self, collection_name: str = "rag_knowledge", similarity_threshold: float = 0.4):
        """
        初始化 RAG 管道
        
        Args:
            collection_name (str): Qdrant 集合名称
            similarity_threshold (float): 检索相似度的硬拦截阈值，低于此分值将直接降级
        """
        self.collection_name = collection_name
        self.similarity_threshold = similarity_threshold
        
        # 初始化大模型与向量客户端
        self.llm_client = LLMClient()
        self.embedding_client = EmbeddingClient()
        # 降级至内存模式运行，确保环境零配置依赖
        self.vector_store = QdrantVectorStore(location=":memory:")
        
    async def initialize_knowledge_base(self, documents: List[dict]):
        """
        将背景知识文档写入内存向量库
        
        Args:
            documents (List[dict]): 包含 id, content, title 的字典列表
        """
        # 1. 物理重构或初始化向量库对应的 collection 集合，向量维数固定为 embo-01 模型的 1536 维
        self.vector_store.create_collection(
            collection_name=self.collection_name,
            dimension=1536
        )
        
        chunks_with_vectors = []
        for doc in documents:
            # 2. 调用真实的 EmbeddingClient 获取该句的文本表征向量，指定类型为 db 写入
            vector = await self.embedding_client.embed_single(
                text=doc["content"],
                embed_type="db"
            )
            
            # 3. 构造 Pydantic 规范的 Chunk 实体
            chunk = Chunk(
                chunk_id=doc["id"],
                document_id=doc["id"],
                content=doc["content"],
                title=doc["title"],
                permission_level=1,  # 默认等级
                user_id="anonymous"  # 匿名用户权限
            )
            
            chunks_with_vectors.append(
                ChunkWithVector(chunk=chunk, vector=vector)
            )
            
        # 4. 并发写入向量库集合
        self.vector_store.upsert_chunks(
            collection_name=self.collection_name,
            chunks_with_vectors=chunks_with_vectors
        )
        print(f"[RAGPipeline] 知识库冷启动完成，共导入 {len(documents)} 条向量记录")

    async def retrieve_context(self, query: str, limit: int = 2) -> List[dict]:
        """
        对用户提问执行高维空间相似度检索
        
        Args:
            query (str): 用户查询句
            limit (int): 检索召回的 Top-K 数量
            
        Returns:
            List[dict]: 包含 content, score, title 的检索块列表
        """
        # 1. 向量化用户的提问，指定类型为 query 检索
        query_vector = await self.embedding_client.embed_single(
            text=query,
            embed_type="query"
        )
        
        # 2. 构造对应的 MetadataFilter 进行多租户安全拦截限制
        filters = MetadataFilter(user_id="anonymous", max_permission_level=1)
        
        # 3. 执行 Dense 稠密向量检索
        results = self.vector_store.search_dense(
            collection_name=self.collection_name,
            query_vector=query_vector,
            limit=limit,
            filters=filters
        )
        
        # 4. 转换为便于拼装 Prompt 的字典结构输出
        return [
            {"content": r.content, "score": r.score, "title": r.title}
            for r in results
        ]

    async def answer(self, query: str) -> str:
        """
        经典 RAG 输入到生成的全生命周期控制
        
        Args:
            query (str): 用户查询提问
            
        Returns:
            str: 答案文本（或兜底拦截信息）
        """
        # 1. 相似度召回
        retrieved_chunks = await self.retrieve_context(query, limit=2)
        
        # 2. 检查边界状态：若检索列表为空，或者相似度第一名的得分低于我们的安全阈值
        if not retrieved_chunks or retrieved_chunks[0]["score"] < self.similarity_threshold:
            score_preview = retrieved_chunks[0]["score"] if retrieved_chunks else 0.0
            print(f"[RAGPipeline] ⚠️ 最高匹配得分 {score_preview:.4f} 低于安全阈值 {self.similarity_threshold}，触发 Fallback 物理阻断，拦截 LLM 调用。")
            return "对不起，未在参考库中找到对应事实。"
            
        # 3. 相似度达标，对检索块进行拼装格式化，作为增强上下文 (Augment)
        context_parts = []
        for i, c in enumerate(retrieved_chunks):
            # 仅采用相似度达标的块，防止低质噪声混入
            if c["score"] >= self.similarity_threshold:
                context_parts.append(
                    f"【文献-{i+1}】(出处: {c['title']}): {c['content']}"
                )
        context_str = "\n".join(context_parts)
        
        # 4. 在 System Prompt 中施加极其严格的类型契约，控制大模型的生成界限
        system_prompt = (
            "你是一个极其严谨的企业合规问答助手。你的回答必须严格遵循以下给出的【参考背景事实】。\n"
            "如果用户的提问无法从【参考背景事实】中直接、完全推导出来，你必须如实且唯一回复：\n"
            "“对不起，未在参考库中找到对应事实。”\n"
            "坚决不允许编造、假设，或引入你的任何预训练外部常识。\n\n"
            "【参考背景事实】:\n"
            f"{context_str}"
        )
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query}
        ]
        
        # 5. 调用大模型，将 temperature 限制为 0.01（极度保守模式），促成决定性输出
        print(f"[RAGPipeline] 🚀 检索相似度 {retrieved_chunks[0]['score']:.4f} 达标，进入大模型生成周期...")
        response_text = await self.llm_client.request_llm(
            messages=messages,
            temperature=0.01,
            max_tokens=600
        )
        
        return response_text


if __name__ == "__main__":
    async def main():
        print("=== Day 45 RAG 经典工作流编排与拦截 运行演示 ===")
        pipeline = RAGPipeline(similarity_threshold=0.4)
        
        # 1. 知识初始化与库加载
        await pipeline.initialize_knowledge_base(KNOWLEDGE_DOCUMENTS)
        
        # 2. 测试正常命中查询 (预期最高得分 >= 0.6)
        query_ok = "Antigravity 是由哪个团队设计的？"
        print(f"\n🔍 测试问题 1 [预期命中]：'{query_ok}'")
        ans_ok = await pipeline.answer(query_ok)
        print(f"RAG 管道输出结果：\n{ans_ok}")
        
        # 3. 测试无关问题拦截降级 (预期最高得分 < 0.6)
        query_fail = "麻婆豆腐的制作步骤是什么？"
        print(f"\n🔍 测试问题 2 [预期拦截]：'{query_fail}'")
        ans_fail = await pipeline.answer(query_fail)
        print(f"RAG 管道输出结果：\n{ans_fail}")
        
        # 验证断言：问题 2 的输出必须触发 Null Fallback
        assert "对不起，未在参考库中找到对应事实" in ans_fail
        print("\n✅ 物理过关验证成功！相似度达标时输出可信回答，低于 0.6 时完美触发 Null Fallback 拦截！")

    asyncio.run(main())
