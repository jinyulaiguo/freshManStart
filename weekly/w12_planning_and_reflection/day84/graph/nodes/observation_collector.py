"""
Day 84 综合实战: Observation Collector 观察合并节点

【设计说明】
将各个并行 TaskStep 收集到的 observations 统一整理提取为清晰的字符串格式，
供 downstream Generator 节点生成综合研报使用。
"""

import json
from typing import Dict, Any
from weekly.w12_planning_and_reflection.day84.state.research_state import ResearchState


class ObservationCollectorNode:
    """观察结果整理合并节点"""

    async def __call__(self, state: ResearchState) -> Dict[str, Any]:
        observations = state.get("observations", {})
        formatted_list = []

        for step_id, obs_data in observations.items():
            content_str = json.dumps(obs_data, ensure_ascii=False)
            formatted_list.append(f"### [Step Output: {step_id}]\n{content_str}")

        combined_obs = "\n\n".join(formatted_list)
        print(f"📦 [ObservationCollectorNode] 归约整理完成，总字符长度: {len(combined_obs)}")
        return {}
