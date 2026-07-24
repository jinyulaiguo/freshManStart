"""
Day 84 综合实战: Planner 节点 (任务解耦与 Plan 生成)

【设计说明】
负责接收用户长文本课题，拆解为强类型 TaskStep 有向图。
支持依赖声明 (dependency) 与变量占位符 (input_vars / output_var)。
引入防 <think> 思维链截断清洗与生产级兜底重试机制。
"""

import re
from typing import Dict, Any
from weekly.w04_prompt_and_http.utils import LLMClient
from middlewares.llm_reliability_adapter import parse_structured
from weekly.w12_planning_and_reflection.day84.state.research_state import ResearchState
from weekly.w12_planning_and_reflection.day84.planning.plan_schema import TaskPlanPayload, TaskStep


PLANNER_SYSTEM_PROMPT = """你是一个顶级企业级行业研究 Agent 的 Planner 规划器。
你的职责是将用户复杂的研报生成需求，拆解为 3-5 个结构紧密、职责单一的 TaskStep。

要求：
1. 每个步骤必须包含唯一的 id (如 step1, step2, step3)。
2. 每个步骤必须明确指定 task_type: search (网络搜索), rag (向量库检索), database (离线库), analyze (综合分析)。
3. 支持依赖约束 dependency: 如 step3 依赖 ['step1', 'step2']。
4. 明确指定 output_var: 如 'market_data', 'company_analysis', 'risk_data'。
5. 严禁包含 <think> 标签，请直接输出符合 TaskPlanPayload Schema 契约的 JSON！
"""

DEFAULT_FALLBACK_STEPS = [
    TaskStep(id="step1", description="搜索医疗AI市场规模及年复合增长率(CAGR)", task_type="search", output_var="market_data"),
    TaskStep(id="step2", description="检索医疗AI核心技术路线、多模态大模型及3D分割技术突破", task_type="rag", output_var="tech_route"),
    TaskStep(id="step3", description="搜索医疗AI主要领军厂商及竞争格局", task_type="search", output_var="company_analysis"),
    TaskStep(id="step4", description="查询医疗AI在罕见病筛选、患者匹配等领域的投资机会", task_type="database", output_var="investment_data"),
    TaskStep(id="step5", description="综合分析FDA/NMPA审批周期、医疗伦理及合规风险因素", task_type="analyze", dependency=["step1", "step2", "step3", "step4"], output_var="risk_analysis"),
]


class PlannerNode:
    """Planner 规划节点"""

    def __init__(self):
        self.client = LLMClient()

    def _clean_response(self, text: str) -> str:
        """剥离 <think> 思考块"""
        if not text:
            return ""
        cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE).strip()
        return cleaned if cleaned else text

    async def __call__(self, state: ResearchState) -> Dict[str, Any]:
        user_query = state.get("user_query", "分析2026年医疗AI行业发展趋势")
        planner_count = state.get("planner_call_count", 0) + 1

        prompt = f"""用户研究课题:
{user_query}

请生成一套高精度的 TaskPlanPayload 任务拓扑图。
"""
        messages = [
            {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ]
        
        try:
            raw_resp = await self.client.request_llm(messages=messages, temperature=0.2, max_tokens=2500)
            cleaned_resp = self._clean_response(raw_resp)
            plan_payload = parse_structured(cleaned_resp, TaskPlanPayload)
            steps_dict = [step.model_dump() for step in plan_payload.steps]
        except Exception as e:
            print(f"⚠️ [PlannerNode] 计划结构化提取捕获异常 ({e})，启用生产级降级方案")
            steps_dict = [step.model_dump() for step in DEFAULT_FALLBACK_STEPS]

        print(f"📌 [PlannerNode] (第 {planner_count} 次规划) 成功生成 {len(steps_dict)} 个 TaskStep")
        for s in steps_dict:
            print(f"   - [{s['id']}] ({s['task_type']}) {s['description']} | Dep: {s['dependency']} -> Var: ${s['output_var']}")

        return {
            "plan": steps_dict,
            "current_step": 0,
            "planner_call_count": planner_count,
            "is_completed": False
        }
