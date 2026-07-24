"""
Day 84 综合实战: Reflector 反思摘要归纳节点 (Reflexion 架构)

【设计说明】
当 Critic 给出 REJECT 时触发。
分析 Critic 提出的缺陷意见与草稿不足，总结提炼出具体的“反思摘要规则 (Reflection Constraint)”，
追加存入 state["reflections"]，供下一轮重构计划或重新生成报告时使用。
传入完整研报草稿，防止只传前 500 字符导致的遗漏。
"""

import re
from typing import Dict, Any
from weekly.w04_prompt_and_http.utils import LLMClient
from weekly.w12_planning_and_reflection.day84.state.research_state import ResearchState


REFLECTOR_SYSTEM_PROMPT = """你是一个高级 Agent 自自我归纳反思器 (Reflector)。
请分析 Critic 审查员给出的拒绝原因与草稿缺陷，总结归纳出 1-2 条极其精准、操作性强的避坑指导规则。

示例输出：
- 下一次生成报告时必须新增单独的“风险分析与合规因素”章节，不得遗漏。
- 下一次生成报告时所有金额与百分比数据必须在后方附带 [source: xxx] 来源标号。
"""


class ReflectorNode:
    """Reflexion 反思总结节点"""

    def __init__(self):
        self.client = LLMClient()

    def _clean_response(self, text: str) -> str:
        if not text:
            return ""
        cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE).strip()
        return cleaned if cleaned else text

    async def __call__(self, state: ResearchState) -> Dict[str, Any]:
        critic_res = state.get("critic_result")
        draft_report = state.get("draft_report", "")
        loop_counter = state.get("loop_counter", 0) + 1

        reason = critic_res.reason if critic_res else "缺少部分必须章节"
        missing = critic_res.missing_sections if critic_res else []

        prompt = f"""Critic 给出的拒绝意见:
{reason}
缺失的章节: {missing}

当前报告草稿 (完整文本):
{draft_report}

请提炼总结针对性的反思规则指令：
"""
        messages = [
            {"role": "system", "content": REFLECTOR_SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ]
        print("🤔 [ReflectorNode] 正在分析失败归因并提炼 Reflexion 经验法则...")
        reflection_rule = await self.client.request_llm(messages=messages, temperature=0.2, max_tokens=2000)

        clean_rule = self._clean_response(reflection_rule)
        print(f"💡 [ReflectorNode] 成功归纳新的反思约束 (第 {loop_counter} 轮): {clean_rule[:70]}...")

        return {
            "reflections": [clean_rule],
            "loop_counter": loop_counter
        }
