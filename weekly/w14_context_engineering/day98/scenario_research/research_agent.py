"""
Day 98 场景一: Research Agent 主编排器 (research_agent.py)

===============================================================================
设计方案说明 (Architecture Design Specification)
===============================================================================

1. 设计意图 (Design Intent):
   无逻辑控制主入口 — 纯粹串联微引擎的数据流拼装积木墙。
   接收用户 Query → 获取 RAG/Memory 候选 → Context Pipeline 编译 →
   模型路由 + LLM 调用 → 返回响应与全链路 Trace 数据。
   维护多轮对话状态，验证 Static Prefix Hash 跨轮次稳定。

2. 核心类与数据流:
   - ResearchAgent: 主编排器
     - execute_query(): 单轮执行入口
     - get_trace_data(): 获取全链路审计数据
   - AgentTraceData: 全链路 Trace 聚合容器

3. 核心用例设计意图:
   验证 5 轮对话中 Static Prefix Hash 100% 一致，
   全链路 Trace 数据完整可审计。
===============================================================================
"""

import os
import sys
import time
import json
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field

current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from rag_simulator import retrieve_papers
from memory_store import retrieve_user_memory
from context_integrator import ResearchContextIntegrator, ContextAssemblyResult
from gateway_adapter import ResearchGateway


@dataclass
class RoundTrace:
    """单轮执行 Trace 记录"""
    round_num: int
    query: str
    # Assembly 数据
    selected_count: int = 0
    rejected_count: int = 0
    total_tokens: int = 0
    security_alerts_count: int = 0
    # Layout 数据
    prefix_hash: str = ""
    static_ratio: float = 0.0
    cache_potential: str = ""
    # Routing 数据
    model_used: str = ""
    latency_ms: float = 0.0
    routing_error: Optional[str] = None
    # 响应
    response_preview: str = ""
    timestamp: float = field(default_factory=time.time)


