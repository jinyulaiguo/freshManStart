"""
Week 15 Day 102 参考标准答案: Faithfulness 幻觉检测探针 (faithfulness_impl.py)

===============================================================================
设计方案说明 (Architecture Design Specification)
===============================================================================

1. 设计意图 (Design Intent):
   RAG Agent 回复可能通顺但包含 Context 外编造事实。本模块实现 RAGAS 风格的
   Faithfulness 探针：强制 LLM 将 answer 拆解为原子 claims，逐条对照
   retrieved_contexts 判定是否支撑，分数 = |supported| / |claims|，禁止 LLM
   直接输出与 claims 不一致的随意分数。

2. 核心类与数据流结构 (Class & Data Flow):
   - FaithfulnessEvaluator:
     - _build_messages(): claims 审计 Judge Prompt
     - evaluate(): request_llm + parse_structured → ProbeScoreResult
     - verify_adversarial() / verify_positive(): 阈值门禁
   - FaithfulnessJudgeResponse / ClaimVerdict: contracts/schemas.py 契约

3. 核心用例设计意图 (Test Case Design Intent):
   固定 W14 蛋白质 LM 语料片段作为 Context，构造：
   - 忠实回复: 仅复述 Context 中的 F1=0.89 / AUROC=0.92 → score >= 0.8
   - 数字幻觉: F1 改为 0.99 → score <= 0.2
   - 张冠李戴: 将 ESM-2 结论安到 ProteinBERT → score <= 0.2
   - 无中生有: 编造 Quantum Attention → score <= 0.2
===============================================================================
"""

from __future__ import annotations

import asyncio
import os
import sys

# ── 路径注入 ──────────────────────────────────────────────────────────────
current_dir = os.path.dirname(os.path.abspath(__file__))
repo_root = os.path.abspath(os.path.join(current_dir, "../../.."))
w04_path = os.path.abspath(os.path.join(current_dir, "../../w04_prompt_and_http"))
w15_root = os.path.abspath(os.path.join(current_dir, ".."))

for p in (repo_root, w04_path, w15_root):
    if p not in sys.path:
        sys.path.append(p)

from utils import LLMClient
from middlewares.llm_reliability_adapter import parse_structured
from contracts.schemas import FaithfulnessJudgeResponse, ProbeScoreResult


# ═══════════════════════════════════════════════════════════════════════════
# FaithfulnessEvaluator 微引擎
# ═══════════════════════════════════════════════════════════════════════════

class FaithfulnessEvaluator:
    """
    Faithfulness 探针：检测 final_answer 相对 retrieved_contexts 的幻觉。

    Parameters
    ----------
    llm_client:
        Week 4 LLMClient 实例。
    temperature:
        Judge 采样温度，默认 0.1 保证 claims 拆解稳定。
    """

    ADVERSARIAL_MAX_SCORE = 0.2
    POSITIVE_MIN_SCORE = 0.8

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        temperature: float = 0.1,
    ):
        self.llm = llm_client or LLMClient()
        self.temperature = temperature

    def _build_messages(
        self,
        answer: str,
        contexts: list[str],
    ) -> list[dict[str, str]]:
        """
        构造 claims 级 Faithfulness 审计 Prompt。

        Returns
        -------
        list[dict[str, str]]
            OpenAI 风格 messages。
        """
        # 步骤 1：格式化 Context 段落
        ctx_block = "\n\n".join(
            f"[Context {i + 1}]\n{c}" for i, c in enumerate(contexts)
        )

        system_msg = (
            "你是严格的 RAG Faithfulness 审计法官。\n\n"
            "## 任务\n"
            "1. 将 Agent 回复拆解为若干条原子事实声明 (claims)，每条只含一个可验证事实；\n"
            "2. 对每条 claim，检查是否能在给定 Context 中找到直接支撑；\n"
            "3. 有支撑 → supported=true，并摘录 evidence_snippet；\n"
            "4. 无支撑、数字被篡改、张冠李戴、无中生有 → supported=false，evidence_snippet=null；\n"
            "5. 禁止编造 Context 中不存在的 evidence。\n\n"
            "## 输出格式\n"
            "严格返回 JSON 对象 (不含 markdown / 思考过程)，字段：\n"
            "- claims: [{claim, supported, evidence_snippet, reason}, ...] 至少 1 条\n"
            "- summary: 幻觉审计摘要\n"
            "注意：不要输出总分；总分由系统按 supported/total 计算。"
        )

        user_msg = (
            f"## Retrieved Contexts\n{ctx_block}\n\n"
            f"## Agent Answer\n{answer}\n\n"
            "请拆解 claims 并逐条判定是否被 Context 支撑。"
        )

        return [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ]

    async def evaluate(
        self,
        test_case_id: str,
        answer: str,
        contexts: list[str],
    ) -> ProbeScoreResult:
        """
        对单条回复执行 Faithfulness 评测。

        Parameters
        ----------
        test_case_id:
            用例 ID，写入结果便于 Diff。
        answer:
            Agent final_answer。
        contexts:
            检索 Context 段落列表。

        Returns
        -------
        ProbeScoreResult
            metric_name=\"faithfulness\" 的探针结果。
        """
        if not contexts:
            return ProbeScoreResult(
                metric_name="faithfulness",
                test_case_id=test_case_id,
                score=0.0,
                passed=False,
                unsupported_claims=["(no retrieved contexts)"],
                summary="无 Context 可供审计，Faithfulness 记 0",
            )

        # 步骤 1：构造 Prompt 并请求 LLM
        messages = self._build_messages(answer, contexts)
        raw = await self.llm.request_llm(
            messages=messages,
            temperature=self.temperature,
            max_tokens=4096,
            response_format={"type": "json_object"},
        )

        # 步骤 2：结构化解析（剥离 <think> 等污染）
        judge = parse_structured(raw, FaithfulnessJudgeResponse)

        # 步骤 3：分数由 claims 确定性推导
        score = judge.score
        unsupported = [c.claim for c in judge.unsupported_claims]

        return ProbeScoreResult(
            metric_name="faithfulness",
            test_case_id=test_case_id,
            score=score,
            passed=score >= self.POSITIVE_MIN_SCORE,
            unsupported_claims=unsupported,
            summary=judge.summary,
            raw_judge=judge.model_dump(),
        )

    def verify_adversarial(self, result: ProbeScoreResult) -> bool:
        """假回复过关：score <= 0.2。"""
        ok = result.score <= self.ADVERSARIAL_MAX_SCORE
        tag = "PASS" if ok else "FAIL"
        print(
            f"   [{tag}] 对抗校验: score={result.score:.4f} "
            f"{'<=' if ok else '>'} {self.ADVERSARIAL_MAX_SCORE}"
        )
        return ok

    def verify_positive(self, result: ProbeScoreResult) -> bool:
        """忠实回复过关：score >= 0.8。"""
        ok = result.score >= self.POSITIVE_MIN_SCORE
        tag = "PASS" if ok else "FAIL"
        print(
            f"   [{tag}] 正样本校验: score={result.score:.4f} "
            f"{'>=' if ok else '<'} {self.POSITIVE_MIN_SCORE}"
        )
        return ok


