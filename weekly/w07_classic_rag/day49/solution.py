"""
Day 49 参考标准答案：公司内部规章制度问答 Bot (带完美引用与语义切块)

设计方案：
==========
1. 设计意图：
   本模块提供一个生产级的 RAG 智能问答系统，集成多格式文档解析、基于句子相似度突变点的自适应语义切块、
   SHA-256去重哈希索引构建、高维密集向量检索、Lost-in-the-Middle 规避（LLM Reranker 重排）
   以及基于 Context 可信脚注引用的流式问答与反向映射。
   
2. 架构设计：
   - ChunkIndexer: 批量文档入库引擎。
     - 自动检测并物理重建 Qdrant 集合（连接本地 Docker 实例 127.0.0.1:6333）。
     - 逐页调用 SemanticTextSplitter 提取语义分块，用 SHA-256 计算唯一内容哈希进行全局去重。
     - 并发计算 Embedding，批量 Upsert 进 Qdrant。
   - LLMReranker: 通用 Cross-Encoder 重排器。
     - 限制最大并发，对初筛 Top-15 的 Chunk 并发请求 LLM 进行 0-100 相关度打分，降序重排。
   - CitationRAGBot: 主控制总线。
     - 实现 Null Fallback 相似度拦截，当 Top-1 分数低于阈值时快速短路。
     - 注入 System 契约 Prompt，强制 LLM 进行引用并输出 [doc_id:page] 脚注。
     - 使用 httpx.AsyncClient 的 stream 接口获取大模型流式响应，实现 SSE 流式输出。
     - 使用正则表达式提取所有脚注，去重并反向映射出对应的源文本对照审计表。

3. 关键数据流：
   - 物理文档 -> 解析富集元数据 -> 语义切片 -> 哈希指纹去重 -> 批量向量化 -> 批量 Qdrant 写入。
   - 用户 Query -> 向量检索 -> Top-15 召回 -> LLM 语义重排 -> 流式契约生成 -> 脚注正则抓取 -> 控制台高亮输出。
"""

import os
import re
import math
import hashlib
import json
import asyncio
import sys
import datetime
from typing import List, Dict, Tuple, AsyncGenerator, Optional

import httpx

# 导入底层基础设施和前几天的可复用组件
from weekly.w04_prompt_and_http.utils import LLMClient
from weekly.w06_embedding_and_vector_db.utils import EmbeddingClient
from weekly.w06_embedding_and_vector_db.project.vector_store import QdrantVectorStore
from weekly.w06_embedding_and_vector_db.project.models import Chunk, ChunkWithVector
from weekly.w07_classic_rag.day44.solution import SemanticTextSplitter
from weekly.w07_classic_rag.day48.solution import MultiFormatDocIngestor