class ResearchAgent:
    """
    Research Agent 主编排器 (积木墙)

    仅负责串联数据流向，不承担具体算法实现。
    所有核心逻辑委托给各微引擎集成层。
    """

    def __init__(self):
        # 初始化微引擎集成层
        self.integrator = ResearchContextIntegrator(
            retrieval_budget=2000,
            memory_budget=800,
            global_budget=4000
        )
        self.gateway = ResearchGateway()

        # 对话状态
        self.dialogue_history: List[Dict[str, str]] = []
        self.round_traces: List[RoundTrace] = []
        self.round_counter = 0

        # 全链路审计数据
        self.all_decision_logs: List[List[Dict]] = []
        self.all_security_alerts: List[List[Dict]] = []
        self.prefix_hash_history: List[str] = []

        # 在第 3 轮模拟 429 故障
        self.gateway.set_429_simulation(round_num=3)

    async def execute_query(
        self,
        query: str,
        event_callback=None,
        round_num: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        执行单轮查询

        Args:
            query: 用户查询
            event_callback: 异步事件回调 (用于 WebSocket 实时推送)
                           callback(event_type: str, data: dict) -> None
            round_num: 可选指定轮次

        Returns:
            Dict 包含: response_text, trace, assembly_result
        """
        if round_num is not None:
            self.round_counter = round_num - 1
        self.round_counter += 1
        round_num = self.round_counter

        trace = RoundTrace(round_num=round_num, query=query)

        # ━━━━━ Step 1: 获取 RAG + Memory 候选 ━━━━━
        if event_callback:
            await event_callback("phase", {"phase": "RETRIEVING", "round": round_num})

        rag_candidates = retrieve_papers(query)
        memory_candidates = retrieve_user_memory()

        if event_callback:
            await event_callback("retrieval_done", {
                "rag_count": len(rag_candidates),
                "memory_count": len(memory_candidates),
                "total_candidate_tokens": sum(c.estimated_tokens for c in rag_candidates + memory_candidates)
            })

        # ━━━━━ Step 2: Context Pipeline 编译 ━━━━━
        if event_callback:
            await event_callback("phase", {"phase": "ASSEMBLING", "round": round_num})

        assembly_result = await self.integrator.assemble_context(
            query=query,
            rag_candidates=rag_candidates,
            memory_candidates=memory_candidates,
            dialogue_history=self.dialogue_history,
            round_num=round_num
        )

        trace.selected_count = assembly_result.selected_count
        trace.rejected_count = assembly_result.rejected_count
        trace.total_tokens = assembly_result.total_tokens
        trace.security_alerts_count = len(assembly_result.security_alerts)
        trace.prefix_hash = assembly_result.prefix_hash
        trace.static_ratio = assembly_result.layout_analysis.get("static_prefix_ratio", 0)
        trace.cache_potential = assembly_result.layout_analysis.get("cache_potential_level", "N/A")

        self.all_decision_logs.append(assembly_result.decision_log)
        self.all_security_alerts.append(assembly_result.security_alerts)
        self.prefix_hash_history.append(assembly_result.prefix_hash)

        if event_callback:
            await event_callback("assembly_done", {
                "selected": assembly_result.selected_count,
                "rejected": assembly_result.rejected_count,
                "total_tokens": assembly_result.total_tokens,
                "security_alerts": len(assembly_result.security_alerts),
                "prefix_hash": assembly_result.prefix_hash,
                "static_ratio": assembly_result.layout_analysis.get("static_prefix_ratio", 0),
                "decision_log": assembly_result.decision_log
            })

            # 逐条推送安全警报
            for alert in assembly_result.security_alerts:
                await event_callback("security_alert", alert)

        # ━━━━━ Step 3: 模型路由 + LLM 调用 ━━━━━
        if event_callback:
            await event_callback("phase", {"phase": "ROUTING", "round": round_num})

        gateway_result = await self.gateway.route_and_call(
            payload=assembly_result.payload,
            round_num=round_num
        )

        trace.model_used = gateway_result["model_used"]
        trace.latency_ms = gateway_result["latency_ms"]
        routing_decision = gateway_result["routing_decision"]
        if routing_decision.error_event:
            trace.routing_error = routing_decision.error_event

        if event_callback:
            await event_callback("routing_done", {
                "model_used": trace.model_used,
                "latency_ms": trace.latency_ms,
                "error_event": trace.routing_error,
                "health_scores": routing_decision.health_scores
            })

        # ━━━━━ Step 4: 处理响应 ━━━━━
        response_text = gateway_result["response_text"]
        trace.response_preview = response_text[:200] + "..." if len(response_text) > 200 else response_text

        # 更新对话历史
        self.dialogue_history.append({"role": "user", "content": query})
        self.dialogue_history.append({"role": "assistant", "content": response_text})

        self.round_traces.append(trace)

        if event_callback:
            await event_callback("round_complete", {
                "round_num": round_num,
                "response_text": response_text,
                "trace_summary": {
                    "selected": trace.selected_count,
                    "rejected": trace.rejected_count,
                    "tokens": trace.total_tokens,
                    "alerts": trace.security_alerts_count,
                    "prefix_hash": trace.prefix_hash,
                    "model": trace.model_used,
                    "latency": trace.latency_ms
                }
            })

        return {
            "response_text": response_text,
            "trace": trace,
            "assembly_result": assembly_result
        }

    def get_trace_data(self) -> Dict[str, Any]:
        """获取全链路审计数据"""
        # 检查 Prefix Hash 稳定性
        unique_hashes = set(self.prefix_hash_history)
        prefix_stable = len(unique_hashes) <= 1

        return {
            "total_rounds": self.round_counter,
            "prefix_hash_history": self.prefix_hash_history,
            "prefix_hash_stable": prefix_stable,
            "round_traces": [
                {
                    "round": t.round_num,
                    "query": t.query[:60],
                    "selected": t.selected_count,
                    "rejected": t.rejected_count,
                    "tokens": t.total_tokens,
                    "alerts": t.security_alerts_count,
                    "prefix_hash": t.prefix_hash[:12] + "...",
                    "static_ratio": t.static_ratio,
                    "model": t.model_used,
                    "latency_ms": t.latency_ms,
                    "routing_error": t.routing_error
                }
                for t in self.round_traces
            ],
            "routing_log": self.gateway.get_routing_log_json(),
            "security_alerts": self.all_security_alerts,
        }
