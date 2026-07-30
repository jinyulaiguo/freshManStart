"""
Week 15 Day 102 学员练习模版: Faithfulness / Relevance 双探针评测 (practice.py)

===============================================================================
练习说明 (Exercise Specification)
===============================================================================
本练习目标是实现两个物理隔离的 LLM-as-Judge 评测探针：
- FaithfulnessEvaluator: 将 answer 拆解为 claims，逐条对照 retrieved_contexts 判定支撑，
  分数 = supported / total（禁止 LLM 随意给分）。
- RelevanceEvaluator: 判定 answer 是否切实解答 query，输出 0-1 分与缺失方面。

学员需要补充以下关键方法：
1. FaithfulnessEvaluator._build_messages(): 构造 claims 审计 Prompt。
2. FaithfulnessEvaluator.evaluate(): LLM 调用 + parse_structured + 组装 ProbeScoreResult。
3. RelevanceEvaluator._build_messages(): 构造切题判定 Prompt。
4. RelevanceEvaluator.evaluate(): LLM 调用 + parse_structured + 组装 ProbeScoreResult。
5. 两探针的阈值校验辅助 (verify_adversarial / verify_positive)。

请根据提示完成 TODO！对照标准答案：
  evaluators/faithfulness_impl.py · evaluators/relevance_impl.py
===============================================================================
"""

from __future__ import annotations

import asyncio
import os
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
repo_root = os.path.abspath(os.path.join(current_dir, "../../.."))
w04_path = os.path.abspath(os.path.join(current_dir, "../../w04_prompt_and_http"))
w15_root = os.path.abspath(os.path.join(current_dir, ".."))

for p in (repo_root, w04_path, w15_root):
    if p not in sys.path:
        sys.path.append(p)

from utils import LLMClient
from contracts.schemas import ProbeScoreResult


class FaithfulnessEvaluator:
    """
    Faithfulness 探针：Context 外幻觉检测

    分数由 claims 支撑比例确定性计算。
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
        TODO 1: 构造 Faithfulness Judge Prompt

        要求：
        1. System: 要求将 answer 拆为原子 claims，逐条对照 Context 判定 supported；
        2. 输出 JSON: claims[{claim, supported, evidence_snippet, reason}], summary；
        3. User: 注入 contexts 与 answer；
        4. 明确禁止编造 evidence，无支撑时 supported=false。
        """
        # ---------------------------------------------------------------------
        # TODO: 请在此处实现 Faithfulness Prompt 构造
        # ---------------------------------------------------------------------
        raise NotImplementedError("TODO 1: 请实现 FaithfulnessEvaluator._build_messages！")

    async def evaluate(
        self,
        test_case_id: str,
        answer: str,
        contexts: list[str],
    ) -> ProbeScoreResult:
        """
        TODO 2: Faithfulness 单次评测

        要求：
        1. 调用 _build_messages；
        2. self.llm.request_llm (temperature=self.temperature, response_format json_object)；
        3. parse_structured → FaithfulnessJudgeResponse；
        4. score = response.score；passed = score >= POSITIVE_MIN_SCORE；
        5. 返回 ProbeScoreResult(metric_name=\"faithfulness\", ...)。
        """
        # ---------------------------------------------------------------------
        # TODO: 请在此处实现 Faithfulness 评测逻辑
        # ---------------------------------------------------------------------
        raise NotImplementedError("TODO 2: 请实现 FaithfulnessEvaluator.evaluate！")

    def verify_adversarial(self, result: ProbeScoreResult) -> bool:
        """
        TODO 5a: 假回复必须 score <= ADVERSARIAL_MAX_SCORE (0.2)
        """
        raise NotImplementedError("TODO 5a: 请实现 Faithfulness 对抗样本校验！")


class RelevanceEvaluator:
    """
    Relevance 探针：Query–Answer 切题检测
    """

    OFF_TOPIC_MAX_SCORE = 0.3
    ON_TOPIC_MIN_SCORE = 0.7

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        temperature: float = 0.1,
    ):
        self.llm = llm_client or LLMClient()
        self.temperature = temperature

    def _build_messages(
        self,
        query: str,
        answer: str,
    ) -> list[dict[str, str]]:
        """
        TODO 3: 构造 Relevance Judge Prompt

        要求：
        1. System: 只判切题性，不因指标深度/同一基准不足而过度压分；
           切题 >=0.8，部分切题 0.4~0.7，答非所问 <=0.3；
        2. 输出 JSON: score(0-1), is_on_topic, missing_aspects, rationale；
        3. User: 注入 query 与 answer。
        """
        # ---------------------------------------------------------------------
        # TODO: 请在此处实现 Relevance Prompt 构造
        # ---------------------------------------------------------------------
        raise NotImplementedError("TODO 3: 请实现 RelevanceEvaluator._build_messages！")

    async def evaluate(
        self,
        test_case_id: str,
        query: str,
        answer: str,
    ) -> ProbeScoreResult:
        """
        TODO 4: Relevance 单次评测

        要求：
        1. 调用 _build_messages + request_llm + parse_structured(RelevanceJudgeResponse)；
        2. 组装 ProbeScoreResult(metric_name=\"relevance\", ...)。
        """
        # ---------------------------------------------------------------------
        # TODO: 请在此处实现 Relevance 评测逻辑
        # ---------------------------------------------------------------------
        raise NotImplementedError("TODO 4: 请实现 RelevanceEvaluator.evaluate！")

    def verify_off_topic(self, result: ProbeScoreResult) -> bool:
        """
        TODO 5b: 偏题回复必须 score <= OFF_TOPIC_MAX_SCORE (0.3)
        """
        raise NotImplementedError("TODO 5b: 请实现 Relevance 偏题样本校验！")


# ===============================================================================
# 调试主入口
# ===============================================================================

DEMO_CONTEXTS = [
    "ESM-2 采用 Masked Language Modeling 在 UniRef50 上预训练，contact prediction F1 达到 0.89。",
    "ProteinBERT 采用双头架构 (MLM + GO 注释预测)，GO term prediction AUROC=0.92。",
]

DEMO_QUERY = "请对比 ESM-2 与 ProteinBERT 的定量指标差异。"


async def main() -> None:
    print("=" * 70)
    print("📝 运行 Day 102 学员练习调试入口 (practice.py)")
    print("   Faithfulness / Relevance 双探针评测")
    print("=" * 70)

    faith = FaithfulnessEvaluator()
    relev = RelevanceEvaluator()

    hallucinated = (
        "ESM-2 的 contact prediction F1 高达 0.99，远超文献记载。"
        "ProteinBERT 使用了未在语料中出现的 Quantum Attention 机制。"
    )

    try:
        f_result = await faith.evaluate("research_hallucination", hallucinated, DEMO_CONTEXTS)
        print(f"Faithfulness(假回复)={f_result.score:.3f} passed_adv={faith.verify_adversarial(f_result)}")

        r_result = await relev.evaluate(
            "research_offtopic",
            DEMO_QUERY,
            "今天天气晴朗，适合户外运动，与蛋白质模型无关。",
        )
        print(f"Relevance(偏题)={r_result.score:.3f} passed_off={relev.verify_off_topic(r_result)}")

    except NotImplementedError as e:
        print(f"\n📌 [TODO 拦截提示]: {e}")
        print("💡 提示: 请打开 `weekly/w15_eval_system/day102/practice.py` 完成 TODO。")
        print("💡 参考: `evaluators/faithfulness_impl.py` 与 `evaluators/relevance_impl.py`。")


if __name__ == "__main__":
    asyncio.run(main())
