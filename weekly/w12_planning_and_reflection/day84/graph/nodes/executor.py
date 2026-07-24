"""
Day 84 综合实战: ReWOO 并行 Executor 节点 (DAG 拓扑解耦)

【设计说明】
实现 ReWOO 范式核心执行器。
1. 调用 DependencyGraph 提取拓扑层级 (Topological Layers)。
2. 对无互相依赖的同一层 TaskSteps，使用 asyncio.gather 进行真正的并发工具分发调度。
3. 执行结果自动回填至 state["observations"] 与 state["variables"]，为下游 ContextBuilder 提供完整实测数据。
"""

import asyncio
from typing import Dict, Any, List
from weekly.w12_planning_and_reflection.day84.state.research_state import ResearchState
from weekly.w12_planning_and_reflection.day84.planning.plan_schema import TaskStep
from weekly.w12_planning_and_reflection.day84.planning.dependency import DependencyGraph
from weekly.w12_planning_and_reflection.day84.tools.registry import ToolRegistry


class ReWOOExecutorNode:
    """ReWOO DAG 层级并发执行器"""

    def __init__(self):
        self.registry = ToolRegistry()

    async def _execute_single_step(self, step: TaskStep, variables: Dict[str, Any]) -> tuple[str, str, Any]:
        """
        单步执行并解包变量
        """
        query = step.description
        # 替换变量占位符 (例如 #market_data 替换为实际前置变量)
        for var_name, var_val in variables.items():
            placeholder = f"#{var_name}"
            if placeholder in query:
                query = query.replace(placeholder, str(var_val))

        print(f"⚡ [ReWOOExecutorNode] 正在执行步骤 [{step.id}] ({step.task_type}): {query[:40]}...")
        result = await self.registry.dispatch(step.task_type, query)
        return step.id, step.output_var, result

    async def __call__(self, state: ResearchState) -> Dict[str, Any]:
        plan_dicts = state.get("plan", [])
        if not plan_dicts:
            return {}

        steps = [TaskStep(**d) for d in plan_dicts]
        dep_graph = DependencyGraph(steps)
        layers = dep_graph.get_execution_layers()

        new_observations: Dict[str, Any] = {}
        new_variables: Dict[str, Any] = dict(state.get("variables", {}))

        print(f"🚀 [ReWOOExecutorNode] 启动 DAG 层级并行调度，共 {len(layers)} 个拓扑层")

        for layer_idx, layer_steps in enumerate(layers, start=1):
            print(f"   ⚙️ 正在并发调度第 {layer_idx}/{len(layers)} 层 (含 {len(layer_steps)} 个独立 TaskStep)")
            tasks = [
                self._execute_single_step(step, new_variables)
                for step in layer_steps
            ]
            layer_results = await asyncio.gather(*tasks)

            for step_id, out_var, res_payload in layer_results:
                new_observations[step_id] = res_payload
                new_variables[out_var] = res_payload

        print(f"✅ [ReWOOExecutorNode] 所有 TaskStep 执行完毕，收集到 {len(new_observations)} 条 Observation数据")
        return {
            "observations": new_observations,
            "variables": new_variables
        }
