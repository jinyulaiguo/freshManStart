"""
Day 98 场景一: Model Router 适配层 (gateway_adapter.py)

===============================================================================
设计方案说明 (Architecture Design Specification)
===============================================================================

1. 设计意图 (Design Intent):
   封装 Day 97 ModelDecisionEngine + LLMGateway，为研究场景提供统一的模型
   路由与 LLM 调用接口。支持 8 维路由决策、429 Rate Limit 模拟触发、
   Fallback 降级链与全链路路由审计日志。

2. 核心类与数据流:
   - ResearchGateway: 研究场景网关适配器
     - route_and_call(): 路由 + 调用一体化接口
     - simulate_429(): 模拟 429 Rate Limit 故障
   - RoutingDecision: 路由决策记录

3. 核心用例设计意图:
   验证 RESEARCH/HIGH 任务自动路由至旗舰模型，429 场景正确切换备用 Provider。
===============================================================================
"""

import os
import sys
import time
import json
import asyncio
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field

# 导入 Day 97 的 Model Control Plane 与 Gateway
current_dir = os.path.dirname(os.path.abspath(__file__))
day97_dir = os.path.abspath(os.path.join(current_dir, "../../day97"))
w04_dir = os.path.abspath(os.path.join(current_dir, "../../../w04_prompt_and_http"))

if day97_dir not in sys.path:
    sys.path.append(day97_dir)
if w04_dir not in sys.path:
    sys.path.append(w04_dir)

from router_gateway_impl import (
    ModelDecisionEngine, LLMGateway, ErrorClassifier,
    ProviderHealthTracker, TaskRequirement, TaskType,
    ModelComplexity, PROVIDER_REGISTRY
)
from utils import LLMClient


@dataclass
class RoutingDecision:
    """路由决策记录"""
    round_num: int
    task_type: str
    complexity: str
    selected_model: str
    selected_provider: str
    fallback_chain: List[str]
    health_scores: Dict[str, float]
    timestamp: float = field(default_factory=time.time)
    error_event: Optional[str] = None
    actual_model_used: Optional[str] = None


class ResearchGateway:
    """
    研究场景模型路由网关适配器

    封装 Day 97 的 8 维路由决策引擎，专为 Research Agent 场景提供：
    - RESEARCH/HIGH 任务自动路由至旗舰模型
    - 429 Rate Limit 模拟与 Fallback 验证
    - 全链路路由决策审计日志
    """

    def __init__(self):
        self.health_tracker = ProviderHealthTracker()
        self.decision_engine = ModelDecisionEngine(health_tracker=self.health_tracker)
        self.gateway = LLMGateway(
            decision_engine=self.decision_engine
        )
        self.client = LLMClient()
        self.routing_log: List[RoutingDecision] = []
        self._simulate_429_on_round: Optional[int] = None

    def set_429_simulation(self, round_num: int):
        """设置在指定轮次模拟 429 Rate Limit 故障"""
        self._simulate_429_on_round = round_num

    async def route_and_call(
        self,
        payload: List[Dict[str, str]],
        round_num: int = 1,
        remaining_budget: float = 1.0
    ) -> Dict[str, Any]:
        """
        路由决策 + LLM 调用一体化接口

        Args:
            payload: LLM Messages Payload
            round_num: 当前对话轮次
            remaining_budget: 剩余预算 (美金)

        Returns:
            Dict 包含: response_text, routing_decision, model_used, latency_ms
        """
        # 构造 8 维路由输入
        task_req = TaskRequirement(
            task_type=TaskType.RESEARCH,
            complexity=ModelComplexity.HIGH,
            required_capabilities={"long_context"},
            context_tokens=sum(len(m.get("content", "")) // 4 for m in payload),
            max_latency_ms=10000,
            remaining_budget_usd=remaining_budget,
            agent_node_name="research_executor"
        )

        # 执行 8 维路由决策
        selected = self.decision_engine.select_provider(
            task_req, self.health_tracker
        )

        # 构造 Fallback 链
        fallback_chain = [
            p.model_name for p in PROVIDER_REGISTRY
            if p.model_name != selected.model_name
        ]

        # 记录路由决策
        decision = RoutingDecision(
            round_num=round_num,
            task_type="RESEARCH",
            complexity="HIGH",
            selected_model=selected.model_name,
            selected_provider=selected.provider_name,
            fallback_chain=fallback_chain[:3],
            health_scores=self._get_health_snapshot()
        )

        # 检查是否需要模拟 429
        if self._simulate_429_on_round == round_num:
            decision.error_event = "429_RATE_LIMIT_SIMULATED"
            # 模拟主模型故障，使用 Fallback
            self.health_tracker.record_failure(selected.model_name)
            # 选择 Fallback 模型
            for fb_model in fallback_chain:
                if self.health_tracker.is_available(fb_model):
                    decision.actual_model_used = fb_model
                    break

        actual_model = decision.actual_model_used or selected.model_name
        decision.actual_model_used = actual_model

        self.routing_log.append(decision)

        # 调用 LLM (使用真实 API)
        start_time = time.time()
        try:
            response_text = await self.client.request_llm(
                messages=payload,
                temperature=0.3,
                max_tokens=4096
            )
            latency_ms = (time.time() - start_time) * 1000

            # 记录成功
            self.health_tracker.record_success(actual_model, latency_ms)

            return {
                "response_text": response_text,
                "routing_decision": decision,
                "model_used": actual_model,
                "latency_ms": round(latency_ms, 1)
            }

        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            self.health_tracker.record_failure(actual_model)

            # 尝试 Fallback
            for fb_model in fallback_chain:
                if self.health_tracker.is_available(fb_model):
                    try:
                        response_text = await self.client.request_llm(
                            messages=payload,
                            temperature=0.3,
                            max_tokens=2000
                        )
                        decision.actual_model_used = fb_model
                        decision.error_event = f"FALLBACK_TO_{fb_model}"
                        return {
                            "response_text": response_text,
                            "routing_decision": decision,
                            "model_used": fb_model,
                            "latency_ms": round(latency_ms, 1)
                        }
                    except Exception:
                        continue

            return {
                "response_text": f"[ERROR] 所有模型均不可用: {str(e)}",
                "routing_decision": decision,
                "model_used": "none",
                "latency_ms": round(latency_ms, 1)
            }

    def _get_health_snapshot(self) -> Dict[str, float]:
        """获取当前所有 Provider 的健康分快照"""
        snapshot = {}
        for p in PROVIDER_REGISTRY:
            score = self.health_tracker.get_health_score(p.model_name)
            snapshot[p.model_name] = score
        return snapshot

    def get_routing_log_json(self) -> List[Dict[str, Any]]:
        """导出路由日志为 JSON 序列化格式"""
        log = []
        for d in self.routing_log:
            log.append({
                "round_num": d.round_num,
                "task_type": d.task_type,
                "complexity": d.complexity,
                "selected_model": d.selected_model,
                "selected_provider": d.selected_provider,
                "actual_model_used": d.actual_model_used,
                "fallback_chain": d.fallback_chain,
                "health_scores": d.health_scores,
                "error_event": d.error_event,
                "timestamp": d.timestamp
            })
        return log
