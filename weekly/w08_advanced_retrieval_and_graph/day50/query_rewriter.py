"""
Day 50 参考答案：多路检索（Multi-Query）与 Query 变形（Query Rewrite）

设计方案：
1. 设计意图：
   本模块提供完整的 Query 改写与多路异步并发检索机制。
   主要针对原始提问与私有知识库之间的词汇鸿沟（Vocabulary Gap）导致低召回率的痛点，
   通过大模型产生 3 个变体，并用 asyncio 并行获取 Embedding 与 Qdrant 检索，
   最后基于 SHA-256 进行哈希去重并集。

2. 核心结构：
   - `QueryRewriter`: 真实调用大模型（LLMClient）异步请求，并严格解析单行变体输出。
   - `MultiQueryRetriever`: 采用 asyncio.gather 并发拉取 Embedding 并采用 asyncio.to_thread 
     执行 Qdrant 同步 Search 方法，防止内存数据库 I/O 阻塞 Python 事件循环。
   - `if __name__ == "__main__":` 调试主入口：用于展示完整真实的运行日志和前后召回数量对比。

3. 数据流与并发模型：
   原始提问 -> LLM 衍生变体 -> List[Query] (长度为4) 
   -> [asyncio.gather] -> 4路 Embedding 向量 
   -> [asyncio.gather(asyncio.to_thread)] -> 4路 Qdrant 搜索结果
   -> [SHA-256 字典过滤] -> 去重排序后的结果集。
"""

import asyncio
import hashlib
from typing import List, Dict, Any, Tuple
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct, Distance, VectorParams

# 导入公共工具与先前实现的客户端，保证真实网络请求与 API 契约
from weekly.w04_prompt_and_http.utils import LLMClient
from weekly.w06_embedding_and_vector_db.utils import EmbeddingClient


class QueryRewriter:
    """Query 改写引擎：利用真实 LLM 生成意图相同但词汇、句式表达各异的问题变体"""

    def __init__(self, llm_client: LLMClient):
        """初始化改写引擎
        
        Args:
            llm_client: 已经加载了环境变量的真实大模型客户端实例
        """
        self.llm_client = llm_client

    async def rewrite_query(self, query: str) -> List[str]:
        """对输入的问题进行语义变形，衍生出 3 个变体
        
        Args:
            query: 用户的原始问题
            
        Returns:
            包含 3 个新生成变体问题的列表（不包含原始提问）
            
        Raises:
            RuntimeError: LLM API 请求失败或解析异常时抛出
        """
        # 1. 构造高防指令 Prompt，迫使 LLM 仅输出干净的问题变体，每行一个
        messages = [
            {
                "role": "system",
                "content": (
                    "你是一个专业的搜索引擎查询改写助手。\n"
                    "你的任务是接收用户输入的原始中文问题，在保证原始语义不变的前提下，重新表达该问题，生成3个不同的中文变体问题。\n"
                    "要求：\n"
                    "1. 只输出生成的变体问题，每行输出一个，不要包含任何序号、序号前缀、多余的解释、思维链标签（如 <think>）或多余符号。\n"
                    "2. 严禁生成任何英文句子或解释，总共只输出3行中文。\n"
                    "示例输出：\n"
                    "CPython 并发限制度如何解决\n"
                    "Python多线程为什么不能利用多核CPU\n"
                    "如何提高Python密集计算的执行效率"
                )
            },
            {
                "role": "user",
                "content": f"原始提问：{query}"
            }
        ]

        # 2. 调用真实大模型，使用 0.7 适度温度以泛化词汇
        response_text = await self.llm_client.request_llm(
            messages=messages,
            temperature=0.7,
            max_tokens=500
        )

        # 3. 按行清洗并解析变体，执行防御性过滤拦截
        variants = []
        for line in response_text.strip().split("\n"):
            cleaned_line = line.strip()
            
            # 3.1 拦截思维链、说明文字以及无意义标签
            if not cleaned_line or "<think>" in cleaned_line or "</think>" in cleaned_line:
                continue
            # 3.2 强力拦截：作为中文提问改写，变体必须包含中文字符
            if not any('\u4e00' <= char <= '\u9fff' for char in cleaned_line):
                continue
            # 3.3 过滤大模型以英文开头输出的引导句或碎碎念（如 "Using different phrasing about..."）
            # 如果一行首字符是英文字母，且中文字符数小于 5 个，则判定为英文噪行并过滤
            if cleaned_line[0].isascii() and cleaned_line[0].isalpha():
                chinese_char_count = sum(1 for char in cleaned_line if '\u4e00' <= char <= '\u9fff')
                if chinese_char_count < 5:
                    continue
                
            # 3.2 过滤去除一些模型可能带出来的序号标记，如 "1. " 或 "1、"
            if cleaned_line.startswith(("1.", "2.", "3.", "1、", "2、", "3、", "- ", "* ")):
                cleaned_line = cleaned_line.split(".", 1)[-1].split("、", 1)[-1].strip()
                
            if cleaned_line:
                variants.append(cleaned_line)

        # 4. 防御性检查，确保哪怕生成行数不对，也至少保留前 3 个或截断
        return variants[:3]


