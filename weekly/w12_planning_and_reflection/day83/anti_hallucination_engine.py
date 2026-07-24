"""
Day 83 参考标准答案: 语义相似度自检与输出文本防幻觉校对

【系统设计方案说明】
1. 设计意图 (Design Intent):
   构建生产级 NLI 语义蕴含防幻觉校对引擎 (NLI Anti-Hallucination Proofreading Engine)。
   解决企业级 RAG 问答系统中大模型因先验知识干预或长文本逻辑混淆而产生的捏造数据 (Neutral)
   或事实矛盾 (Contradiction) 幻觉问题。通过引入原子陈述提取 (Claim Extraction) 与 NLI 逻辑对齐校验，
   实现对大模型生成物在物理边界上的强力语义约束。

2. 类与函数结构 (Class & Function Architecture):
   - ClaimEvaluation: Pydantic 模型，定义单点事实陈述的 NLI 推理结果 (claim_text, label, reasoning)。
   - AntiHallucinationReport: Pydantic 模型，定义全局校对报告 (overall_status, claim_evaluations, unsupported_claims, correction_guidance)。
   - AtomicClaimsPayload: Pydantic 模型，用于 Extractor 强类型解析提取出的断言列表。
   - AntiHallucinationState: TypedDict 状态容器，维护参考 Context、问题、当前草稿、校对报告与重修计数器。
   - ClaimExtractorNode: 原子陈述提取节点，将复合句回答切分为单点事实断言数组。
   - AntiHallucinationVerifier: NLI 语义蕴含校验器，逐句与 Context 计算 ENTAILMENT / CONTRADICTION / NEUTRAL。
   - AnswerGeneratorNode: 回答生成/重修节点，根据校对指引进行文本重修。
   - AntiHallucinationGuard: 条件路由控制器，精准控制放行 (TO_END)、重修纠偏 (TO_GENERATOR_CORRECTION) 或熔断 (TO_FALLBACK)。
   - AntiHallucinationEngine: 主控调度引擎，串联控制流并驱动防幻觉闭环演练。

3. 关键数据流流向 (Data Flow):
   Context + Question ➔ AnswerGeneratorNode ➔ Raw Answer (Attempt #1: 含 Q3 预估幻觉)
     ➔ ClaimExtractorNode ➔ Atomic Claims: [Claim 1 (Q2营收), Claim 2 (Q2净利), Claim 3 (Q3预估)]
     ➔ AntiHallucinationVerifier ➔ NLI Label: Claim 1&2 (ENTAILMENT), Claim 3 (NEUTRAL)
     ➔ Report: overall_status = "HALLUCINATION_DETECTED"
     ➔ AntiHallucinationGuard ➔ AnswerGeneratorNode (Inject Correction Guidance: 剔除 Q3 预估)
     ➔ Attempt #2 Draft (Clean) ➔ Verifier ➔ All ENTAILMENT ➔ AntiHallucinationGuard ➔ END Node

4. 核心用例设计意图 (Test Case Design Intent):
   选取“企业 2025 年 Q2 财报问答”作为真实验证场景：
   - 参考 Context 明确写明：`Acme 公司 Q2 营收 1200 万美元，净利润 200 万美元。未提及 Q3 预估数据。`
   - 验证点 1：测试 Generator 在首次生成时混入了先验知识幻觉（如额外捏造了“预计 Q3 营收将达到 1500 万美元”）。
   - 验证点 2：测试 ClaimExtractorNode 能否准确切分出独立的原子事实断言。
   - 验证点 3：测试 AntiHallucinationVerifier 能否独立识别出“Q3 预估数据”在 Context 中未提及，并精准标记为 `NEUTRAL` 幻觉。
   - 验证点 4：测试 Guard 与 Generator 能否根据校对报告在第二轮生成中彻底剔除该无根据陈述，实现 100% 对齐通关。
"""

import re
import asyncio
from typing import Dict, List, Any, Optional, Literal, TypedDict
from pydantic import BaseModel, Field

# 从公共工具与中间件导入 API 与结构化提取功能 (规则 12, 20 & 21)
from weekly.w04_prompt_and_http.utils import load_env_file, LLMClient
from middlewares.llm_reliability_adapter import parse_structured

# 加载环境变量
load_env_file()


# ==========================================
# 1. 强类型 Schema 与 State 容器契约
# ==========================================

class ClaimEvaluation(BaseModel):
    """
    单个原子事实陈述的 NLI 推理结果契约
    """
    claim_text: str = Field(description="抽取的单点事实陈述文本")
    label: Literal["ENTAILMENT", "CONTRADICTION", "NEUTRAL"] = Field(
        description="NLI 推理标签: ENTAILMENT(蕴含/完全符合), CONTRADICTION(与 Context 矛盾), NEUTRAL(无根无据/凭空捏造)"
    )
    reasoning: str = Field(description="基于 Context 的逻辑推导与判定依据")


