"""
Week 15 Day 100 学员练习模版: G-Eval LLM-as-Judge 专业度评测引擎 (practice.py)

===============================================================================
练习说明 (Exercise Specification)
===============================================================================
本练习目标是实现符合 G-Eval 论文规范的 LLM-as-Judge 评测微引擎，对 W14 Research
Agent 的回复专业度进行 Rubric + CoT 量化打分，并通过多次独立采样验证收敛性。

学员需要补充 GEvalJudge 中以下关键方法：
1. `_build_evaluation_messages()`: 构造含 Rubric 细则与 CoT 步骤的 Judge 提示词。
2. `score_once()`: 单次 LLM Judge 调用 + parse_structured 结构化解析。
3. `_compute_weighted_aggregate()`: 多次采样分数的加权均值与标准差计算。
4. `evaluate_professionalism()`: 并发多次独立打分并聚合。
5. `verify_convergence()`: 验证归一化分数标准差 < 0.2。

请根据提示完成 TODO 部分的代码实现！
完成后可对照参考标准答案 `evaluators/g_eval_judge_impl.py`。
===============================================================================
"""

import os
import sys
import asyncio
from dataclasses import dataclass, field
from typing import Any

current_dir = os.path.dirname(os.path.abspath(__file__))
repo_root = os.path.abspath(os.path.join(current_dir, "../../.."))
w04_path = os.path.abspath(os.path.join(current_dir, "../../w04_prompt_and_http"))
w15_root = os.path.abspath(os.path.join(current_dir, ".."))

for p in (repo_root, w04_path, w15_root):
    if p not in sys.path:
        sys.path.append(p)

from utils import LLMClient
from contracts.schemas import GEvalJudgeResponse, GEvalAggregateResult


@dataclass
class RubricScoreBand:
    """Rubric 单个分数段的判定标准"""
    score: int
    label: str
    criteria: str


@dataclass
class GEvalRubric:
    """G-Eval 评估细则 (Evaluation Rubric)"""
    metric_name: str
    criteria_description: str
    score_bands: list[RubricScoreBand] = field(default_factory=list)
    cot_step_templates: list[str] = field(default_factory=list)


# W14 Research Agent 专业度 Rubric (预置，学员可直接使用)
PROFESSIONALISM_RUBRIC = GEvalRubric(
    metric_name="professionalism",
    criteria_description="评估 AI 研究助手回复的学术论文级专业表述质量",
    score_bands=[
        RubricScoreBand(1, "外行", "术语误用、逻辑混乱、无学术引用结构"),
        RubricScoreBand(2, "入门", "基本可读但缺乏深度，无定量指标支撑"),
        RubricScoreBand(3, "合格", "术语基本正确，有简单对比但论证不完整"),
        RubricScoreBand(4, "专业", "引用准确、对比清晰、含定量指标与方法论区分"),
        RubricScoreBand(5, "卓越", "论证严密、多维度对比、含 Scaling/架构/任务类型细分"),
    ],
    cot_step_templates=[
        "识别回复中的核心论点与关键结论",
        "检查蛋白质语言模型领域术语使用是否准确",
        "评估是否包含定量性能指标 (F1, AUROC, Spearman ρ 等)",
        "评估论证结构是否完整 (对比维度、方法论区分、结论有据)",
        "对照 Rubric 给出 1-5 分最终评分",
    ],
)


