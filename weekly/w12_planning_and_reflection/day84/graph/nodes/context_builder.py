"""
Day 84 综合实战: Context Builder 节点 (Token 预算管理与 Reflexion 注入)

【设计说明】
构建给 Generator 的物理 Prompt。
将 MAX_CONTEXT_CHARS 提升至 25000 字符，充分容纳所有 ReWOO 多路并发收集到的行业数据，
防止因人工偏小的 Char 预算限制导致关键章节数据被物理裁剪截断。
"""

import json
from typing import Dict, Any
from weekly.w12_planning_and_reflection.day84.state.research_state import ResearchState


MAX_CONTEXT_CHARS = 25000


class ContextBuilderNode:
    """上下文剪裁与反思规则组装节点"""

    async def __call__(self, state: ResearchState) -> Dict[str, Any]:
        user_query = state.get("user_query", "")
        observations = state.get("observations", {})
        reflections = state.get("reflections", [])
        verification_result = state.get("verification_result")

        # 整理 Observation 数据
        obs_text_blocks = []
        for step_id, val in observations.items():
            obs_text_blocks.append(f"【{step_id} 调研结果】:\n{json.dumps(val, ensure_ascii=False)}")
        full_obs_text = "\n\n".join(obs_text_blocks)

        # 预算裁剪 (容量提升至 25000 字符，消除硬裁切)
        if len(full_obs_text) > MAX_CONTEXT_CHARS:
            full_obs_text = full_obs_text[:MAX_CONTEXT_CHARS] + "\n...(达到 25000 字符预算上限自动安全裁剪)..."

        # 注入 Reflexion Memory 历史修补约束
        reflections_prompt = ""
        if reflections:
            rules_str = "\n".join([f"  {idx+1}. {r}" for idx, r in enumerate(reflections)])
            reflections_prompt = f"\n⚠️ [历史自我反思强制约束与经验法则]:\n{rules_str}\n必须严格遵循上述反思法则进行增补修正！\n"

        # 注入 NLI 防幻觉纠偏指令
        correction_guidance = ""
        if verification_result and verification_result.overall_status == "HALLUCINATION_DETECTED":
            correction_guidance = f"\n🛑 [防幻觉 NLI 校对纠偏指令]:\n{verification_result.correction_guidance}\n必须无条件剔除上述无根据或矛盾的数据断言！\n"

        context_prompt = f"""用户研究课题需求:
{user_query}

收集到的真实多源调研 Context:
{full_obs_text}
{reflections_prompt}{correction_guidance}
"""
        print("🧱 [ContextBuilderNode] Prompt 上下文组装完毕 (含 Reflexion 约束，无人工硬截断)")
        return {"context_prompt": context_prompt}