# ═══════════════════════════════════════════════════════════════════════════
# 固定对抗样本 (W14 蛋白质 LM 场景)
# ═══════════════════════════════════════════════════════════════════════════

DEMO_CONTEXTS = [
    (
        "ESM-2 采用 Masked Language Modeling (MLM) 在 UniRef50 上预训练，"
        "contact prediction F1 达到 0.89，在 remote homology 判别任务上表现更优。"
    ),
    (
        "ProteinBERT 采用双头架构 (MLM + GO 注释预测头)，"
        "在 GO term prediction 中 AUROC=0.92，显式利用功能注释监督信号。"
    ),
]

SAMPLES: list[tuple[str, str, str, str]] = [
    # (label, test_case_id, answer, expect)  expect in {positive, adversarial}
    (
        "忠实复述",
        "research_faithful",
        (
            "ESM-2 使用 MLM 在 UniRef50 预训练，contact prediction F1 为 0.89。"
            "ProteinBERT 双头架构在 GO term prediction 上 AUROC=0.92。"
        ),
        "positive",
    ),
    (
        "数字幻觉",
        "research_num_halluc",
        (
            "ESM-2 的 contact prediction F1 高达 0.99，远超所有已知文献记录。"
            "ProteinBERT 的 GO AUROC 达到 0.999。"
        ),
        "adversarial",
    ),
    (
        "张冠李戴",
        "research_swap",
        (
            "ProteinBERT 在 UniRef50 上做 MLM 预训练，contact prediction F1 达到 0.89。"
            "ESM-2 则采用双头架构，GO term prediction AUROC=0.92。"
        ),
        "adversarial",
    ),
    (
        "无中生有",
        "research_fabricate",
        (
            "ESM-2 引入了 Quantum Attention 与 Hyperbolic Embedding，"
            "使 contact prediction 突破人类极限；这些技术均已写入原始论文摘要。"
        ),
        "adversarial",
    ),
]


def print_result(label: str, result: ProbeScoreResult) -> None:
    """终端输出单条探针明细。"""
    print(f"\n── {label} ({result.test_case_id}) ──")
    print(f"   score={result.score:.4f}  passed={result.passed}")
    print(f"   summary: {result.summary[:120]}")
    if result.unsupported_claims:
        print("   unsupported:")
        for claim in result.unsupported_claims[:5]:
            print(f"     · {claim[:80]}")


# ═══════════════════════════════════════════════════════════════════════════
# 标准答案调试主入口
# ═══════════════════════════════════════════════════════════════════════════

async def main() -> None:
    print("=" * 70)
    print("🔬 Day 102 标准答案: FaithfulnessEvaluator 幻觉检测探针")
    print("=" * 70)

    evaluator = FaithfulnessEvaluator(temperature=0.1)
    all_pass = True

    for label, case_id, answer, expect in SAMPLES:
        print(f"\n🎯 评测场景: {label}")
        result = await evaluator.evaluate(case_id, answer, DEMO_CONTEXTS)
        print_result(label, result)

        if expect == "positive":
            ok = evaluator.verify_positive(result)
        else:
            ok = evaluator.verify_adversarial(result)

        if not ok:
            all_pass = False

    print(
        f"\n📊 过关验证: "
        f"{'✅ 正样本高分 + 三类假回复极低分全部通过' if all_pass else '❌ 存在场景未达阈值'}"
    )


if __name__ == "__main__":
    asyncio.run(main())
