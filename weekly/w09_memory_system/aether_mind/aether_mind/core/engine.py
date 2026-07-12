"""
AetherMind Master Assembly Engine
=================================

设计方案:
---------
本模块实现系统的核心装配层 `MemoryAgentEngine`。
遵循“无状态积木墙”设计原则，主引擎自身不承担具体的路由分发或记忆消解算法，
而是作为各微引擎（数据库适配器、向量库适配器、意图路由器、工作记忆滑窗、长期记忆事实管理器、高级 RAG 协调器及 ReAct 规划器）
的装配体和生命周期协调中心。

核心数据流 ( handle_message_stream ):
-----------------------------------
1. 初始化协程安全的请求 Trace 日志容器。
2. 检索关系型数据库，建立/加载会话，进行语义缓存匹配（Semantic Cache Match）。
3. 调度意图路由器预测分流路径（NONE, MEM, RAG, MEM+RAG, TOOL, PLAN）。
4. 根据路由分流，并行执行长短期记忆召回与 RAG + GraphRAG 检索。
5. 调度 ContextBuilder 进行 Prompt 组装与 Token 防爆裁剪。
6. 发起 LLM 推理，以 SSE 流式 yield 传回 Token 与 Trace 事件。
7. 后台启动非阻塞异步任务（create_task）：
   - 执行增量事实提取（FactExtractor）。
   - 执行事实去重与冲突消歧（MemoryConsolidator）。
   - 执行艾宾浩斯时间遗忘衰减。
   - 物理更新工作记忆滑窗摘要。

结构说明:
---------
- MemoryAgentEngine: 主协调装配引擎。
"""

import time
import asyncio
from typing import List, Dict, Any, AsyncGenerator
from aether_mind.storage.base import SQLStore, VectorStore
from aether_mind.utils.client import AetherMindLLMClient
from aether_mind.utils.logging import TraceContext, logger
from aether_mind.core.router import MemoryRouter
from aether_mind.core.planner import AgentExecutor
from aether_mind.core.context import ContextBuilder
from aether_mind.memory.buffer import BufferMemoryManager
from aether_mind.memory.long import LongMemoryManager
from aether_mind.memory.consolidator import MemoryConsolidator
from aether_mind.rag.engine import RAGEngine
from aether_mind.core.semantic_cache import SemanticCacheEngine
from aether_mind.config import settings


