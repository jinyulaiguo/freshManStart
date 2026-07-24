"""
Day 84 综合实战: Report Generator 报告生成节点

【设计说明】
基于组装好的 context_prompt 调用 MiniMax LLM 真实 API 生成深入、详实的行业研究报告草稿。
提升 max_tokens 至 6000，防止长文本在生成章节末尾被 API 强行硬截断。
"""

from typing import Dict, Any
from weekly.w04_prompt_and_http.utils import LLMClient
from weekly.w12_planning_and_reflection.day84.state.research_state import ResearchState


GENERATOR_SYSTEM_PROMPT = """你是一个顶级行业研究机构的高级分析师。
请根据提供的真实 Context 数据，生成一份严谨、详尽的深度行业研究报告。

报告格式规范要求：
1. 包含核心章节：执行摘要、市场规模与增长率、核心技术路线与突破、主要领军厂商与竞争格局、投资机会、关键风险与合规因素。
2. 每一个引用的关键数据、百分比或预测数字，必须在后方明确标明来源标记（例如 [source: step1_market] 或 [source: rag_context]）。
3. 语言严谨专业，绝对不要在文章末尾戛然而止，确保每一个章节都有详实的论述与收尾。
"""


class ReportGeneratorNode:
    """研报生成器节点"""

    def __init__(self):
        self.client = LLMClient()

    async def __call__(self, state: ResearchState) -> Dict[str, Any]:
        context_prompt = state.get("context_prompt", "")

        prompt = f"""请根据以下组装好的上下文与历史反思指令，生成正式完整行业研究报告草稿：

{context_prompt}
"""
        messages = [
            {"role": "system", "content": GENERATOR_SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ]
        print("✍️ [ReportGeneratorNode] 正在调用 MiniMax LLM 生成完整无截断行业研究报告 (max_tokens=6000)...")
        draft_report = await self.client.request_llm(messages=messages, temperature=0.4, max_tokens=6000)

        print(f"📄 [ReportGeneratorNode] 报告草稿生成完成，字数: {len(draft_report)}")
        return {"draft_report": draft_report}
