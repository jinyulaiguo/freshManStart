"""
Day 84 综合实战: RePlanner 动态计划重组节点

【设计说明】
结合 Reflexion 归纳出的经验法则，动态调整或扩展后续未执行的 TaskStep 计划拓扑。
如果发现数据缺失，自动追加专项搜索 step。
引入防 <think> 标签剥离与 JSON 语法损坏降级保底机制。
"""

import re
from typing import Dict, Any
from weekly.w04_prompt_and_http.utils import LLMClient
from middlewares.llm_reliability_adapter import parse_structured
from weekly.w12_planning_and_reflection.day84.state.research_state import ResearchState
from weekly.w12_planning_and_reflection.day84.planning.plan_schema import TaskPlanPayload


class ReplannerNode:
    """动态重规划节点"""

    def __init__(self):
        self.client = LLMClient()

    def _clean_response(self, text: str) -> str:
        if not text:
            return ""
        cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE).strip()
        return cleaned if cleaned else text

    async def __call__(self, state: ResearchState) -> Dict[str, Any]:
        reflections = state.get("reflections", [])
        existing_plan = state.get("plan", [])

        prompt = f"""当前已归纳的反思建议:
{reflections}

当前已有计划:
{existing_plan}

请重新审查并更新 TaskPlanPayload。如有必要，增加针对特定缺陷 (如风险因素) 的补充调研步骤。
严禁使用 <think> 标签，请直接输出符合 TaskPlanPayload Schema 的 JSON。
"""
        messages = [
            {"role": "system", "content": "你是一个高级动态重规划器。只输出包含更新后 steps 的 JSON。"},
            {"role": "user", "content": prompt}
        ]
        print("🔄 [ReplannerNode] 正在根据 Reflexion 反思动态调整任务规划...")
        
        try:
            raw_resp = await self.client.request_llm(messages=messages, temperature=0.2, max_tokens=2500)
            cleaned_resp = self._clean_response(raw_resp)
            plan_payload = parse_structured(cleaned_resp, TaskPlanPayload)
            updated_steps_dict = [s.model_dump() for s in plan_payload.steps]
        except Exception as e:
            print(f"⚠️ [ReplannerNode] 动态重规划提取解析捕捉异样 ({e})，继承保留原计划拓扑")
            updated_steps_dict = existing_plan

        print(f"✨ [ReplannerNode] 动态计划重构完成，更新为 {len(updated_steps_dict)} 个步骤")
        return {"plan": updated_steps_dict}
