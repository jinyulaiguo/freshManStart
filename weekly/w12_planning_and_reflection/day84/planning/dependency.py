"""
Day 84 综合实战: DAG 依赖拓扑解析器 (Dependency Graph)

【设计说明】
实现 ReWOO 范式下的 TaskStep DAG 依赖拓扑解析。
将强类型任务列表解析为层级拓扑 (Topological Layers)，确保：
1. 每一层内的 TaskStep 互不依赖，可以安全使用 asyncio.gather 并行拉起。
2. 上层 TaskStep 执行完毕后，其 output_var 自动注入变量池，下层依赖这些变量的 Step 才能被拉起。
"""

from typing import List, Dict, Any, Set
from weekly.w12_planning_and_reflection.day84.planning.plan_schema import TaskStep


class DependencyGraph:
    """
    DAG 拓扑解析与并发分级计算器
    """

    def __init__(self, steps: List[TaskStep]):
        self.steps = {s.id: s for s in steps}

    def get_execution_layers(self) -> List[List[TaskStep]]:
        """
        计算 TaskStep 的拓扑层级 (Layers)。
        返回 List[List[TaskStep]]，第 i 个子数组代表第 i 层可并发执行的 TaskStep。
        """
        in_degree: Dict[str, int] = {s_id: 0 for s_id in self.steps}
        adj_list: Dict[str, List[str]] = {s_id: [] for s_id in self.steps}

        # 构建图与入度表
        for s_id, step in self.steps.items():
            for dep_id in step.dependency:
                if dep_id in self.steps:
                    adj_list[dep_id].append(s_id)
                    in_degree[s_id] += 1

        layers: List[List[TaskStep]] = []
        visited: Set[str] = set()

        while len(visited) < len(self.steps):
            # 找出当前入度为 0 且未处理的节点
            current_layer_ids = [
                s_id for s_id, deg in in_degree.items()
                if deg == 0 and s_id not in visited
            ]

            if not current_layer_ids:
                # 存在依赖环路或无效依赖，强制将剩余未处理节点放最后一层
                remaining = [s for s_id, s in self.steps.items() if s_id not in visited]
                layers.append(remaining)
                break

            current_layer_steps = [self.steps[s_id] for s_id in current_layer_ids]
            layers.append(current_layer_steps)

            # 更新拓扑状态
            for s_id in current_layer_ids:
                visited.add(s_id)
                for neighbor in adj_list[s_id]:
                    in_degree[neighbor] -= 1

        return layers
