"""
Day 98 场景二: 成本治理集成层 (cost_controller.py)

封装 Day 94 CostGovernanceEngine，提供 Coding Agent 场景级 API。
"""

import os
import sys
import time
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field

current_dir = os.path.dirname(os.path.abspath(__file__))
day94_dir = os.path.abspath(os.path.join(current_dir, "../../day94"))
if day94_dir not in sys.path:
    sys.path.append(day94_dir)

from governance_impl import (
    CostGovernanceEngine, HierarchicalBudget, GovernanceState,
    CostPredictor, HumanApprovalRequiredException
)


class CodingCostController:
    """
    Coding 场景成本治理控制器

    封装 Day 94 CostGovernanceEngine，提供：
    - 固定任务预算 $0.15
    - 状态机迁移事件通知
    - 降级策略自动触发
    """

    def __init__(self, task_budget: float = 0.15):
        budget = HierarchicalBudget(task_budget_usd=task_budget)
        self.engine = CostGovernanceEngine(budget=budget)
        self.state_transitions: List[Dict[str, Any]] = []
        self.total_budget = task_budget

    def evaluate_step(self, step_name: str, estimated_tokens: int = 1500) -> Dict[str, Any]:
        """
        评估单步执行的成本影响

        Args:
            step_name: 步骤名称 (如 "planner_node", "tool_executor")
            estimated_tokens: 预估 Token 数

        Returns:
            Dict: 包含状态、消耗比例、是否降级等
        """
        # 估算本步费用
        model = self.engine.optimizer.current_model
        cost = CostPredictor.predict_task_cost("coding", 1, model, estimated_tokens)

        prev_state = self.engine.state
        new_state = self.engine.update_usage_and_transition(estimated_tokens, cost)

        # 记录状态迁移
        if new_state != prev_state:
            transition = {
                "timestamp": time.time(),
                "step": step_name,
                "from_state": prev_state.value,
                "to_state": new_state.value,
                "used_usd": round(self.engine.budget.used_usd, 6),
                "usage_ratio": round(self.engine.budget.used_usd / self.total_budget, 4)
            }
            self.state_transitions.append(transition)

            # DEGRADED 状态自动触发降级
            if new_state == GovernanceState.DEGRADED:
                self.engine.optimizer.apply_degradation(new_state)

        usage_ratio = self.engine.budget.used_usd / self.total_budget if self.total_budget > 0 else 0

        return {
            "state": new_state.value,
            "used_usd": round(self.engine.budget.used_usd, 6),
            "total_budget": self.total_budget,
            "usage_ratio": round(usage_ratio, 4),
            "current_model": self.engine.optimizer.current_model,
            "step_cost": round(cost, 6),
            "is_degraded": new_state == GovernanceState.DEGRADED,
            "is_stopped": new_state == GovernanceState.STOP,
        }

    def get_current_state(self) -> str:
        return self.engine.state.value

    def get_current_model(self) -> str:
        return self.engine.optimizer.current_model

    def should_use_lightweight_model(self) -> bool:
        """是否应使用轻量模型"""
        return self.engine.state in (GovernanceState.DEGRADED, GovernanceState.STOP)

    def get_cost_trace(self) -> Dict[str, Any]:
        """导出成本审计数据"""
        return {
            "total_budget": self.total_budget,
            "used_usd": round(self.engine.budget.used_usd, 6),
            "used_tokens": self.engine.budget.used_tokens,
            "final_state": self.engine.state.value,
            "transitions": self.state_transitions,
            "trace_logs": self.engine.trace_logs
        }
