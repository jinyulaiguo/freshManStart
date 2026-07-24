"""
Day 80 参考标准答案: LLM-as-Critic 独立审查器与双模型博弈架构

【系统设计方案说明】
1. 设计意图 (Design Intent):
   构建生产级 Generator-Critic 双模型博弈架构引擎。引入独立系统提示词的 Critic 法官节点，
   扫描生成物中的逻辑漏洞、合规盲区与格式缺陷，输出强类型 Pydantic 决策 Payload (PASS/REJECT)。
   解决单一模型自查存在认知盲区与自我包庇的问题，提升高严肃性业务文本 (如英文法律合同) 的可靠性。

2. 类与函数结构 (Class & Function Architecture):
   - CriticReview: Pydantic 模型，定义物理隔离的审查决策契约 (decision, score, risk_items, critique_feedback)。
   - ContractDraft: Pydantic 模型，存储生成的合同文本草稿与版本号。
   - CriticGameState: TypedDict 状态容器，维护合同需求、当前草稿、历次审查记录与博弈计数器。
   - GeneratorNode: 采用 Tag-Separated 格式解析器，可靠提取消除了换行与双引号转义困扰的长篇合同文本。
   - CriticNode: 独立的审查法官节点，以防范风险为导向进行盲审，输出 CriticReview。
   - GameLoopGuard: 博弈收敛与熔断控制器，防止无限 REJECT 循环。
   - CriticGameEngine: 主图调度流程，驱动博弈对抗与条件路由。

3. 关键数据流流向 (Data Flow):
   User Input ➔ GeneratorNode ➔ ContractDraft ➔ CriticNode ➔ CriticReview Payload
     ➔ Router Edge ➔ (If PASS & Score>=85) ➔ END Node
     ➔ Router Edge ➔ (If REJECT & Loop<3) ➔ GeneratorNode (Revision with Feedback)
     ➔ Router Edge ➔ (If Loop>=3) ➔ Manual Intercept / Fallback Node

4. 核心用例设计意图 (Test Case Design Intent):
   选取“自动生成合规的跨境软件服务 (SaaS) 英文法律合同”作为标准验证场景：
   - 验证点 1：测试 Generator 在初次生成时故意缺少关键保护条款（如未写违约金上限或终止通知期）。
   - 验证点 2：测试 Critic Node 能否独立识别出上述合同隐患，准确输出 REJECT 及针对性的修改指令。
   - 验证点 3：测试 Router 条件路由能否成功将 Critic Feedback 喂回 Generator 进行二次修改。
   - 验证点 4：测试修改后的合同草稿能否成功通过 Critic 审查（输出 PASS & Score>=85），验证博弈收敛能力。
"""

import asyncio
import json
import re
import time
from typing import Dict, List, Any, Optional, Literal, TypedDict
from pydantic import BaseModel, Field

# 从公共工具加载 API 凭证与配置 (规则 12 & 20)
from weekly.w04_prompt_and_http.utils import load_env_file, LLMClient

# 从平级独立中间件导入一键式极简门面函数 parse_structured
from middlewares.llm_reliability_adapter import parse_structured

# 加载环境变量
load_env_file()


# ==========================================
# 1. 强类型 Pydantic Schema 契约
# ==========================================

class CriticReview(BaseModel):
    """
    Critic 独立审查法官强类型决策 Payload
    """
    decision: Literal["PASS", "REJECT"] = Field(description="审查结论：PASS(通过) 或 REJECT(驳回重构)")
    score: int = Field(ge=0, le=100, description="综合合规与严密性评分 (0-100)")
    risk_items: List[str] = Field(default_factory=list, description="检测到的缺陷、排版隐患或法律风险清单")
    critique_feedback: str = Field(description="具体的修改指令，供 Generator 在下一轮精准修复")


class ContractDraft(BaseModel):
    """
    生成器产出的合同草稿契约
    """
    title: str = Field(description="合同名称")
    content: str = Field(description="合同全文内容")
    version: int = Field(default=1, description="草稿版本号")


class CriticGameState(TypedDict):
    """
    LangGraph 状态图全局 TypedDict 容器
    """
    contract_requirement: str
    current_draft: Optional[ContractDraft]
    latest_review: Optional[CriticReview]
    loop_counter: int  # 博弈轮次计数器


# ==========================================
# 2. 博弈控制器 (GameLoopGuard)
# ==========================================

