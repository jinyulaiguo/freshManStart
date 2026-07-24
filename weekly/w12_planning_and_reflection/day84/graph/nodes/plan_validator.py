"""
Day 84 综合实战: Plan Validator 校验与防死循环熔断节点

【设计说明】
校验 Planner 生成的 plan 是否合法：
1. 检查 step 数量是否 >= 1。
2. 检查 planner_call_count，若超过最大规划重试阈值 (MAX_PLAN_RETRY = 4)，触发熔断防护。
"""

from typing import Dict, Any, Literal
from weekly.w12_planning_and_reflection.day84.state.research_state import ResearchState


MAX_PLAN_RETRY = 4


class PlanValidatorNode:
    """Plan 结构与死循环熔断校验器"""

    async def __call__(self, state: ResearchState) -> Dict[str, Any]:
        plan = state.get("plan", [])
        planner_count = state.get("planner_call_count", 0)

        if planner_count > MAX_PLAN_RETRY:
            print(f"🛑 [PlanValidatorNode] 触发死循环熔断策略！Planner 累计规划 {planner_count} 次超限。")
            return {
                "error_message": f"Planner max quota exceeded ({planner_count})",
                "is_completed": True
            }

        if not plan:
            print("⚠️ [PlanValidatorNode] Plan 为空，拦截返回并提示。")
            return {"error_message": "Empty plan generated", "is_completed": True}

        print(f"✅ [PlanValidatorNode] Plan 结构校验通过 (含 {len(plan)} 步骤)")
        return {}

    @staticmethod
    def route_guard(state: ResearchState) -> Literal["TO_EXECUTOR", "TO_FALLBACK"]:
        """路由开关"""
        if state.get("error_message") or state.get("is_completed"):
            return "TO_FALLBACK"
        return "TO_EXECUTOR"