class GEvalJudge:
    """
    G-Eval LLM-as-Judge 评测微引擎

    基于 Rubric + CoT 多次独立采样，计算加权均值与收敛标准差。
    """

    CONVERGENCE_STD_THRESHOLD = 0.2

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        sample_count: int = 5,
        temperature: float = 0.2,
    ):
        self.llm = llm_client or LLMClient()
        self.sample_count = sample_count
        self.temperature = temperature

    def _build_evaluation_messages(
        self,
        query: str,
        answer: str,
        rubric: GEvalRubric,
    ) -> list[dict[str, str]]:
        """
        TODO 1: 构造 G-Eval Judge 提示词 Messages

        要求：
        1. System 消息注入 metric_name、criteria_description、score_bands 细则；
        2. 列出 cot_step_templates 作为强制推理步骤；
        3. User 消息包含 query 与 answer；
        4. 要求输出 JSON 对象 (evaluation_steps, chain_of_thought_summary, score, score_rationale)。
        """
        # ---------------------------------------------------------------------
        # TODO: 请在此处实现 Judge 提示词构造逻辑
        # ---------------------------------------------------------------------
        raise NotImplementedError("TODO 1: 请实现 _build_evaluation_messages 提示词构造！")

    async def score_once(
        self,
        query: str,
        answer: str,
        rubric: GEvalRubric = PROFESSIONALISM_RUBRIC,
    ) -> GEvalJudgeResponse:
        """
        TODO 2: 单次 LLM Judge 打分

        要求：
        1. 调用 _build_evaluation_messages 构造 Prompt；
        2. 调用 self.llm.request_llm (temperature=self.temperature)；
        3. 使用 middlewares.llm_reliability_adapter.parse_structured 解析为 GEvalJudgeResponse。
        """
        # ---------------------------------------------------------------------
        # TODO: 请在此处实现单次 Judge 打分逻辑
        # ---------------------------------------------------------------------
        raise NotImplementedError("TODO 2: 请实现 score_once 单次打分！")

    @staticmethod
    def _compute_weighted_aggregate(
        metric_name: str,
        responses: list[GEvalJudgeResponse],
        weights: list[float] | None = None,
    ) -> GEvalAggregateResult:
        """
        TODO 3: 计算多次采样的加权均值与标准差

        要求：
        1. 提取 raw_scores (1-5) 与 normalized_scores (score/5.0)；
        2. weights 默认等权 (1/N)；
        3. weighted_mean = sum(w_i * s_i)；
        4. std_dev = sqrt(sum(w_i * (s_i - mean)^2))；
        5. converged = std_dev < CONVERGENCE_STD_THRESHOLD (0.2)。
        """
        # ---------------------------------------------------------------------
        # TODO: 请在此处实现加权聚合与标准差计算
        # ---------------------------------------------------------------------
        raise NotImplementedError("TODO 3: 请实现 _compute_weighted_aggregate 聚合计算！")

    async def evaluate_professionalism(
        self,
        query: str,
        answer: str,
        rubric: GEvalRubric = PROFESSIONALISM_RUBRIC,
    ) -> GEvalAggregateResult:
        """
        TODO 4: 并发多次独立采样并聚合

        要求：
        1. 使用 asyncio.gather 并发调用 score_once (self.sample_count 次)；
        2. 调用 _compute_weighted_aggregate 聚合结果；
        3. 返回 GEvalAggregateResult。
        """
        # ---------------------------------------------------------------------
        # TODO: 请在此处实现多次采样聚合逻辑
        # ---------------------------------------------------------------------
        raise NotImplementedError("TODO 4: 请实现 evaluate_professionalism 多次采样！")

    def verify_convergence(self, result: GEvalAggregateResult) -> bool:
        """
        TODO 5: 验证收敛性 (标准差 < 0.2)

        要求：返回 result.converged，并在不收敛时打印告警信息。
        """
        # ---------------------------------------------------------------------
        # TODO: 请在此处实现收敛性验证逻辑
        # ---------------------------------------------------------------------
        raise NotImplementedError("TODO 5: 请实现 verify_convergence 收敛验证！")


# ===============================================================================
# 调试主入口 (Debug Main Entrypoint)
# ===============================================================================
async def main() -> None:
    print("=" * 70)
    print("📝 运行 Day 100 学员练习调试入口 (practice.py)")
    print("   G-Eval LLM-as-Judge 专业度评测引擎")
    print("=" * 70)

    sample_query = (
        "请对比 ESM-2 与 ProteinBERT 在蛋白质二级结构预测中的表现，"
        "需包含定量指标与方法论差异。"
    )
    sample_answer = (
        "ESM-2 采用 Masked Language Modeling 在 UniRef50 上预训练，"
        "contact prediction F1 达到 0.89，在 remote homology 判别任务上表现更优。"
        "ProteinBERT 采用双头架构 (MLM + GO 注释预测)，"
        "在 GO term prediction 中 AUROC=0.92，显式利用功能注释监督信号。"
        "判别式任务推荐 ESM-2，功能注释任务推荐 ProteinBERT。"
    )

    judge = GEvalJudge(sample_count=5)

    try:
        result = await judge.evaluate_professionalism(sample_query, sample_answer)
        converged = judge.verify_convergence(result)

        print(f"\n📊 专业度评测结果:")
        print(f"   采样次数: {result.sample_count}")
        print(f"   原始分数: {result.raw_scores}")
        print(f"   加权均值: {result.weighted_mean:.3f}")
        print(f"   标准差:   {result.std_dev:.3f}")
        print(f"   收敛:     {'✅ PASS' if converged else '❌ FAIL (σ >= 0.2)'}")

    except NotImplementedError as e:
        print(f"\n📌 [TODO 拦截提示]: {e}")
        print("💡 提示: 请打开 `weekly/w15_eval_system/day100/practice.py` 完成 TODO。")
        print("💡 参考: 完成后对照 `evaluators/g_eval_judge_impl.py`。")


if __name__ == "__main__":
    asyncio.run(main())