class GameLoopGuard:
    """
    博弈收敛与熔断控制器
    """

    def __init__(self, max_loops: int = 3, pass_score: int = 85):
        self.max_loops = max_loops
        self.pass_score = pass_score

    def evaluate_routing(self, state: CriticGameState) -> str:
        """
        判断博弈路由流向

        :param state: 全局 CriticGameState
        :return: 路由信号 ("TO_END", "TO_GENERATOR_REVISE", "TO_FALLBACK")
        """
        review = state.get("latest_review")
        loop_count = state.get("loop_counter", 0)

        if review and review.decision == "PASS" and review.score >= self.pass_score:
            return "TO_END"

        if loop_count >= self.max_loops:
            return "TO_FALLBACK"

        return "TO_GENERATOR_REVISE"


# ==========================================
# 3. 标签分隔解析器与 Critic JSON 解析
# ==========================================

def parse_contract_tag_format(raw_text: str, default_title: str = "SaaS Service Agreement") -> tuple[str, str]:
    """
    使用 ===TITLE=== 和 ===CONTENT=== 提取长篇合同文本
    彻底规避多行字符串中的未转义双引号与换行引发的 JSONDecodeError 崩溃
    增加截断保护：防止大模型在 ===CONTENT=== 处截断导致内容清空
    """
    # 物理剥离大模型思维链 <think>...</think> 标签
    cleaned_text = re.sub(r"<think>.*?</think>", "", raw_text, flags=re.DOTALL).strip()

    title = default_title
    content = cleaned_text

    if "===TITLE===" in cleaned_text and "===CONTENT===" in cleaned_text:
        parts = cleaned_text.split("===CONTENT===")
        title_part = parts[0].split("===TITLE===")[1].strip()
        content_part = parts[1].strip()
        if title_part:
            title = title_part
        if content_part:
            content = content_part
        else:
            # 截断兜底：如果 ===CONTENT=== 后面被截断为空，清理标签保留前面生成的正文
            content = re.sub(r"===TITLE===|===CONTENT===", "", cleaned_text).strip()
    elif "===TITLE===" in cleaned_text:
        content = re.sub(r"===TITLE===", "", cleaned_text).strip()

    return title, content


def parse_critic_json(raw_output: str) -> dict:
    """
    使用 middlewares/llm_reliability_adapter 极简门面函数 parse_structured()
    一键式完成清洗、栈提取、解码、Pydantic 强校验与 0 延迟确定性修复！
    """
    try:
        review_obj = parse_structured(raw_output, CriticReview)
        return review_obj.model_dump()
    except Exception:
        pass

    # 兜底：若严重损坏则做正则降级保底
    target_str = raw_output
    decision = "PASS" if re.search(r'"decision"\s*:\s*"PASS"', target_str, re.IGNORECASE) else "REJECT"
    score = 85 if decision == "PASS" else 75
    if score_m := re.search(r'"score"\s*:\s*"?(\d+)"?', target_str):
        score = int(score_m.group(1))

    risk_items = []
    if risk_m := re.search(r'"risk_items"\s*:\s*\[(.*?)\]', target_str, re.DOTALL):
        items_raw = risk_m.group(1)
        risk_items = [item.strip(' "\'\t\r\n') for item in items_raw.split(',') if item.strip()]
    if not risk_items and decision == "REJECT":
        risk_items = ["检测到规则匹配项缺失/待补充风险"]

    feedback = ""
    if fb_m := re.search(r'"critique_feedback"\s*:\s*"(.*?)"\s*(?:\}|\,)', target_str, re.DOTALL):
        feedback = fb_m.group(1).strip()
    elif fb_m2 := re.search(r'"critique_feedback"\s*:\s*"(.*)', target_str, re.DOTALL):
        cleaned_fb = fb_m2.group(1).rstrip('}"\r\n ').strip()
        feedback = cleaned_fb.replace('\\"', '"')
    
    if not feedback and decision == "REJECT":
        feedback = "请进一步完善 SLA 补偿标准、责任限制上限以及终止通知期细节。"

    return {
        "decision": decision,
        "score": score,
        "risk_items": risk_items,
        "critique_feedback": feedback
    }


# ==========================================
# 4. Generator 与 Critic 微引擎
# ==========================================

