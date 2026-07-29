"""
Day 98 场景二: 节点级路由集成层 (node_router.py)

封装 Day 97 ModelDecisionEngine，实现 LangGraph 3 节点差异化路由。
"""

import os
import sys
import time
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

current_dir = os.path.dirname(os.path.abspath(__file__))
day97_dir = os.path.abspath(os.path.join(current_dir, "../../day97"))
if day97_dir not in sys.path:
    sys.path.append(day97_dir)

from router_gateway_impl import (
    ModelDecisionEngine, ProviderHealthTracker, TaskRequirement,
    TaskType, ModelComplexity, PROVIDER_REGISTRY
)


# 节点级路由策略配置
NODE_ROUTING_CONFIG = {
    "planner_node": {
        "task_type": TaskType.CODING,
        "complexity": ModelComplexity.HIGH,
        "description": "架构规划节点 — 需要强推理模型",
    },
    "tool_executor": {
        "task_type": TaskType.CODING,
        "complexity": ModelComplexity.LOW,
        "description": "代码执行节点 — 可用轻量模型",
    },
    "reflection_node": {
        "task_type": TaskType.CODING,
        "complexity": ModelComplexity.HIGH,
        "description": "代码审查节点 — 需要强推理模型",
    },
}


class NodeRouter:
    """
    LangGraph 节点级差异化路由器

    根据节点角色分配不同级别的模型：
    - planner_node → 旗舰模型 (gpt-4o)
    - tool_executor → 轻量模型 (gpt-4o-mini)
    - reflection_node → 旗舰模型 (gpt-4o)

    当 Cost Governance 进入 DEGRADED 时，所有节点降级为轻量模型。
    """

    def __init__(self):
        self.decision_engine = ModelDecisionEngine()
        self.health_tracker = ProviderHealthTracker()
        self.routing_log: List[Dict[str, Any]] = []
        self._force_lightweight = False

    def set_force_lightweight(self, force: bool):
        """强制所有节点使用轻量模型（被 Cost Governance 降级触发）"""
        self._force_lightweight = force

    def route_for_node(self, node_name: str, remaining_budget: float = 1.0) -> Dict[str, Any]:
        """
        为指定 LangGraph 节点执行路由决策

        Args:
            node_name: 节点名 (planner_node, tool_executor, reflection_node)
            remaining_budget: 剩余预算

        Returns:
            Dict: 路由决策结果
        """
        config = NODE_ROUTING_CONFIG.get(node_name, NODE_ROUTING_CONFIG["tool_executor"])

        # 如果被降级强制使用轻量模型
        if self._force_lightweight:
            complexity = ModelComplexity.LOW
        else:
            complexity = config["complexity"]

        task_req = TaskRequirement(
            task_type=config["task_type"],
            complexity=complexity,
            required_capabilities={"tool_calling"},
            remaining_budget_usd=remaining_budget,
            agent_node_name=node_name
        )

        selected = self.decision_engine.select_provider(task_req, self.health_tracker)

        decision = {
            "timestamp": time.time(),
            "node_name": node_name,
            "node_description": config["description"],
            "original_complexity": config["complexity"].value,
            "actual_complexity": complexity.value,
            "selected_model": selected.model_name,
            "selected_provider": selected.provider_name,
            "cost_per_1k_input": selected.cost_per_1k_input,
            "forced_lightweight": self._force_lightweight,
        }

        self.routing_log.append(decision)
        return decision

    def get_routing_log(self) -> List[Dict[str, Any]]:
        return self.routing_log

    def calculate_savings(self) -> Dict[str, Any]:
        """计算节点级路由相比全程旗舰模型的节省比例"""
        if not self.routing_log:
            return {"savings_ratio": 0, "total_entries": 0}

        flagship_cost = sum(0.0025 for _ in self.routing_log)  # 假设全用 gpt-4o
        actual_cost = sum(e.get("cost_per_1k_input", 0.0025) for e in self.routing_log)

        savings = (flagship_cost - actual_cost) / flagship_cost if flagship_cost > 0 else 0

        return {
            "flagship_total_cost_1k": round(flagship_cost, 6),
            "actual_total_cost_1k": round(actual_cost, 6),
            "savings_ratio": round(savings, 4),
            "total_entries": len(self.routing_log)
        }