class ChunkIndexer:
    """向量库索引构建与去重引擎"""

    def __init__(self, collection_name: str = "company_policy", dimension: int = 1536):
        """
        初始化索引构建器
        
        Args:
            collection_name: Qdrant 集合名称
            dimension: 向量维度，默认 1536 (embo-01)
        """
        self.collection_name = collection_name
        self.dimension = dimension
        
        self.embedding_client = EmbeddingClient()
        self.splitter = SemanticTextSplitter(threshold_step=1.0)
        # 初始化 Qdrant 客户端，物理连接本地 Docker 中的实例 (127.0.0.1:6333)
        self.vector_store = QdrantVectorStore(url="http://127.0.0.1", port=6333)

    def _compute_content_hash(self, content: str, doc_id: str, page: int) -> str:
        """
        根据文本内容、文档ID和页码计算唯一的 SHA-256 哈希值作为内容指纹
        
        Args:
            content: 文本内容
            doc_id: 文档标识
            page: 页码
            
        Returns:
            str: 64位十六进制哈希指纹
        """
        hash_input = f"{content}|||{doc_id}|||{page}"
        return hashlib.sha256(hash_input.encode("utf-8")).hexdigest()

    async def ingest_and_index(self, pages: List[Dict], recreate: bool = False) -> int:
        """
        主索引流：对多格式文档进行语义切片、哈希去重、批量向量化并写入 Qdrant
        
        Args:
            pages: 包含 content 和 metadata 的页面数据列表
            recreate: 是否物理重建向量库集合，若为 False 则增量写入
            
        Returns:
            int: 成功入库构建索引 of Chunk 总数
        """
        # Step 1: 物理重建或检查创建 Qdrant Collection
        if recreate or not self.vector_store.client.collection_exists(self.collection_name):
            print(f"[Indexer] 正在物理重建/初始化 Qdrant 集合: {self.collection_name}...")
            self.vector_store.create_collection(
                collection_name=self.collection_name,
                dimension=self.dimension
            )
        else:
            print(f"[Indexer] 正在增量写入已存在的 Qdrant 集合: {self.collection_name}...")

        all_chunks: List[Chunk] = []
        seen_hashes = set()
        chunk_count = 0

        # Step 2: 逐页进行语义分块与元数据富集
        for page in pages:
            content = page.get("content", "").strip()
            if not content:
                continue
            
            metadata = page.get("metadata", {})
            source_file = metadata.get("source_file", "unknown")
            page_number = metadata.get("page_number", 1)
            file_type = metadata.get("file_type", "txt")
            
            # 使用源文件名的 md5 前缀生成全局简短的 doc_id，便于大模型脚注引用
            doc_md5 = hashlib.md5(source_file.encode("utf-8")).hexdigest()[:6]
            doc_id = f"doc_{doc_md5}"

            # 使用 Day 44 的 SemanticTextSplitter 自适应语义切块
            chunks_text = await self.splitter.split_text(content)
            
            for idx, chunk_text in enumerate(chunks_text):
                chunk_text = chunk_text.strip()
                if not chunk_text:
                    continue
                
                # 计算 SHA-256 内容指纹，用于去重
                content_hash = self._compute_content_hash(chunk_text, doc_id, page_number)
                
                # 如果当前批次或去重库中已经存在此哈希，则丢弃，防范冗余
                if content_hash in seen_hashes:
                    continue
                seen_hashes.add(content_hash)
                
                chunk_id = f"{doc_id}_chunk_{page_number}_{idx}"
                
                # 构造 Pydantic 规范的 Chunk 实体
                chunk_obj = Chunk(
                    chunk_id=chunk_id,
                    document_id=doc_id,
                    content=chunk_text,
                    chunk_index=chunk_count,
                    title=source_file,
                    source_path=source_file,
                    page_number=page_number,
                    char_length=len(chunk_text),
                    hash=content_hash,
                    category="policy",
                    permission_level=1,
                    user_id="default"
                )
                all_chunks.append(chunk_obj)
                chunk_count += 1

        if not all_chunks:
            print("[Indexer] 未找到任何有效的非重复知识切片，跳过写入。")
            return 0

        # Step 3: 批量向量化 (优化网络 I/O)
        print(f"[Indexer] 正在批量向量化 {len(all_chunks)} 个非重复切片...")
        texts_to_embed = [c.content for c in all_chunks]
        embeddings = await self.embedding_client.embed_texts(texts_to_embed, embed_type="db")

        # Step 4: 构造 ChunkWithVector 列表并批量 Upsert 进 Qdrant
        chunks_with_vectors = []
        for chunk, vector in zip(all_chunks, embeddings):
            chunks_with_vectors.append(
                ChunkWithVector(chunk=chunk, vector=vector)
            )

        self.vector_store.upsert_chunks(
            collection_name=self.collection_name,
            chunks_with_vectors=chunks_with_vectors
        )
        print(f"[Indexer] 索引构建完成！共成功入库 {len(all_chunks)} 个非重复 Chunk。")
        return len(all_chunks)


