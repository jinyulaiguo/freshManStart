"""
File: reasoning_engine.py
Description: Day 56 综合实战：跨小说章节的高级逻辑推理分析器主引擎。

设计方案：
1. 设计意图：
   整合多路检索、假设文档对齐、重排序过滤、知识三元组关系抽取以及图拓扑结构进行综合推理。
   提供统一的流程控制与执行结果结构化返回，用作可视化前端的数据源。

2. 核心结构：
   - `ReasoningEngine`: 主调度类。
     - `execute(query: str) -> AsyncGenerator[Dict[str, Any], None]`: 
       使用异步生成器逐步产出每一步的结果，支持 SSE 流式推送到前端。
   - `StepResult`: 约定每一步输出的数据契约格式。
   
3. 关键数据流向：
   用户 Query ──► Step 1 (Multi-Query) ──► 变体 Query + 粗筛 Chunks (SHA-256去重)
               ├──► Step 2 (HyDE) ──► 假设回答 + 假设检索 Chunks
               ▼ (合并 Chunks)
   合并后的 50 个 Chunks ──► Step 3 (Rerank) ──► 重新打分的 Top-10 Chunks
                                            ──► Step 4 (KG三元组建模) ──► 内存图拓扑结构
                                            ▼ (拼装上下文 + 图谱关系)
                                  Step 5 (推理报告) ──► 最终结论与推理路径
"""

import asyncio
import time
import hashlib
from typing import List, Dict, Any, Tuple, AsyncGenerator
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct

from weekly.w04_prompt_and_http.utils import LLMClient
from weekly.w06_embedding_and_vector_db.utils import EmbeddingClient
from weekly.w08_advanced_retrieval_and_graph.day50.query_rewriter import QueryRewriter, MultiQueryRetriever
from weekly.w08_advanced_retrieval_and_graph.day51.rerank_handler import APILightweightReranker
from weekly.w08_advanced_retrieval_and_graph.day52.hyde_pipeline import HyDEPipeline
from weekly.w08_advanced_retrieval_and_graph.day53.kg_extractor import KGExtractor, MemoryGraph

# 测试小说语料数据
MOCK_NOVEL_CHUNKS = [
    "第一章：江城是一个山明水秀的江南小城。李四是江城警局的刑侦队长，他为人正直深得民心。在警局里，李四有一个非常器重的贴身助手叫张三，两人合作多年，关系极好，目前正联手侦办一桩离奇的黄金失窃案。",
    "第一章续：李队长每天办案辛劳，他的贤内助王五在江城一所大学里教历史，每天过着深居简出的平静生活。王五经常为李四熬夜准备热茶，是公认的模范夫妻。",
    "第二章：夜幕降临，江城大酒店的某个包房里，助手张三悄悄推门而入。包房内坐着的正是被警局通缉的神秘幕后反派赵六。平日深得李队长信任的这个警员，竟然一直是赵六安插的内鬼。",
    "第二章续：反派赵六递过去一箱现金，冷酷地指示张警员必须在三天内将警局机密卷宗偷出，否则交易作废。张三默默收下现金，点头答应，背叛了李队长。"
]

