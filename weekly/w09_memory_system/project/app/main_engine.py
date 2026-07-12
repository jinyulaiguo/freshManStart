"""
Main Assembly Agent Engine Module.

设计方案说明：
1. **设计意图**：
   本模块实现记忆增强 Agent 的核心主装配引擎（MemoryAgentEngine）。
   践行“自底向上”的积木拼装架构，主引擎作为一个干净的生命周期协调器，
   只负责调度与串联各个功能单一的微引擎（Router, BufferManager, Extractor, Consolidator, RAGEngine），
   不涉及任何具体的路由判定或消歧去重细节。
2. **交互处理核心流 (handle_message)**：
   - 步骤 1: 建立 Session 并触发状态热重构（若内存为空则自动加载 SQLite 介质）。
   - 步骤 2: 自适应路由决策。
   - 步骤 3: 多路检索拉取（MEM -> 长期偏好, RAG -> 客观文档, NONE -> 短路跳过）。
   - 步骤 4: 组装上下文，大模型异步推理，获得回复并保存。
   - 步骤 5: 派发非阻塞后台任务（异步事实提取、冲突消歧与时间遗忘衰减），直接将结果返回用户，保障极低首字时延体验。
"""

import sys
import os
import time
import asyncio
from typing import List, Dict, Any, Tuple, Optional

# 确保导入 config
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from config import get_llm_client
from db import PersistenceStore
from memory_router import MemoryRouter
from buffer_memory_manager import BufferMemoryManager
from fact_extractor import FactExtractor, FactItem as ExtractedFactItem
from memory_consolidator import MemoryConsolidator, FactItem as ConsolidatorFactItem
from rag_engine import RAGEngine
from weekly.w04_prompt_and_http.utils import LLMClient