class LLMReranker:
    """基于大模型语义打分的通用重排器 (Cross-Encoder)"""

    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client
        # 并发控制，限制最大并发以防 429 频率超限
        self.semaphore = asyncio.Semaphore(3)

    async def _score_chunk(self, query: str, chunk_content: str) -> float:
        """
        调用大模型对单个 Chunk 与提问的语义相关性进行 0.0 - 100.0 打分
        
        Args:
            query: 用户提问
            chunk_content: 文献片段内容
            
        Returns:
            float: 相关度得分
        """
        system_prompt = (
            "你是一个极其严谨的语义相关性打分器。你需要评估给定的背景文献与用户提问的相关度。\n"
            "打分标准如下：\n"
            "- 90.0-100.0 分：背景文献与提问完全契合，能直接提供完整、精准的解答答案。\n"
            "- 60.0-89.0 分：高度相关，包含了大部分背景概念，但不能直接、完全回答该提问。\n"
            "- 30.0-59.0 分：有一些概念性或词语上的重合，但两者的核心意图有明显偏差。\n"
            "- 0.0-29.0 分：完全不相关，或属于毫不相关的噪音。\n\n"
            "【强约束】：你必须且只能输出一个数字分值（例如 '95.5' 或 '40'），严禁包含任何其他字词、标点、前缀、空格或解释性陈述。"
        )
        user_prompt = f"用户提问：{query}\n背景文献：{chunk_content}"
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        # 增加异常捕捉和正则防错过滤
        try:
            async with self.semaphore:
                response = await self.llm_client.request_llm(
                    messages=messages,
                    temperature=0.01,
                    max_tokens=10
                )
                cleaned_response = response.strip()
                # 使用正则抓取第一个数字或浮点数
                match = re.search(r"(\d+(?:\.\d+)?)", cleaned_response)
                if match:
                    score = float(match.group(1))
                    return max(0.0, min(score, 100.0))
                return 0.0
        except Exception as e:
            print(f"⚠️ [Reranker] 单个分块打分异常: {e}")
            return 0.0

    async def rerank(self, query: str, chunks: List[Dict]) -> List[Dict]:
        """
        并发打分并降序排列
        
        Args:
            query: 用户提问
            chunks: 原始初筛得到的 Chunk 字典列表
            
        Returns:
            List[Dict]: 按相关性分数降序重排后的 Chunk 列表
        """
        if not chunks:
            return []
        
        print(f"[Reranker] 正在对 {len(chunks)} 个初筛分块进行并发大模型重排打分...")
        # Step 1: 并发调度打分
        tasks = [self._score_chunk(query, c["content"]) for c in chunks]
        scores = await asyncio.gather(*tasks)

        # Step 2: 富集得分并进行降序排列
        reranked_chunks = []
        for chunk, score in zip(chunks, scores):
            c_copy = chunk.copy()
            c_copy["rerank_score"] = score
            reranked_chunks.append(c_copy)

        reranked_chunks = sorted(reranked_chunks, key=lambda x: x["rerank_score"], reverse=True)
        return reranked_chunks