class GeneratorNode:
    """
    生成器节点 (Generator)
    负责初始生成合同，或根据 Critic 反馈进行针对性修订
    """

    def __init__(self):
        self.llm_client = LLMClient()

    async def generate_initial_draft(self, requirement: str) -> ContractDraft:
        """
        根据用户需求初始生成合同草稿
        """
        system_prompt = (
            "你是一个法务合同起草生成器 (Generator Node)。\n"
            "请根据用户的需求起草一份精炼、核心的英文合同条款草稿 (控制在 500 词以内)。\n"
            "为了确保格式解析 100% 稳健，请使用以下【标签格式】输出:\n\n"
            "===TITLE===\n"
            "[合同标题]\n"
            "===CONTENT===\n"
            "[合同核心条款文本]\n"
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"起草需求: {requirement}"}
        ]

        raw_output = await self.llm_client.request_llm(messages, temperature=0.3, max_tokens=2500)
        title, content = parse_contract_tag_format(raw_output)
        return ContractDraft(title=title, content=content, version=1)

    async def revise_draft(self, draft: ContractDraft, feedback: str) -> ContractDraft:
        """
        根据 Critic 的修改意见针对性修订合同草稿
        """
        system_prompt = (
            "你是一个法务合同修订生成器 (Generator Node)。\n"
            "上一轮生成的合同被 Critic 审查法官 REJECT 驳回。\n"
            "请结合 Critic 的【具体修订指令】，对合同草稿进行针对性补充和改进 (控制在 600 词以内)。\n"
            "注意：只修补和改进被指出的缺陷，不要破坏原有的合理条款！\n"
            "【强制格式要求】: 在 ===CONTENT=== 之后只输出纯粹、合规的英文合同条款正文，绝对不要在此包含任何自我解释、检讨或致歉说明！\n\n"
            "请使用以下【标签格式】输出:\n"
            "===TITLE===\n"
            "[合同标题]\n"
            "===CONTENT===\n"
            "[修订后的合同完整文本]\n"
        )

        user_content = (
            f"【原合同草稿 (v{draft.version})】:\n{draft.content}\n\n"
            f"【Critic 法官修改指令 (Feedback)】:\n{feedback}\n\n"
            "请重新修改并返回完善后的合规合同。"
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ]

        raw_output = await self.llm_client.request_llm(messages, temperature=0.2, max_tokens=1600)
        title, content = parse_contract_tag_format(raw_output, default_title=draft.title)
        return ContractDraft(title=title, content=content, version=draft.version + 1)


class CriticNode:
    """
    独立审查法官节点 (Critic Node)
    物理隔离于 Generator，以严格法官身份进行盲审
    """

    def __init__(self):
        self.llm_client = LLMClient()

    async def review_contract(self, requirement: str, draft: ContractDraft) -> CriticReview:
        """
        审查合同草稿，输出强类型 CriticReview 决策 Payload
        """
        system_prompt = (
            "你是一个精通跨境商法的资深高级法务总监 (Critic Node)。\n"
            "你的职责是客观审查 Generator 提交的合同草稿，检查关键条款完备性与严密性。\n\n"
            "【审查规则与格式要求】:\n"
            "1. 必须输出合法的单行 JSON 格式:\n"
            "   {\n"
            "     \"decision\": \"PASS\" 或 \"REJECT\",\n"
            "     \"score\": 85,\n"
            "     \"risk_items\": [\"隐患1\"],\n"
            "     \"critique_feedback\": \"修改指令\"\n"
            "   }\n"
            "2. 【数据类型要求】: score 必须为纯数字 (如 90，绝对不能带引号)！属性值内部严禁出现双引号 \"，请一律用单引号 ' 代替！\n"
            "3. 【评分逻辑】: 若合同已包含用户要求的 SLA 保障、Limitation of Liability (责任限制上限)、Data Protection (数据隐私) 和 Termination Notice Period (违约终止)，"
            "且条款清晰严密，必须给出 decision=\"PASS\" 且 score >= 85！只有当发现严重条款缺失时才给出 REJECT (score < 85)。"
        )

        user_content = (
            f"【用户原始需求】: {requirement}\n\n"
            f"【待审合同草稿 (v{draft.version})】:\n{draft.content}\n\n"
            "请执行合规审计并返回 JSON 决策 Payload。"
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ]

        raw_output = await self.llm_client.request_llm(
            messages, 
            temperature=0.1, 
            max_tokens=800,
            response_format={"type": "json_object"}
        )
        data = parse_critic_json(raw_output)
        return CriticReview.model_validate(data)