class ReasoningEngine:
    """综合推理引擎：串联多路检索、HyDE、Rerank、知识图谱提取和最终生成报告"""

    def __init__(self, collection_name: str = "day56_novel_kb"):
        """初始化推理引擎及其内部所有的微引擎组件"""
        self.collection_name = collection_name
        self.llm_client = LLMClient()
        self.embedding_client = EmbeddingClient()
        self.qdrant_client = QdrantClient(location=":memory:") # 本地内存向量数据库
        
        # 初始化微引擎
        self.query_rewriter = QueryRewriter(self.llm_client)
        self.mq_retriever = MultiQueryRetriever(
            self.qdrant_client, self.embedding_client, self.query_rewriter, self.collection_name
        )
        self.reranker = APILightweightReranker(self.llm_client)
        self.hyde_pipeline = HyDEPipeline(
            self.qdrant_client, self.embedding_client, self.llm_client, self.collection_name
        )
        self.kg_extractor = KGExtractor(self.llm_client)

    async def initialize_database(self):
        """初始化内存向量数据库，注入小说分段"""
        print("-> 正在初始化内存向量数据库，注入小说切片...")
        self.qdrant_client.recreate_collection(
            collection_name=self.collection_name,
            vectors_config=VectorParams(size=1536, distance=Distance.COSINE)
        )
        # 并发计算 Embedding 并批量 Upsert
        vectors = await self.embedding_client.embed_texts(MOCK_NOVEL_CHUNKS, embed_type="db")
        points = [
            PointStruct(
                id=idx,
                vector=vector,
                payload={"text": doc, "hash": hashlib.sha256(doc.encode("utf-8")).hexdigest()}
            )
            for idx, (doc, vector) in enumerate(zip(MOCK_NOVEL_CHUNKS, vectors))
        ]
        self.qdrant_client.upsert(collection_name=self.collection_name, points=points)
        print("-> 向量数据库注入小说切片成功！")

    async def execute_reasoning(self, query: str) -> AsyncGenerator[Dict[str, Any], None]:
        """流式执行高级逻辑推理，逐步 yield 每一阶段的结果数据给前端展示"""
        
        # ==========================================
        # STEP 1: Multi-Query 变形与检索 (Day 50)
        # ==========================================
        start_time = time.time()
        print(f"\n[Step 1] 启动 Multi-Query 检索. Query: {query}")
        
        try:
            # 检索 top_k=3
            mq_results, mq_meta = await self.mq_retriever.retrieve(query, top_k=3)
            mq_duration = time.time() - start_time
            
            step1_data = {
                "step": 1,
                "status": "success",
                "duration": round(mq_duration, 2),
                "data": {
                    "rewritten_queries": mq_meta["rewritten_queries"],
                    "raw_count": mq_meta["raw_count"],
                    "deduped_count": mq_meta["deduped_count"],
                    "chunks": mq_results
                }
            }
        except Exception as e:
            step1_data = {
                "step": 1,
                "status": "error",
                "error": str(e),
                "data": {"rewritten_queries": [query], "raw_count": 0, "deduped_count": 0, "chunks": []}
            }
        yield step1_data

        # ==========================================
        # STEP 2: HyDE 假设性文档生成与检索 (Day 52)
        # ==========================================
        start_time = time.time()
        print(f"\n[Step 2] 启动 HyDE 假设性检索...")
        
        try:
            hyde_results, hypo_doc = await self.hyde_pipeline.retrieve_with_hyde(query, top_k=3)
            hyde_duration = time.time() - start_time
            
            step2_data = {
                "step": 2,
                "status": "success",
                "duration": round(hyde_duration, 2),
                "data": {
                    "hypothetical_document": hypo_doc,
                    "chunks": hyde_results
                }
            }
        except Exception as e:
            step2_data = {
                "step": 2,
                "status": "error",
                "error": str(e),
                "data": {"hypothetical_document": "", "chunks": []}
            }
        yield step2_data

        # ==========================================
        # 合并粗筛 Chunks
        # ==========================================
        # 将 Multi-Query 召回与 HyDE 召回的文档进行合并并去重
        coarse_chunks_dict = {}
        # 1. 注入 Multi-Query 召回
        for item in step1_data["data"]["chunks"]:
            txt = item["text"]
            h = hashlib.sha256(txt.encode("utf-8")).hexdigest()
            coarse_chunks_dict[h] = {"text": txt, "score": item["score"]}
            
        # 2. 注入 HyDE 召回
        for item in step2_data["data"]["chunks"]:
            txt = item["text"]
            h = hashlib.sha256(txt.encode("utf-8")).hexdigest()
            # 如果已存在，取最高得分
            if h in coarse_chunks_dict:
                if item["score"] > coarse_chunks_dict[h]["score"]:
                    coarse_chunks_dict[h]["score"] = item["score"]
            else:
                coarse_chunks_dict[h] = {"text": txt, "score": item["score"]}
                
        coarse_chunks = [{"text": v["text"], "score": v["score"]} for v in coarse_chunks_dict.values()]

        # ==========================================
        # STEP 3: API Rerank 重新打分与过滤 (Day 51)
        # ==========================================
        start_time = time.time()
        print(f"\n[Step 3] 启动 Reranker 对 {len(coarse_chunks)} 个 Chunks 进行重排序...")
        
        try:
            # 设定相关性过滤阈值为 0.3
            reranked_results = await self.reranker.rerank(query, coarse_chunks, threshold=0.3)
            rerank_duration = time.time() - start_time
            
            # 记录打分对比，用于前端图表显示
            score_comparison = []
            for item in coarse_chunks:
                # 寻找 rerank 后的分数，如果低于 0.3 被过滤了，分数设置为 0.0
                new_score = 0.0
                for r_item in reranked_results:
                    if r_item["text"] == item["text"]:
                        new_score = r_item["score"]
                        break
                score_comparison.append({
                    "text_preview": item["text"][:30] + "...",
                    "old_score": item["score"],
                    "new_score": new_score
                })

            step3_data = {
                "step": 3,
                "status": "success",
                "duration": round(rerank_duration, 2),
                "data": {
                    "chunks": reranked_results,
                    "score_comparison": score_comparison,
                    "filtered_count": len(coarse_chunks) - len(reranked_results)
                }
            }
        except Exception as e:
            step3_data = {
                "step": 3,
                "status": "error",
                "error": str(e),
                "data": {"chunks": coarse_chunks[:5], "score_comparison": [], "filtered_count": 0}
            }
        yield step3_data

        # ==========================================
        # STEP 4: 知识三元组提取与拓扑构建 (Day 53)
        # ==========================================
        start_time = time.time()
        print(f"\n[Step 4] 启动知识三元组提取...")
        
        try:
            # 只取 Rerank 后的 Top-5 文本段提取三元组，降低 token 开销
            top_chunks = step3_data["data"]["chunks"][:5]
            combined_text = "\n".join([c["text"] for c in top_chunks])
            
            triples = await self.kg_extractor.extract_triples(combined_text)
            kg_duration = time.time() - start_time
            
            # 构建内存图并展示连通状态
            graph = MemoryGraph()
            for t in triples:
                graph.add_triple(
                    s=t["subject"], p=t["predicate"], o=t["object"],
                    s_label=t["subject_label"], o_label=t["object_label"]
                )
                
            nodes_list = [{"id": name, "label": lbl} for name, lbl in graph.nodes.items()]
            edges_list = []
            for s, rels in graph.adj_list.items():
                for p, objects in rels.items():
                    for o in objects:
                        edges_list.append({"source": s, "target": o, "relation": p})

            step4_data = {
                "step": 4,
                "status": "success",
                "duration": round(kg_duration, 2),
                "data": {
                    "triples": triples,
                    "nodes": nodes_list,
                    "edges": edges_list
                }
            }
        except Exception as e:
            step4_data = {
                "step": 4,
                "status": "error",
                "error": str(e),
                "data": {"triples": [], "nodes": [], "edges": []}
            }
        yield step4_data

        # ==========================================
        # STEP 5: 拼装上下文推理生成最终报告 (Day 55 框架整合)
        # ==========================================
        start_time = time.time()
        print(f"\n[Step 5] 启动最终推理报告生成...")
        
        try:
            # 拼装上下文：重排后的最佳 Chunks + 提取出的知识图谱三元组关系
            ctx_chunks = "\n".join([f"- {c['text']}" for c in step3_data["data"]["chunks"][:5]])
            ctx_triples = "\n".join([f"- ({t['subject']}) ──[{t['predicate']}]──► ({t['object']})" for t in step4_data["data"]["triples"]])
            
            prompt_messages = [
                {
                    "role": "system",
                    "content": (
                        "你是一个极具严密逻辑推理能力的 AI 小说案件研究助手。\n"
                        "你需要结合给定的上下文线索片段（文本事实）和从中提取出的知识实体拓扑三元组关系，对用户提出的推理问题进行深度剖析，输出最终的推理报告。\n"
                        "要求：\n"
                        "1. 推理报告必须包含：核心结论（直接回答问题）、关联实体分析（按图谱连通关系梳理）、详细推理路径（从第一章到第二章的关系演进剖析）。\n"
                        "2. 语言表达必须严谨、客观，直接根据证据陈述，不要废话和修饰。\n"
                        "3. 将报告结构化，使用 Markdown 格式。"
                    )
                },
                {
                    "role": "user",
                    "content": (
                        f"用户推理提问：{query}\n\n"
                        f"【上下文小说事实片段】：\n{ctx_chunks}\n\n"
                        f"【知识图谱关系网络三元组】：\n{ctx_triples}\n\n"
                        f"请给出详细推理报告及推理路径："
                    )
                }
            ]
            
            report = await self.llm_client.request_llm(
                messages=prompt_messages,
                temperature=0.2,
                max_tokens=1000
            )
            
            # 清洗大模型可能自带的思维链
            import re
            if "<think>" in report:
                report = re.sub(r"<think>.*?</think>", "", report, flags=re.DOTALL)
                
            report_duration = time.time() - start_time
            
            step5_data = {
                "step": 5,
                "status": "success",
                "duration": round(report_duration, 2),
                "data": {
                    "report": report.strip()
                }
            }
        except Exception as e:
            step5_data = {
                "step": 5,
                "status": "error",
                "error": str(e),
                "data": {"report": f"报告生成发生异常错误: {e}"}
            }
        yield step5_data