class CitationRAGBot:
    """具备可信引用生成、解析与流式输出的经典 RAG 控制器"""

    def __init__(self, indexer: ChunkIndexer, similarity_threshold: float = 0.4):
        """
        初始化问答 Bot
        
        Args:
            indexer: 已绑定向量连接的索引服务实例
            similarity_threshold: 检索匹配得分硬拦截阈值，低于此值则直接 Fallback
        """
        self.indexer = indexer
        self.similarity_threshold = similarity_threshold
        
        self.llm_client = LLMClient()
        self.reranker = LLMReranker(self.llm_client)

    def parse_citations(self, response_text: str) -> List[Tuple[str, int]]:
        """
        正则解析 response_text 提取脚注，并首次出现顺序去重
        
        Args:
            response_text: LLM 回答的完整文本
            
        Returns:
            List[Tuple[str, int]]: 去重后的 (doc_id, page_number) 元组列表
        """
        if not response_text:
            return []
        
        # 容忍冒号及末尾括号前的空格
        pattern = r"\[(doc_[a-fA-F0-9]+)\s*:\s*(\d+)\s*\]"
        matches = re.findall(pattern, response_text)
        
        unique_citations = []
        seen = set()
        for doc_id, page_str in matches:
            pair = (doc_id, int(page_str))
            if pair not in seen:
                seen.add(pair)
                unique_citations.append(pair)
        return unique_citations

    async def answer_stream(self, query: str) -> AsyncGenerator[Dict, None]:
        """
        经典 RAG 检索 -> 重排 -> 流式响应 -> 脚注解析的反向映射主控流
        
        Args:
            query: 用户提问
            
        Yields:
            Dict: 流式信息数据字典
        """
        yield {"type": "status", "content": "正在向量化用户查询并执行初筛检索..."}
        
        # Step 1: 向量化提问并召回 Top-15 (大样本初筛)
        query_vector = await self.indexer.embedding_client.embed_single(query, embed_type="query")
        
        # 直接使用 Qdrant query_points 底层，确保完整取到 page_number 和 document_id 等 Payload
        results = self.indexer.vector_store.client.query_points(
            collection_name=self.indexer.collection_name,
            query=query_vector,
            limit=15
        )

        raw_chunks = []
        chunk_registry = {}  # 用于后续脚注反向快速查找
        
        for p in results.points:
            payload = p.payload or {}
            chunk_info = {
                "chunk_id": payload.get("chunk_id", ""),
                "document_id": payload.get("document_id", ""),
                "content": payload.get("content", ""),
                "page_number": payload.get("page_number", 1),
                "source_file": payload.get("source_path", "unknown"),
                "score": float(p.score)
            }
            raw_chunks.append(chunk_info)
            # 建立 (document_id, page_number) -> chunk 字典映射，用于脚注查找原始事实
            key = (chunk_info["document_id"], chunk_info["page_number"])
            if key not in chunk_registry:
                chunk_registry[key] = chunk_info

        # Step 2: 阈值拦截校验 (Null Result Fallback)
        if not raw_chunks or raw_chunks[0]["score"] < self.similarity_threshold:
            print(f"[RAGBot] ⚠️ 初筛最高分 {raw_chunks[0]['score'] if raw_chunks else 0.0:.4f} 低于安全线 {self.similarity_threshold}，触发 Fallback 物理拦截")
            yield {"type": "status", "content": "匹配相似度不足，直接触发空检索拦截..."}
            yield {"type": "delta", "content": "对不起，未在参考库中找到对应事实。"}
            yield {"type": "final", "answer": "对不起，未在参考库中找到对应事实。", "citations": []}
            return

        # Step 3: 大模型 Cross-Encoder 重排，规避 U 型曲线遗忘
        yield {"type": "status", "content": "初筛检索完成，正在进行大模型 Cross-Encoder 重排..."}
        reranked_chunks = await self.reranker.rerank(query, raw_chunks)

        # Step 4: 拼装强契约 Prompt 与背景事实，要求严格引用
        context_parts = []
        for idx, rc in enumerate(reranked_chunks):
            context_parts.append(
                f"【文献-{idx+1}】[ID: {rc['document_id']}, 页码: {rc['page_number']}, 出处: {rc['source_file']}]:\n{rc['content']}"
            )
        context_str = "\n\n".join(context_parts)

        system_prompt = (
            "你是一个极其诚实、严谨的公司合规审查问答助手。\n"
            "你的任务是根据给出的【参考背景文献】回答用户的问题。\n"
            "为了保障回答的可信度与合规溯源，你必须在回答中陈述任何来自于文献的事实句尾（标点符号之前），"
            "紧跟并标注其直接引用的文献脚注。格式必须严格为：`[doc_id:page_number]`。\n\n"
            "【强制规则契约】：\n"
            "1. 必须严格执行 `[doc_id:page_number]` 格式标引。绝对不允许错标或漏标。注意格式是 [doc_xxx:页码]，不要写成 [文献-x] 或 [Page x]。\n"
            "2. 只能针对陈述句中直接依赖的背景事实句标引脚注，不能凭空捏造脚注。\n"
            "3. 如果问题无法从【参考背景文献】中直接、完全推导出来，你必须且唯一回复：\n"
            "“对不起，未在参考库中找到对应事实。”\n"
            "绝对不允许引入你的任何预训练常识。\n\n"
            "【参考背景文献】:\n"
            f"{context_str}"
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query}
        ]

        yield {"type": "status", "content": "正在流式请求大模型生成答案..."}

        # Step 5: 使用 httpx 物理流式调用大模型 API (SSE 协议解析)
        headers = {
            "Authorization": f"Bearer {self.llm_client.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.llm_client.model_name,
            "messages": messages,
            "temperature": 0.01, # 极限保守模式
            "max_tokens": 1000,
            "stream": True
        }

        full_answer = ""
        timeout_policy = httpx.Timeout(timeout=30.0)
        
        async with httpx.AsyncClient(timeout=timeout_policy) as client:
            async with client.stream(
                "POST",
                f"{self.llm_client.base_url}/chat/completions",
                headers=headers,
                json=payload
            ) as response:
                if response.status_code != 200:
                    error_body = await response.aread()
                    raise RuntimeError(f"LLM Stream API 异常 (HTTP {response.status_code}): {error_body.decode('utf-8')}")
                
                # 逐行读取 SSE 内容
                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith("data:"):
                        data_str = line[5:].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            data_json = json.loads(data_str)
                            delta = data_json["choices"][0]["delta"].get("content", "")
                            if delta:
                                full_answer += delta
                                yield {"type": "delta", "content": delta}
                        except Exception:
                            continue

        # Step 6: 答案生成完毕，提取脚注并反向映射原始文献
        yield {"type": "status", "content": "答案生成结束，正在解析可信脚注来源..."}
        citation_pairs = self.parse_citations(full_answer)
        
        citations = []
        for doc_id, page in citation_pairs:
            key = (doc_id, page)
            if key in chunk_registry:
                # 能够成功映射，富集段落内容和出处文件
                citations.append({
                    "doc_id": doc_id,
                    "page": page,
                    "source_file": chunk_registry[key]["source_file"],
                    "content": chunk_registry[key]["content"]
                })
            else:
                # 记录可能存在的越界或乱标引幻觉
                print(f"⚠️ [RAGBot] 检测到模型生成了库中不存在的脚注：{doc_id}:{page}")

        yield {"type": "final", "answer": full_answer, "citations": citations}