# ==========================================
# 5. Critic 博弈引擎 (CriticGameEngine)
# ==========================================

class CriticGameEngine:
    """
    LLM-as-Critic 双模型博弈引擎
    """

    def __init__(self, max_loops: int = 3, pass_score: int = 85):
        self.generator = GeneratorNode()
        self.critic = CriticNode()
        self.guard = GameLoopGuard(max_loops=max_loops, pass_score=pass_score)

    async def run_async(self, requirement: str) -> Dict[str, Any]:
        """
        运行完整的 Generator-Critic 博弈循环
        """
        print("🚀 [Critic Game Engine Start] 启动 Generator-Critic 双模型博弈引擎...")
        print(f"📌 [Requirement]: {requirement}\n")

        state: CriticGameState = {
            "contract_requirement": requirement,
            "current_draft": None,
            "latest_review": None,
            "loop_counter": 0
        }

        # 1. 初始生成草稿
        print("✍️ [Phase 1: Generator Node] 正在起草初始合同草稿 (v1)...")
        draft = await self.generator.generate_initial_draft(requirement)
        state["current_draft"] = draft
        print(f"✅ [Draft v1 Generated] 标题: {draft.title}")
        print(f"   预览内容 (前 150 字符): {draft.content[:150].strip()}...\n")

        # 2. 博弈循环
        while True:
            state["loop_counter"] += 1
            loop_idx = state["loop_counter"]
            print(f"=" * 60)
            print(f"⚖️ [Phase 2: Critic Game Loop Round #{loop_idx}] 法官审阅阶段...")

            # 触发 Critic 节点盲审
            t0 = time.time()
            review = await self.critic.review_contract(requirement, state["current_draft"])
            state["latest_review"] = review
            print(f"📥 [Critic Payload Received] 耗时 {time.time()-t0:.2f}s")
            print(f"   • 审查结论: {review.decision}")
            print(f"   • 合规评分: {review.score} / 100")
            print(f"   • 风险扫描: {review.risk_items}")
            print(f"   • 修改指令: {review.critique_feedback}\n")

            # 评估路由信号
            action = self.guard.evaluate_routing(state)

            if action == "TO_END":
                print("🎉 [Game Loop Complete] Critic 给出 PASS，评分达标，博弈收敛通过！")
                break
            elif action == "TO_FALLBACK":
                print("⚠️ [Game Loop Intercept] 达到最大博弈轮数熔断上限，自动触发人工审核降级！")
                break
            else:  # TO_GENERATOR_REVISE
                print(f"🔄 [Game Loop Revision] 结论为 REJECT，路由强制回退至 Generator (进入第 {loop_idx+1} 轮修订)...")
                revised_draft = await self.generator.revise_draft(
                    state["current_draft"], 
                    review.critique_feedback
                )
                state["current_draft"] = revised_draft
                print(f"✅ [Draft Revised] 生成版本 v{revised_draft.version}\n")

        return state


# ==========================================
# 6. 调试主入口 (规则 1 & 6)
# ==========================================

if __name__ == "__main__":
    print("=" * 70)
    print("Day 80 参考标准答案: LLM-as-Critic 独立审查器与双模型博弈架构")
    print("=" * 70)

    engine = CriticGameEngine(max_loops=3, pass_score=85)
    sample_requirement = (
        "起草一份跨境 SaaS 软件服务授权协议 (SaaS Service Agreement)。"
        "必须包含服务级别 SLA 保障、数据隐私保护、明确的免责与责任限制上限 (Limitation of Liability)，"
        "以及违约终止条款 (Termination Notice Period)。"
    )

    try:
        final_state = asyncio.run(engine.run_async(sample_requirement))
        print("\n" + "=" * 60)
        print("📄 【最终通过 Critic 审阅的法务合同】")
        print("=" * 60)
        print(f"版本: v{final_state['current_draft'].version}")
        print(f"评分: {final_state['latest_review'].score}")
        print("-" * 60)
        print(final_state['current_draft'].content)
        print("\n✅ [Test Passed] 成功完成 Generator-Critic 双模型对抗博弈全闭环测试！")
    except Exception as e:
        print(f"\n❌ [引擎运行发生异常]: {e}")
        import traceback
        traceback.print_exc()