class AntiHallucinationReport(BaseModel):
    """
    全局防幻觉校对报告契约
    """
    overall_status: Literal["PASS", "HALLUCINATION_DETECTED"] = Field(description="综合校对结论: PASS 或 HALLUCINATION_DETECTED")
    claim_evaluations: List[ClaimEvaluation] = Field(default_factory=list, description="每个断言的 NLI 详细评估列表")
    unsupported_claims: List[str] = Field(default_factory=list, description="被判定为 CONTRADICTION 或 NEUTRAL 的无效/幻觉陈述列表")
    correction_guidance: str = Field(description="针对性的文本纠偏指令，供下一轮 Generator 剔除或修正幻觉")


class AtomicClaimsPayload(BaseModel):
    """
    Extractor 提取出的原子事实断言列表 Payload
    """
    claims: List[str] = Field(description="从回答文本中拆分出的单点事实断言数组")


class AntiHallucinationState(TypedDict):
    """
    状态图全局 TypedDict 容器
    """
    rag_context: str
    user_question: str
    current_answer: str
    verification_report: Optional[AntiHallucinationReport]
    loop_counter: int  # 纠偏重修计数器
    is_success: bool


# ==========================================
# 2. 核心微引擎实现
# ==========================================

class ClaimExtractorNode:
    """
    原子陈述提取节点：将段落回答切分为独立的单点事实断言列表
    """

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.client = llm_client or LLMClient()

    async def extract_claims(self, answer: str) -> List[str]:
        """
        调用 LLM 从回答中抽取单点事实陈述数组
        """
        cleaned_answer = re.sub(r"<think>.*?</think>", "", answer, flags=re.DOTALL | re.IGNORECASE).strip()
        prompt = f"""你是一名严谨的文本分析专家。请将以下回答段落拆解为互相独立的单点原子事实陈述 (Atomic Claims)。

【待拆解回答段落】:
{cleaned_answer}

【要求】:
1. 将回答中的主张、数字、结论拆分为简短、独立的单点陈述句。
2. 忽略问候语、标题 (#)、Markdown 表格 (|)、块引用 (>) 或连接词，仅保留有实际事实含义的陈述。
3. 请直接输出符合 JSON 结构的文本，严禁包含 <think> 标签！
"""
        messages = [
            {"role": "system", "content": "你是一名精通文本原子陈述拆解的专家。请输出 JSON 强类型契约。"},
            {"role": "user", "content": prompt}
        ]

        try:
            raw_text = await self.client.request_llm(messages=messages, temperature=0.1)
            payload: AtomicClaimsPayload = parse_structured(raw_text=raw_text, response_model=AtomicClaimsPayload)
            valid_claims = []
            for c in payload.claims:
                c_str = c.strip()
                if not c_str or c_str.startswith(("#", "|", ">", "---", "```", "<think>", "Let me", "The user", "According")):
                    continue
                cleaned = re.sub(r"[\*#>\-\|\`]", "", c_str).strip()
                if len(cleaned) > 3:
                    valid_claims.append(cleaned)
            return valid_claims if valid_claims else [cleaned_answer]
        except Exception:
            # 降级备用：基于句号与换行拆分并过滤 Markdown 杂质
            raw_lines = [s.strip() for s in cleaned_answer.replace("！", "。").replace("\n", "。").split("。") if s.strip()]
            valid_sentences = []
            for line in raw_lines:
                line_str = line.strip()
                if not line_str or line_str.startswith(("#", "|", ">", "---", "```", "<think>")):
                    continue
                cleaned = re.sub(r"[\*#>\-\|\`]", "", line_str).strip()
                if len(cleaned) > 3:
                    valid_sentences.append(cleaned)
            return valid_sentences if valid_sentences else [cleaned_answer]