class MemoryAgentEngine:
    """多层级高可用记忆增强 Agent 主装配引擎。"""

    def __init__(self, db_path: str = "agent_memory.db", token_limit: int = 1500, client: Optional[LLMClient] = None):
        """初始化主引擎，并实例化所有子微引擎组件。

        Args:
            db_path: SQLite 物理存储文件路径。
            token_limit: 短期记忆字符长度超限阈值。
            client: 真实大模型请求客户端。
        """
        self.client = client or get_llm_client()
        self.store = PersistenceStore(db_path=db_path)
        
        # 实例化微引擎
        self.router = MemoryRouter(client=self.client)
        self.buffer_manager = BufferMemoryManager(token_limit=token_limit, client=self.client)
        self.extractor = FactExtractor(client=self.client)
        self.consolidator = MemoryConsolidator(client=self.client)
        
        # 捕获 RAG 引擎可能出现的依赖报错
        try:
            self.rag_engine = RAGEngine()
        except Exception as e:
            print(f"⚠️ [主引擎] 实例化本地 RAG 引擎失败，将使用 Mock 降级检索。错误: {e}")
            self.rag_engine = None
            
        # 审计日志列表，用于在 Dashboard 实时拉取展示后台任务细节
        self.audit_logs: List[Dict[str, Any]] = []

    def log_audit(self, level: str, message: str) -> None:
        """记录一条审计日志，附带精确时戳。

        Args:
            level: 日志级别 (INFO, WARNING, ERROR, SUCCESS)。
            message: 日志消息文本。
        """
        log_entry = {
            "timestamp": time.time(),
            "level": level.upper(),
            "message": message
        }
        self.audit_logs.append(log_entry)
        # 限制审计日志总长度，防止内存无限累加
        if len(self.audit_logs) > 500:
            self.audit_logs.pop(0)
        print(f"[{level.upper()}] {message}")

    async def handle_message(self, session_id: str, user_id: str, query: str) -> Dict[str, Any]:
        """处理一轮用户的交互提问，进行自适应分流、上下文组装、大模型推理及后台非阻塞异步记忆沉淀。

        Args:
            session_id: 会话唯一标识符。
            user_id: 租户唯一标识符。
            query: 用户提问。

        Returns:
            包含回复、路由决策、检索开销及召回 payload 的结果字典。
        """
        start_time = time.time()
        
        # 1. 物理层 Session 初始化
        await self.store.init_db()
        await self.store.create_session(session_id, user_id)
        
        # 2. 状态热重构判定（若内存活跃消息及摘要为空，说明是进程冷启动，物理重塑之）
        if not self.buffer_manager.messages and not self.buffer_manager.current_summary:
            self.log_audit("info", f"检测到 Session '{session_id}' 状态未载入，执行断电状态重构...")
            await self.buffer_manager.load_state(self.store, session_id)
            
        # 3. 意图路由分类判定
        self.log_audit("info", f"收到 Query: \"{query}\" (Session: {session_id}, User: {user_id})")
        route_decision = await self.router.route(query)
        self.log_audit("info", f"自适应路由器决策分支 -> [{route_decision}]")
        
        rtt_ms = 0
        retrieval_payload = []
        retrieval_start = time.time()
        
        # 4. 根据路由分流执行检索召回
        if route_decision == "MEM":
            # 长期偏好检索：拉取该用户的所有 Facts 偏好
            user_facts = await self.store.load_user_memories(user_id)
            # 根据关键字进行分词过滤，匹配与 query 相关的偏好
            matched_facts = []
            for k, v in user_facts.items():
                words = k.lower().split("_")
                if any(w in query.lower() and len(w) > 3 for w in words):
                    matched_facts.append(f"{k}: {v}")
            
            rtt_ms = int((time.time() - retrieval_start) * 1000)
            retrieval_payload = matched_facts
            self.log_audit("success", f"MEM 长期记忆召回成功。召回偏好: {matched_facts} (I/O 耗时: {rtt_ms}ms)")
            
        elif route_decision == "RAG":
            # 外部客观知识库检索
            if self.rag_engine:
                matched_docs = self.rag_engine.retrieve(query, limit=2)
            else:
                matched_docs = ["Mock: 微软 GraphRAG 框架通过 Leiden 社区检测构建全局知识图谱索引。"]
                
            rtt_ms = int((time.time() - retrieval_start) * 1000)
            retrieval_payload = matched_docs
            self.log_audit("success", f"RAG 专业客观知识召回成功。召回文档: {matched_docs} (I/O 耗时: {rtt_ms}ms)")
            
        else:
            # NONE 分支，短路跳过 I/O 检索，极大降低首字延迟
            rtt_ms = 0
            retrieval_payload = []
            self.log_audit("info", "NONE 短路分支，不执行任何数据库与向量检索。时延: 0ms")

        # 5. 上下文组装 (Context Assembler)
        # A. 拉取短期活跃消息 (包含 System 级别摘要头部)
        messages = self.buffer_manager.get_messages()
        
        # B. 组装检索召回 Payload 为临时的 System Prompt 附加信息
        retrieval_prompt = ""
        if route_decision == "MEM" and retrieval_payload:
            retrieval_prompt = "【已知的关于用户的背景偏好（来自长期记忆）】:\n" + "\n".join(f"- {item}" for item in retrieval_payload)
        elif route_decision == "RAG" and retrieval_payload:
            retrieval_prompt = "【从专业技术知识库中检索到的背景知识】:\n" + "\n".join(f"- {item}" for item in retrieval_payload)
            
        if retrieval_prompt:
            messages.append({
                "role": "system",
                "content": f"系统辅助上下文背景信息：\n{retrieval_prompt}\n\n请结合上述背景，并作为当前回答的参考，直接回答用户的提问。"
            })
            
        # C. 放入用户的当前提问
        messages.append({"role": "user", "content": query})
        
        # 6. 大模型推理生成回复
        self.log_audit("info", "发起大模型推理以生成 Assistant 回复...")
        reply = await self.client.request_llm(messages, temperature=0.7)
        self.log_audit("success", "回复生成成功。")
        
        # 7. 对话记录物理持久化
        # A. 物理写入 SQLite 数据库
        await self.store.save_message(session_id, "user", query)
        await self.store.save_message(session_id, "assistant", reply)
        
        # B. 同步追加至短期记忆滑窗，并在需要时触发后台异步摘要
        self.buffer_manager.append({"role": "user", "content": query}, self.store, session_id)
        self.buffer_manager.append({"role": "assistant", "content": reply}, self.store, session_id)
        
        # 8. 派发非阻塞后台异步记忆沉淀与衰减任务
        # 我们不阻塞主流程，直接在这里 create_task，让前台快速返回，达到极致时效
        asyncio.create_task(self._async_background_process(session_id, user_id, query, reply))
        
        total_time_ms = int((time.time() - start_time) * 1000)
        return {
            "reply": reply,
            "route": route_decision,
            "rtt_ms": rtt_ms,
            "payload": retrieval_payload,
            "total_time_ms": total_time_ms
        }

    async def _async_background_process(self, session_id: str, user_id: str, query: str, reply: str) -> None:
        """后台非阻塞异步线程：执行 Facts 增量式提取、时序冲突消歧合并及艾宾浩斯时间衰减。

        Args:
            session_id: 会话唯一标识符。
            user_id: 租户唯一标识符。
            query: 最新用户提问。
            reply: 最新 Assistant 回复。
        """
        # 构造临时的单轮对话上下文，让 extractor 仅针对当前这轮对话提取，实现“增量式事实沉淀”
        current_dialogue = [
            {"role": "user", "content": query},
            {"role": "assistant", "content": reply}
        ]
        
        self.log_audit("info", "后台任务：开始对本轮交互执行原子 Facts 提取...")
        extracted_facts = await self.extractor.extract_facts(current_dialogue)
        
        if not extracted_facts:
            self.log_audit("info", "后台任务：本轮交互未检测到有价值的原子事实陈述。")
        else:
            self.log_audit("info", f"后台任务：成功增量提取出 {len(extracted_facts)} 条原子事实偏好。")
            
            # 步骤 1: 遍历提取出的每个事实，逐一与数据库现有事实做冲突消歧
            for new_fact in extracted_facts:
                # 从 SQLite 加载该用户当前的全部 Facts 项
                raw_memories = await self.store.load_all_memory_items(user_id)
                existing_items = [
                    ConsolidatorFactItem(
                        fact_key=m["fact_key"],
                        fact_value=m["fact_value"],
                        timestamp=m["timestamp"],
                        weight=m["weight"]
                    ) for m in raw_memories
                ]
                
                # 转换新提取事实的实体格式
                new_item = ConsolidatorFactItem(
                    fact_key=new_fact.fact_key,
                    fact_value=new_fact.fact_value,
                    timestamp=time.time(),
                    weight=1.0
                )
                
                self.log_audit("info", f"后台任务：将新事实 [{new_item.fact_key} -> {new_item.fact_value}] 进行消歧判定...")
                
                # 调用冲突消解微引擎进行判定
                consolidated_list, deleted_keys = await self.consolidator.consolidate_facts(existing_items, new_item)
                
                # 物理删除被擦除的旧冲突 Facts
                for del_key in deleted_keys:
                    await self.store.delete_fact(user_id, del_key)
                    self.log_audit("warning", f"后台任务：已物理擦除数据库中的旧冲突事实，键名: '{del_key}'")
                
                # 将合并消歧后的最终 Fact 保存或原地覆盖到数据库
                await self.store.save_fact(
                    user_id=user_id,
                    fact_key=new_item.fact_key,
                    fact_value=new_item.fact_value,
                    weight=new_item.weight,
                    timestamp=new_item.timestamp
                )
                self.log_audit("success", f"后台任务：原子事实存盘成功 -> [{new_item.fact_key} : {new_item.fact_value}]")

        # 步骤 2: 物理执行艾宾浩斯时间遗忘衰减与淘汰
        self.log_audit("info", "后台任务：触发艾宾浩斯遗忘曲线折算...")
        
        # 重新拉取所有事实
        raw_memories = await self.store.load_all_memory_items(user_id)
        existing_items = [
            ConsolidatorFactItem(
                fact_key=m["fact_key"],
                fact_value=m["fact_value"],
                timestamp=m["timestamp"],
                weight=m["weight"]
            ) for m in raw_memories
        ]
        
        # 重新折算权重
        current_time = time.time()
        # 这里为了演示效果，衰减速率设为 0.002
        active_items, decayed_keys = self.consolidator.apply_time_decay(
            existing_items,
            current_time=current_time,
            decay_rate=0.002,
            threshold=0.2
        )
        
        # 物理批量更新活跃事实在数据库中的留存权重
        weights_map = {item.fact_key: item.weight for item in active_items}
        await self.store.update_memories_weights(user_id, weights_map)
        
        # 从数据库物理淘汰衰减值低于 0.2 的冷记忆
        if decayed_keys:
            await self.store.clear_decayed_memories(user_id, threshold=0.2)
            for k in decayed_keys:
                self.log_audit("warning", f"后台任务：事实 [{k}] 衰减权重低于 0.2，已被物理遗忘淘汰。")
                
        self.log_audit("success", "后台任务：长期事实记忆去重消歧与时间遗忘衰减同步闭环。")