async def run_interactive_repl(bot: CitationRAGBot):
    """
    运行交互式问答 REPL
    
    Args:
        bot: CitationRAGBot 实例
    """
    print("\n" + "="*80)
    print("      🌟 欢迎使用公司内部规章制度问答 Bot (Day 49 综合实战版) 🌟")
    print("      配色方案: Warm Intellectual Minimalism (温润知性极简主义)")
    print("="*80 + "\n")
    print("系统已连接本地 Docker 中的 Qdrant (127.0.0.1:6333) 实例。")
    print("提示：输入 'quit' 或 'exit' 退出系统。\n")

    while True:
        try:
            # 等待用户输入问题
            query = input("\n👤 提问 > ").strip()
            if not query:
                continue
            if query.lower() in ("quit", "exit"):
                print("👋 感谢使用，系统退出。")
                break
            
            print()
            # 开启异步流式获取响应
            async for packet in bot.answer_stream(query):
                ptype = packet["type"]
                if ptype == "status":
                    # 知性灰色小字显示处理状态
                    sys.stdout.write(f"\033[90m[{packet['content']}]\033[0m\n")
                    sys.stdout.flush()
                elif ptype == "delta":
                    # 墨炭黑色正常输出 LLM Token
                    sys.stdout.write(packet["content"])
                    sys.stdout.flush()
                elif ptype == "final":
                    print("\n")
                    citations = packet["citations"]
                    if citations:
                        # 采用 Warm Intellectual Minimalism 的 Secondary Accent 杏粘土色 (#D97757，这里用 ANSI 橙/棕色)
                        print("\033[33m" + "="*25 + " 📄 原始文献溯源审计表 " + "="*25 + "\033[0m")
                        for idx, cite in enumerate(citations, start=1):
                            print(f" \033[1m[{idx}] [{cite['doc_id']}:{cite['page']}]\033[0m")
                            print(f"   - 来源文献: \033[4m{cite['source_file']}\033[0m")
                            # 还原内容缩略，采用 organic 绿色包裹表示成功命中
                            print(f"   - 原始段落: \033[32m{cite['content']}\033[0m")
                            print("-" * 72)
                        print("\033[33m" + "="*72 + "\033[0m")
                    else:
                        print("\033[90m[本次生成未包含有效引用来源]\033[0m")
        except Exception as e:
            print(f"\n\033[31m⚠️ 运行发生异常: {e}\033[0m")


async def main():
    test_dir = "./weekly/w07_classic_rag/day49/test_docs"
    
    # Step 1: 扫描解析
    print(f"📁 正在扫描测试文档目录: {test_dir}")
    ingestor = MultiFormatDocIngestor(test_dir)
    pages = ingestor.scan_and_ingest()
    print(f"📁 扫描结束。共读取 {len(pages)} 个页面文档。")

    # Step 2: 索引建库
    indexer = ChunkIndexer(collection_name="company_policy", dimension=1536)
    await indexer.ingest_and_index(pages)

    # Step 3: 启动 Bot 问答交互
    bot = CitationRAGBot(indexer, similarity_threshold=0.4)
    
    # 检查是否为非交互测试模式
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        print("\n🚀 [非交互测试模式] 正在自动运行测试提问...")
        test_queries = [
            "请问公司年假有几天？当年没休完会怎么样？",
            "正式员工出差住宿费一天可以报销多少钱？"
        ]
        
        for query in test_queries:
            print(f"\n🙋 自动提问: '{query}'")
            async for packet in bot.answer_stream(query):
                ptype = packet["type"]
                if ptype == "status":
                    sys.stdout.write(f"\033[90m[{packet['content']}]\033[0m\n")
                    sys.stdout.flush()
                elif ptype == "delta":
                    sys.stdout.write(packet["content"])
                    sys.stdout.flush()
                elif ptype == "final":
                    print("\n")
                    citations = packet["citations"]
                    if citations:
                        print("\033[33m" + "="*25 + " 📄 原始文献溯源审计表 " + "="*25 + "\033[0m")
                        for idx, cite in enumerate(citations, start=1):
                            print(f" \033[1m[{idx}] [{cite['doc_id']}:{cite['page']}]\033[0m")
                            print(f"   - 来源文献: \033[4m{cite['source_file']}\033[0m")
                            print(f"   - 原始段落: \033[32m{cite['content']}\033[0m")
                            print("-" * 72)
                        print("\033[33m" + "="*72 + "\033[0m")
                    else:
                        print("\033[90m[本次生成未包含有效引用来源]\033[0m")
    else:
        await run_interactive_repl(bot)


if __name__ == "__main__":
    asyncio.run(main())