class MultiQueryRetriever:
    """多路检索器：并发计算多路 Query 向量，向向量库请求检索，并完成哈希去重"""

    def __init__(
        self,
        qdrant_client: QdrantClient,
        embedding_client: EmbeddingClient,
        query_rewriter: QueryRewriter,
        collection_name: str = "code_review_kb"
    ):
        """初始化多路检索器
        
        Args:
            qdrant_client: Qdrant 客户端实例
            embedding_client: 向量编码客户端实例
            query_rewriter: QueryRewriter 改写引擎实例
            collection_name: 向量库集合名称
        """
        self.qdrant_client = qdrant_client
        self.embedding_client = embedding_client
        self.query_rewriter = query_rewriter
        self.collection_name = collection_name

    async def retrieve(self, query: str, top_k: int = 3) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """执行多路并发检索，并基于文本内容的 SHA-256 哈希值进行去重合并
        
        Args:
            query: 用户的原始提问
            top_k: 每一路检索返回的 Top-K 数量
            
        Returns:
            一个元组，包含：
            - 去重合并后的 Chunk 字典列表，每个字典形如 {"text": str, "score": float}
            - 统计元数据信息，如 {"raw_count": int, "deduped_count": int, "rewritten_queries": list}
        """
        # 1. 触发 LLM 改写获取变体，将原始提问和变体合并
        variants = await self.query_rewriter.rewrite_query(query)
        all_queries = [query] + variants

        # 2. 并发（asyncio.gather）为所有 Query 请求 Embedding 向量表征
        # 利用非阻塞并发降低网络时延
        embed_tasks = [
            self.embedding_client.embed_single(q_text, embed_type="query")
            for q_text in all_queries
        ]
        query_vectors = await asyncio.gather(*embed_tasks)

        # 3. 并发向 Qdrant 数据库发起相似度检索请求
        # 注意：QdrantClient 内存模式操作为同步 Block I/O，在此使用 asyncio.to_thread 委托给线程池
        # 使用最新的 client.query_points() API 并提取其 .points 结果
        async def _query_qdrant(vector, limit):
            res = await asyncio.to_thread(
                self.qdrant_client.query_points,
                collection_name=self.collection_name,
                query=vector,
                limit=limit
            )
            return res.points

        search_tasks = [
            _query_qdrant(v, top_k)
            for v in query_vectors
        ]
        raw_results_list = await asyncio.gather(*search_tasks)


        # 4. 哈希并集去重（以文档内容的 SHA-256 做唯一键，保障词汇对齐的绝对准确）
        unique_chunks = {}
        total_raw_count = 0

        for results in raw_results_list:
            total_raw_count += len(results)
            for hit in results:
                payload = hit.payload
                text_content = payload.get("text", "")
                
                # 计算文本哈希值作为去重指纹
                text_hash = hashlib.sha256(text_content.encode("utf-8")).hexdigest()
                score = hit.score

                # 如果内容已被召回过，则保留 score 更高（相关度更高）的记录
                if text_hash in unique_chunks:
                    if score > unique_chunks[text_hash]["score"]:
                        unique_chunks[text_hash] = {"text": text_content, "score": score}
                else:
                    unique_chunks[text_hash] = {"text": text_content, "score": score}

        # 5. 将去重后的结果按相关度分数降序重新排列
        sorted_results = sorted(
            unique_chunks.values(),
            key=lambda x: x["score"],
            reverse=True
        )

        # 6. 构造统计元数据，便于对比和审计
        metadata = {
            "raw_count": total_raw_count,
            "deduped_count": len(sorted_results),
            "rewritten_queries": all_queries
        }

        return sorted_results, metadata