class MemoryAgentEngine:
    """
    AetherMind 核心装配层与生命周期调度器。
    """

    def __init__(self, db: SQLStore, vector_store: VectorStore):
        """
        初始化装配引擎。

        Args:
            db (SQLStore): 关系型数据库存储适配器（SQLite/Postgres）。
            vector_store (VectorStore): 向量数据库适配器（Qdrant）。
        """
        self.db = db
        self.vector_store = vector_store
        
        # 初始化微引擎组件
        self.client = AetherMindLLMClient()
        self.router = MemoryRouter(self.client)
        self.buffer_manager = BufferMemoryManager(token_limit=settings.token_limit)
        self.long_memory = LongMemoryManager(self.client)
        self.consolidator = MemoryConsolidator(self.client, decay_rate=settings.memory_decay_rate)
        self.rag_engine = RAGEngine(self.client)
        self.planner = AgentExecutor(self.client)
        self.context_builder = ContextBuilder(char_budget=4000)
        # 生产级三层语义缓存微引擎（L1 哈希 + L2 Qdrant ANN + L3 LLM 兜底）
        self.semantic_cache = SemanticCacheEngine(self.client, self.vector_store)

    async def initialize(self) -> None:
        """
        物理建立数据库表结构，并从 Qdrant 反向重建 Corpus 和 GraphRAG 网络社区。
        """
        logger.info("[引擎启动] 开始初始化存储表结构...")
        # 1. 物理创建 SQLite / PostgreSQL 关系表
        await self.db.init_db()
        
        # 2. 物理创建 Qdrant 向量集合
        await self.vector_store.init_collections()
        
        # 3. 从向量数据库中加载已有 Chunks 重建 GraphRAG 和 BM25
        await self.rag_engine.reload_corpus_from_store(self.vector_store)
        # 4. 初始化语义缓存专用 Qdrant Collection
        await self.semantic_cache.init_collection()
        logger.info("[引擎启动] 存储层与微引擎群初始化成功。")

    async def handle_message_stream(
        self,
        session_id: str,
        user_id: str,
        query: str
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        处理单次会话请求，流式下发 SSE 事件（Token 字符与 Trace Span 日志）。

        Args:
            session_id (str): 会话唯一 ID。
            user_id (str): 租户用户 ID。
            query (str): 用户输入问题。

        Yields:
            AsyncGenerator[Dict[str, Any], None]: SSE 结构化输出流。
        """
        # 0. 初始化协程安全的请求 Trace 日志追踪上下文
        TraceContext.new_trace()
        start_time = time.time()

        yield {
            "type": "trace",
            "step": "router",
            "content": f"收到会话请求。Session ID: {session_id}, User ID: {user_id}"
        }

        # 1. 物理创建/重载 Session 与 User
        await self.db.create_session(session_id, user_id)

        # 2. 生产级三层语义缓存查询（L1 哈希 → L2 Qdrant ANN → L3 LLM 兜底）
        # 按 user_id 维度做缓存，跨 Session 可复用同一用户的历史缓存条目。
        cache_result = await self.semantic_cache.get(user_id, query)

        if cache_result is not None:
            cache_hit_text, hit_level = cache_result
            logger.info(f"[语义缓存命中] {hit_level} | user={user_id} query='{query[:30]}...'")
            yield {
                "type": "trace",
                "step": "cache",
                "content": f"【{hit_level}】命中语义缓存，直接流式回显（跳过 LLM 推理）。"
            }
            # 分块流式回显缓存内容（模拟流式感知）
            chunk_size = 10
            for i in range(0, len(cache_hit_text), chunk_size):
                await asyncio.sleep(0.01)
                yield {
                    "type": "token",
                    "content": cache_hit_text[i:i + chunk_size]
                }
            yield {"type": "done", "total_tokens": 0, "duration_ms": int((time.time() - start_time) * 1000)}
            return

        # 3. 意图分流路由器决策
        route = await self.router.route(query)
        yield {
            "type": "trace",
            "step": "router",
            "content": f"意图路由器决策路线为: {route}"
        }

        # 4. 如果是复杂的 PLAN / TOOL 路由，直接分发给 ReAct 规划器，流式代管输出
        if route in ("PLAN", "TOOL"):
            # RAG 检索打底（作为规划器的上下文输入）
            # 定义 trace 回调，将子步骤事件实时 yield 到 SSE 流
            async def _plan_trace(step, content, duration_ms=0):
                pass  # PLAN 路由不需要实时 trace（规划器自己会 yield）

            vector_chunks, graph_context = await self.rag_engine.retrieve(
                query, self.vector_store, on_trace=_plan_trace
            )
            context_parts = []
            for c in vector_chunks:
                text = c["payload"].get("text", "")
                source = c["payload"].get("source", "未知来源")
                context_parts.append(f"[文档切片 (来源: {source})]:\n{text}")
            context_text = "\n\n".join(context_parts)
            if graph_context:
                context_text += f"\n\n[GraphRAG 关联知识]\n{graph_context}"

            final_reply_chunks = []
            async for sse_event in self.planner.execute(query, context_text, session_id):
                yield sse_event
                if sse_event["type"] == "token":
                    final_reply_chunks.append(sse_event["content"])

            final_reply = "".join(final_reply_chunks)

        else:
            # 5. 如果是 NONE / MEM / RAG / MEM+RAG
            # 5.1 并行召回长期记忆与 RAG 背景知识
            memories_list = []
            rag_chunks = []
            graph_context = ""

            retrieval_tasks = []

            # 决定是否检索长期记忆（MEM 路径，直接 await 即可，无 trace 需求）
            mem_task = None
            if route in ("MEM", "MEM+RAG"):
                async def _get_mem():
                    m_hits = await self.long_memory.retrieve_relevant_facts(user_id, query, self.vector_store)
                    return [h["payload"]["fact"] for h in m_hits]
                mem_task = asyncio.ensure_future(_get_mem())

            # RAG 路径：用 asyncio.Queue 桥接 on_trace 回调，实现逐步实时 yield
            rag_task = None
            if route in ("RAG", "MEM+RAG"):
                _trace_q: asyncio.Queue = asyncio.Queue()

                async def _rag_trace(step: str, content: str, duration_ms: int = 0):
                    await _trace_q.put({"type": "trace", "step": step, "content": content, "duration_ms": duration_ms})

                async def _get_rag():
                    v_hits, g_res = await self.rag_engine.retrieve(
                        query, self.vector_store, on_trace=_rag_trace
                    )
                    await _trace_q.put(None)  # 发送哨兵值，通知消费者结束
                    return [c["payload"] for c in v_hits], g_res

                rag_task = asyncio.ensure_future(_get_rag())

                # 实时消费 trace 队列，逐步 yield 给 SSE 流（直到哨兵 None 为止）
                while True:
                    event = await _trace_q.get()
                    if event is None:
                        break
                    yield event

            # 等待所有检索任务完成，分配结果
            if mem_task is not None:
                memories_list = await mem_task
            if rag_task is not None:
                rag_chunks, graph_context = await rag_task

            # 5.2 载入工作记忆最近的对话消息和累积背景摘要
            active_history = await self.buffer_manager.load_messages(session_id, self.db)
            session_summary = await self.db.get_session_summary(session_id) or ""

            # 5.3 调度 ContextBuilder 进行 Prompt 拼装与 Token 预算裁剪
            prompt_messages = self.context_builder.assemble(
                query=query,
                long_term_memories=memories_list,
                rag_chunks=rag_chunks,
                graph_rag_context=graph_context,
                session_summary=session_summary,
                active_history=active_history
            )

            # 5.4 发起 LLM 推理并流式 yield 回传 token
            final_reply_chunks = []
            async for token in self.client.request_llm_stream(prompt_messages, temperature=0.2, max_tokens=4096):
                yield {
                    "type": "token",
                    "content": token
                }
                final_reply_chunks.append(token)
            
            final_reply = "".join(final_reply_chunks)

        # 6. 保存短期活跃对话记录（自动触发 Buffer 滑窗和摘要压缩）
        # 注意：先写 user 消息，再写 assistant 回复。写入回复时会物理检查 Token 并可能在后台压缩
        await self.buffer_manager.append(session_id, "user", query, self.db, self.client)
        await self.buffer_manager.append(session_id, "assistant", final_reply, self.db, self.client)

        # 7. 后台启动非阻塞异步任务（长期记忆抽取、消歧冲突及时间衰减）
        # 把最新的一轮对话组成段落送给抽取器
        latest_dialogue_block = f"用户: {query}\n助理: {final_reply}"
        
        async def _background_long_memory_jobs():
            try:
                # 7.1 增量事实抽取
                new_facts = await self.long_memory.extract_facts(latest_dialogue_block)
                # 7.2 事实去重与冲突消歧
                for fact in new_facts:
                    await self.consolidator.consolidate_fact(
                        user_id=user_id,
                        new_fact_key=fact.fact_key,
                        new_fact_value=fact.fact_value,
                        db=self.db,
                        vector_store=self.vector_store
                    )
                # 7.3 艾宾浩斯时间衰减（每个请求后对用户的所有 Facts 进行一次时间折损计算）
                await self.consolidator.apply_ebbinghaus_decay(
                    user_id=user_id,
                    db=self.db,
                    vector_store=self.vector_store
                )
            except Exception as ex:
                logger.error(f"[后台长期记忆维护异常] {str(ex)}")

        # 挂载后台任务
        asyncio.create_task(_background_long_memory_jobs())

        # 8. 审计保存最终答案的 Trace 日志（用于可观测性），
        #    并后台非阻塞双写语义缓存 L1 + L2（不阻塞当前响应流）
        total_duration = int((time.time() - start_time) * 1000)
        await self.db.save_trace_log(
            session_id=session_id,
            step_name="final_answer",
            duration_ms=total_duration,
            input_data=query,
            output_data=final_reply
        )
        # 后台双写语义缓存（create_task 非阻塞，不增加用户响应延迟）
        asyncio.create_task(self.semantic_cache.put(user_id, query, final_reply))

        # 9. 下发 Done 结束事件
        yield {
            "type": "done",
            "total_tokens": len(final_reply) // 2, # 粗略估计
            "duration_ms": total_duration
        }
