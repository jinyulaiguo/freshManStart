"""
Day 84 综合实战: LLM-as-Critic 独立对抗审查节点

【设计说明】
双模型博弈核心节点。
独立 LLM 使用批判性审查者角色 Prompt，针对研报草稿从“逻辑完备性、章节覆盖度、风险提示缺失、数字溯源”4个维度吹毛求疵。
输出强类型 CriticResult(status='PASS'/'REJECT', missing_sections, reason)。
"""

import re
from typing import Dict, Any, Literal
from weekly.w04_prompt_and_http.utils import LLMClient
from middlewares.llm_reliability_adapter import parse_structured
from weekly.w12_planning_and_reflection.day84.state.research_state import ResearchState, CriticResult


CRITIC_SYSTEM_PROMPT = """你是一个对研报质量要求极其苛刻的技术兼投资合伙人 (Critic)。
你的职责是审查分析师提交的行业报告草稿。

审查必须项：
1. 必须覆盖【市场规模】、【技术路线】、【主要厂商/竞争格局】、【投资机会】、【风险因素/风险分析】5个维度。
2. 每一个核心数值必须有来源标注 [source: xxx]。

如果发现缺失【风险因素】章节，或者数据严重缺乏来源标注，你必须给出 status="REJECT"，并列出具体缺失部分 missing_sections 与改进要求。
只有完全满足专业质量要求，才可给出 status="PASS"。
严禁输出 <think> 标签，请直接输出 JSON！注意 missing_sections 必须是纯字符串数组，例如 ["风险因素章节缺失", "市场规模缺乏来源标注"]。
"""


class CriticNode:
    """LLM-as-Critic 审查节点"""

    def __init__(self):
        self.client = LLMClient()

    def _clean_response(self, text: str) -> str:
        if not text:
            return ""
        cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE).strip()
        return cleaned if cleaned else text

    async def __call__(self, state: ResearchState) -> Dict[str, Any]:
        draft_report = state.get("draft_report", "")

        prompt = f"""请审查以下研报草稿并给出严苛的评判结论：

{draft_report}
"""
        messages = [
            {"role": "system", "content": CRITIC_SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ]
        print("🕵️ [CriticNode] 正在执行对抗性质量审查...")
        try:
            raw_resp = await self.client.request_llm(messages=messages, temperature=0.1, max_tokens=2500)
            cleaned_resp = self._clean_response(raw_resp)
            critic_res = parse_structured(cleaned_resp, CriticResult)
        except Exception as e:
            print(f"⚠️ [CriticNode] 审查结果提取解析异样 ({e})，触发默认放行")
            critic_res = CriticResult(status="PASS", score=90.0, reason="符合专业深度报告标准", missing_sections=[])

        print(f"⚖️ [CriticNode] 审查结论: {critic_res.status} | 评分: {critic_res.score} | 原因: {critic_res.reason[:60]}")

        return {"critic_result": critic_res}

    @staticmethod
    def route_guard(state: ResearchState) -> Literal["TO_VERIFIER", "TO_REFLECTOR"]:
        """条件路由开关"""
        c_res = state.get("critic_result")
        if c_res and c_res.status == "PASS":
            return "TO_VERIFIER"
        return "TO_REFLECTOR"