class AntiHallucinationVerifier:
    """
    NLI 语义蕴含校验器：逐句与 Context 计算 NLI 逻辑对齐
    """

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.client = llm_client or LLMClient()

    async def verify(self, rag_context: str, claims: List[str]) -> AntiHallucinationReport:
        """
        调用 LLM / NLI 逻辑对 claims 列表进行强类型校验
        """
        prompt = f"""你是一名极其苛刻的 RAG 防幻觉校验专家。请严格对照【参考 Context】，对【待校验断言】列表逐一计算 NLI (自然语言推理) 逻辑标签。

【参考 Context (物理唯一事实真理)】:
{rag_context}

【待校验断言列表】:
{claims}

【NLI 判定标准】:
1. ENTAILMENT (蕴含): 断言中的事实 100% 能由 Context 直接推导出来。
2. CONTRADICTION (矛盾): 断言的结论与 Context 中的事实明确冲突。
3. NEUTRAL (中立/凭空捏造): Context 中完全没有提及该断言的内容（属于无根据推测）。

【极重要 Schema 契约】:
- label 字段必须只能为 "ENTAILMENT", "CONTRADICTION", "NEUTRAL" 三个字符串之一，严禁自行扩展！
- overall_status 必须只能为 "PASS" (当所有断言均为 ENTAILMENT 时) 或 "HALLUCINATION_DETECTED" (当存在任何 CONTRADICTION 或 NEUTRAL 时)。
- 请直接输出符合 JSON 结构的文本，严禁包含 <think> 标签！
"""
        messages = [
            {"role": "system", "content": "你是一名精通 NLI 语义蕴含校对的专家。请输出符合 Schema 契约的 JSON 校对报告。"},
            {"role": "user", "content": prompt}
        ]

        try:
            raw_text = await self.client.request_llm(messages=messages, temperature=0.1)
            cleaned_text = re.sub(r"<think>.*?</think>", "", raw_text, flags=re.DOTALL | re.IGNORECASE).strip()
            cleaned_text = re.sub(r',\s*""\s*\}', '}', cleaned_text)
            report: AntiHallucinationReport = parse_structured(raw_text=cleaned_text, response_model=AntiHallucinationReport)
            return report
        except Exception as e:
            print(f"⚠️ [AntiHallucinationVerifier] NLI 校对解析捕获异常 ({type(e).__name__}: {e})，触发保底风控。")
            return AntiHallucinationReport(
                overall_status="HALLUCINATION_DETECTED",
                claim_evaluations=[],
                unsupported_claims=["校对中间件异常，默认触发严格复查"],
                correction_guidance="请严格对照 Context 重新生成，剔除任何未在 Context 中提及的推测性数字或信息。"
            )


class AnswerGeneratorNode:
    """
    回答生成/重修节点：结合 Context 与纠偏指令生成严格对齐的回答
    """

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.client = llm_client or LLMClient()

    async def generate_answer(
        self,
        rag_context: str,
        user_question: str,
        correction_guidance: Optional[str] = None
    ) -> str:
        """
        生成或重修回答，强制约束于 Context 物理边界
        """
        if not correction_guidance:
            # 轮次 #1 初始生成：模拟大模型因先验知识干预带入轻微幻觉 (如额外说明未提及的 Q3 预测)
            system_prompt = "你是一名问答助手。请根据 Context 回答用户问题。"
            user_prompt = f"参考 Context:\n{rag_context}\n用户问题: {user_question}\n提示：请全面回答，可以适当对后续季度进行合理展望。"
        else:
            # 轮次 #2+ 纠偏重修：强制施加 NLI 防幻觉避坑规则
            system_prompt = f"""你是一名零幻觉 (Zero-Hallucination) 极度严谨的问答引擎。
你的回答必须 100% 物理受限于 Context 文本，绝对不允许包含任何 Context 中没有提及的数字、时间或预估。

【上一轮检测出的幻觉纠偏指令】：
{correction_guidance}

【极重要约束】：
1. 彻底删除所有被标记为 NEUTRAL (无根据) 或 CONTRADICTION (矛盾) 的陈述！
2. 只保留 Context 中明确记载的事实。如果不确定，直接说明 Context 未提及。
"""
            user_prompt = f"参考 Context:\n{rag_context}\n用户问题: {user_question}\n请重新给出修正后的可靠回答："

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        raw_response = await self.client.request_llm(messages=messages, temperature=0.2)
        # 物理剥离大模型返回的 <think> 思考过程标签，防止思考链污染后端的 Claim 提取与 NLI 校验
        cleaned_response = re.sub(r"<think>.*?</think>", "", raw_response, flags=re.DOTALL | re.IGNORECASE).strip()
        return cleaned_response


class AntiHallucinationGuard:
    """
    纠偏条件路由控制器
    """

    def __init__(self, max_retries: int = 3):
        self.max_retries = max_retries

    def evaluate_routing(self, state: AntiHallucinationState) -> str:
        """
        判断下一步路由流向

        :return: "TO_END" | "TO_GENERATOR_CORRECTION" | "TO_FALLBACK"
        """
        report = state["verification_report"]
        if report and report.overall_status == "PASS":
            return "TO_END"

        if state["loop_counter"] >= self.max_retries:
            return "TO_FALLBACK"

        return "TO_GENERATOR_CORRECTION"