# =====================================================================
# 🛠️ 预置测试数据注入与调试运行入口
# =====================================================================

async def prepare_mock_database(qdrant_client: QdrantClient, embedding_client: EmbeddingClient, collection_name: str):
    """辅助函数：在内存向量库中预置测试知识库数据，模拟代码审查知识库"""
    kb_documents = [
        "CPython 解释器的全局解释器锁 (GIL) 对多线程计算做出了物理限制，导致多线程无法并发利用多核 CPU，对于 CPU 密集型任务应通过进程池 (ProcessPoolExecutor) 规避并发瓶颈。",
        "asyncio 异步事件循环的底层基于非阻塞 I/O 多路复用，非常适合网络请求、文件读写等 I/O 密集型并发任务，但不适合含有密集计算的 CPU 绑定任务。",
        "Python 对象的垃圾回收机制主要基于引用计数，辅助以标记清除和分代收集。频繁创建临时大对象会导致高频触发 GC 暂停，带来显著的吞吐量开销。"
    ]
    
    # recreate_collection 在内存模式下初始化集合架构
    qdrant_client.recreate_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(size=1536, distance=Distance.COSINE) # MiniMax-M3 Embedding 向量长度为 1536
    )
    
    # 批量计算真实文本表征向量并 Upsert 入库
    vectors = await embedding_client.embed_texts(kb_documents, embed_type="db")
    points = [
        PointStruct(
            id=idx,
            vector=vector,
            payload={"text": doc, "hash": hashlib.sha256(doc.encode("utf-8")).hexdigest()}
        )
        for idx, (doc, vector) in enumerate(zip(kb_documents, vectors))
    ]
    qdrant_client.upsert(collection_name=collection_name, points=points)
    print("-> 内存向量数据库初始化成功，已成功写入 3 条技术参考 Chunks。\n")


async def main():
    """本地手动调试主入口"""
    print("=== 开始 Day 50 Multi-Query 检索链本地调试 (标准答案) ===\n")
    
    # 1. 初始化依赖客户端
    try:
        llm = LLMClient()
        embed = EmbeddingClient()
        qdrant = QdrantClient(location=":memory:") # 使用 Qdrant 内存模式，防止依赖外部服务
        collection_name = "code_review_kb"
        
        # 注入测试数据
        await prepare_mock_database(qdrant, embed, collection_name)
    except Exception as e:
        print(f"依赖服务初始化失败 (检查 .env 配置文件): {e}")
        return

    # 2. 初始化检索器
    rewriter = QueryRewriter(llm)
    retriever = MultiQueryRetriever(qdrant, embed, rewriter, collection_name)

    # 3. 原始提问（词汇存在表示鸿沟）
    query = "Python 并发如何优化以消除 CPU 瓶颈？"
    print(f"原始提问: '{query}'\n")

    # 4. 执行多路检索并输出详细数据对比
    try:
        print("正在调用 LLM 进行 Query Rewrite...")
        variants = await rewriter.rewrite_query(query)
        print(f"改写成功！生成变体: {variants}\n")
        
        print("正在并行执行 Multi-Query 并发检索与哈希去重...")
        results, meta = await retriever.retrieve(query, top_k=2)
        
        print("\n--- 检索统计元数据 ---")
        print(f"原始汇总检索量 (含重复): {meta['raw_count']}")
        print(f"去重合并后数量: {meta['deduped_count']}")
        print(f"多路改写查询列表: {meta['rewritten_queries']}")
        
        print("\n--- 召回知识详情 ---")
        for i, chunk in enumerate(results):
            print(f"[{i+1}] (相似度得分: {chunk['score']:.4f}):\n   {chunk['text']}\n")
            
    except Exception as e:
        print(f"\n❌ 运行发生异常: {e}")


if __name__ == "__main__":
    asyncio.run(main())
