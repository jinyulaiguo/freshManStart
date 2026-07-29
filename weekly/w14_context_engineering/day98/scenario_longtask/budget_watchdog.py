"""
Day 98 场景三: 长任务预算看门狗 (budget_watchdog.py)

封装 Day 94 CostGovernanceEngine，适配 30 分钟长任务预算控制。
"""

import os
import sys
import time
from typing import Dict, Any, List

current_dir = os.path.dirname(os.path.abspath(__file__))
day94_dir = os.path.abspath(os.path.join(current_dir, "../../day94"))
if day94_dir not in sys.path:
    sys.path.append(day94_dir)

from governance_impl import (
    CostGovernanceEngine, HierarchicalBudget, GovernanceState,
    CostPredictor
)


class BudgetWatchdog:
    """
    长任务预算看门狗

    适配 30 分钟长任务:
    - 任务级预算 $0.50
    - 70% → WARNING, 90% → DEGRADED
    - 联动压缩控制器和容灾网关
    """

    def __init__(self, task_budget: float = 0.50):
        budget = HierarchicalBudget(task_budget_usd=task_budget)
        self.engine = CostGovernanceEngine(budget=budget)
        self.total_budget = task_budget
        self.state_transitions: List[Dict[str, Any]] = []
        self.step_log: List[Dict[str, Any]] = []

    def record_step(self, scan_index: int, tokens: int = 500, model: str = "MiniMax-M3") -> Dict[str, Any]:
        """记录单步消耗"""
        cost = CostPredictor.predict_task_cost("audit", 1, model, tokens)
        prev_state = self.engine.state
        new_state = self.engine.update_usage_and_transition(tokens, cost)

        if new_state != prev_state:
            self.state_transitions.append({
                "scan_index": scan_index,
                "from": prev_state.value,
                "to": new_state.value,
                "used_usd": round(self.engine.budget.used_usd, 6),
                "timestamp": time.time()
            })

        usage_ratio = self.engine.budget.used_usd / self.total_budget if self.total_budget > 0 else 0

        entry = {
            "scan_index": scan_index,
            "state": new_state.value,
            "used_usd": round(self.engine.budget.used_usd, 6),
            "usage_ratio": round(usage_ratio, 4),
            "step_cost": round(cost, 6),
        }
        self.step_log.append(entry)

        return entry

    def get_state(self) -> str:
        return self.engine.state.value

    def should_compress(self) -> bool:
        """是否应触发额外压缩"""
        return self.engine.state in (GovernanceState.WARNING, GovernanceState.DEGRADED)

    def should_use_lightweight(self) -> bool:
        """是否应使用轻量模型"""
        return self.engine.state == GovernanceState.DEGRADED

    def get_trace(self) -> Dict[str, Any]:
        return {
            "total_budget": self.total_budget,
            "used_usd": round(self.engine.budget.used_usd, 6),
            "final_state": self.engine.state.value,
            "transitions": self.state_transitions,
            "steps": len(self.step_log),
        }