class AntiHallucinationEngine:
    """
    防幻觉校对引擎主控调度器
    """

    def __init__(self, max_retries: int = 3):
        self.generator = AnswerGeneratorNode()
        self.extractor = ClaimExtractorNode()
        self.verifier = AntiHallucinationVerifier()
        self.guard = AntiHallucinationGuard(max_retries=max_retries)

    async def run(self, rag_context: str, user_question: str) -> AntiHallucinationState:
        """
        执行完整的 NLI 防幻觉校对自愈闭环
        """
        state: AntiHallucinationState = {
            "rag_context": rag_context,
            "user_question": user_question,
            "current_answer": "",
            "verification_report": None,
            "loop_counter": 0,
            "is_success": False
        }

        print("=" * 70)
        print("🚀 启动 NLI 语义蕴含防幻觉校对引擎")
        print(f"📄 参考 Context:\n{rag_context}")
        print(f"❓ 用户问题: {user_question}")
        print("=" * 70)

        correction_guidance = None

        while True:
            state["loop_counter"] += 1
            current_loop = state["loop_counter"]
            print(f"\n🔄 --- 尝试/重修轮次 #{current_loop} ---")

            # 1. Generator 生成回答
            print("🤖 [AnswerGeneratorNode] 正在生成回答...")
            answer_draft = await self.generator.generate_answer(
                rag_context=state["rag_context"],
                user_question=state["user_question"],
                correction_guidance=correction_guidance
            )
            state["current_answer"] = answer_draft
            print(f"📝 生成的回答草稿:\n\"{answer_draft}\"\n")

            # 2. ClaimExtractor 切分原子陈述
            print("🔍 [ClaimExtractorNode] 正在拆解单点事实断言 (Atomic Claims)...")
            claims = await self.extractor.extract_claims(answer_draft)
            print(f"📌 提取出的原子断言 ({len(claims)} 条):")
            for i, c in enumerate(claims):
                print(f"   [{i+1}] {c}")

            # 3. NLI Verifier 逻辑校验
            print("\n⚖️ [AntiHallucinationVerifier] 正在对照 Context 进行 NLI 蕴含校验...")
            report = await self.verifier.verify(state["rag_context"], claims)
            state["verification_report"] = report

            print(f"📊 [NLI 校对结论]: {report.overall_status}")
            for eval_item in report.claim_evaluations:
                icon = "✅" if eval_item.label == "ENTAILMENT" else ("❌" if eval_item.label == "CONTRADICTION" else "⚠️")
                print(f"   {icon} [{eval_item.label}] '{eval_item.claim_text}' ➔ 依据: {eval_item.reasoning}")

            # 4. Guard 判定条件路由
            route = self.guard.evaluate_routing(state)

            if route == "TO_END":
                state["is_success"] = True
                print("\n🎉 [AntiHallucinationEngine] 语义蕴含校验 100% 通过！回答无任何幻觉捏造。")
                break
            elif route == "TO_FALLBACK":
                state["is_success"] = False
                print(f"\n⚠️ [AntiHallucinationEngine] 达到最大重估次数 ({self.guard.max_retries})，触发严格降级拦截。")
                break
            elif route == "TO_GENERATOR_CORRECTION":
                print(f"\n⚡ [AntiHallucinationGuard] 发现幻觉陈述 ({len(report.unsupported_claims)} 条)，强制路由重修！")
                print(f"💡 [纠偏指令]: {report.correction_guidance}")
                correction_guidance = report.correction_guidance

        return state


# ==========================================
# 3. 运行入口 (规则 6 统一规范)
# ==========================================

async def main():
    rag_context = """
Acme Industrial Corp 2025 年 Q2 财报摘要：
1. 财务表现：总营收 1200 万美元，净利润 200 万美元，SaaS 业务营收同比增长 40%。
2. 业务运营：新增企业级客户 15 家，员工总数保持 150 人不变。
3. 注意事项：公司管理层明确声明本次报告未包含或预测 2025 年 Q3 的财务指标。
"""

    user_question = "请总结 Acme 公司 Q2 的财报表现，并说明管理层对 Q3 业绩的预估是多少？"

    engine = AntiHallucinationEngine(max_retries=3)
    final_state = await engine.run(rag_context, user_question)

    print("\n" + "=" * 70)
    print("📊 防幻觉校对引擎运行总结")
    print("=" * 70)
    print(f"最终校验通过: {final_state['is_success']}")
    print(f"总迭代轮次: {final_state['loop_counter']}")
    print("\n最终交付给用户的无幻觉可靠回答:")
    print(final_state["current_answer"])


if __name__ == "__main__":
    asyncio.run(main())
