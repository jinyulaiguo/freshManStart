"""
Week 15 Day 100 参考标准答案: G-Eval LLM-as-Judge 专业度评测引擎 (g_eval_judge_impl.py)

===============================================================================
设计方案说明 (Architecture Design Specification)
===============================================================================

1. 设计意图 (Design Intent):
   自由文本 Agent 回复无法通过 BLEU/ROUGE 精确匹配评测。本模块实现 G-Eval 论文
   规范的 LLM-as-Judge 微引擎：通过 Evaluation Rubric 规定 1-5 分边界、强制 CoT
   分步推理后再输出最终分，多次独立采样计算加权均值与标准差，验证 Judge 收敛性
   (σ < 0.2)。

2. 核心类与数据流结构 (Class & Data Flow):
   - GEvalRubric / RubricScoreBand: Rubric 细则与 CoT 步骤模板
   - GEvalJudge: 评测微引擎
     - _build_evaluation_messages(): Rubric + CoT Judge Prompt 构造
     - score_once(): 单次 LLM 调用 + parse_structured 解析
     - _compute_weighted_aggregate(): 加权均值 + 标准差
     - evaluate_professionalism(): asyncio.gather 并发多次采样
     - verify_convergence(): σ < 0.2 收敛门禁
   - GEvalJudgeResponse / GEvalAggregateResult: contracts/schemas.py 契约

3. 核心用例设计意图 (Test Case Design Intent):
   选取 W14 Research Agent 蛋白质 LM 对比分析回复作为验证样本：
   - 验证 Rubric 1-5 分细则能区分外行 vs 专业表述；
   - 验证 5 次独立采样归一化分数标准差 σ < 0.2；
   - 验证 parse_structured 能剥离 Judge 模型 <think> 污染。
===============================================================================
"""

from __future__ import annotations

import asyncio
import math
import os
import sys
from dataclasses import dataclass, field
from typing import Any

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
from contracts.schemas import GEvalJudgeResponse, GEvalAggregateResult


# ═══════════════════════════════════════════════════════════════════════════
# G-Eval Rubric 定义
# ═══════════════════════════════════════════════════════════════════════════

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

    def format_score_bands_text(self) -> str:
        """将 score_bands 格式化为 Prompt 可读文本"""
        lines = []
        for band in self.score_bands:
            lines.append(f"  {band.score} 分 ({band.label}): {band.criteria}")
        return "\n".join(lines)

    def format_cot_steps_text(self) -> str:
        """将 CoT 步骤格式化为编号列表"""
        return "\n".join(
            f"  步骤 {i + 1}: {step}"
            for i, step in enumerate(self.cot_step_templates)
        )


PROFESSIONALISM_RUBRIC = GEvalRubric(
    metric_name="professionalism",
    criteria_description=(
        "评估 AI 研究助手 (W14 Research Agent) 回复是否达到学术论文级专业表述标准，"
        "涵盖术语准确性、定量指标引用、方法论对比完整性与论证结构。"
    ),
    score_bands=[
        RubricScoreBand(1, "外行", "术语误用、逻辑混乱、无学术引用结构、数据编造"),
        RubricScoreBand(2, "入门", "基本可读但缺乏深度，无定量指标支撑，对比维度单一"),
        RubricScoreBand(3, "合格", "术语基本正确，有简单对比但论证不完整，缺少任务类型区分"),
        RubricScoreBand(4, "专业", "引用准确、对比清晰、含定量指标 (F1/AUROC/ρ) 与方法论区分"),
        RubricScoreBand(5, "卓越", "论证严密、多维度对比、含 Scaling/架构/判别vs生成任务细分与结论有据"),
    ],
    cot_step_templates=[
        "识别回复中的核心论点、对比模型与关键结论",
        "检查蛋白质语言模型领域术语 (MLM, Autoregressive, Contact Prediction 等) 是否准确",
        "评估是否引用了语料中的定量性能指标 (F1, AUROC, Spearman ρ, GDT-TS 等)",
        "评估论证结构是否完整 (对比维度、方法论差异、任务类型区分、结论依据)",
        "对照 Rubric 各分数段标准，给出 1-5 分最终评分及理由",
    ],
)


# ═══════════════════════════════════════════════════════════════════════════
# G-Eval Judge 微引擎
# ═══════════════════════════════════════════════════════════════════════════

class GEvalJudge:
    """
    G-Eval LLM-as-Judge 评测微引擎

    Rubric + CoT 多次独立采样 → 加权均值 + 标准差 → 收敛验证 (σ < 0.2)
    """

    CONVERGENCE_STD_THRESHOLD = 0.2

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        sample_count: int = 5,
        temperature: float = 0.2,
        max_concurrency: int = 3,
    ):
        self.llm = llm_client or LLMClient()
        self.sample_count = sample_count
        self.temperature = temperature
        self._semaphore = asyncio.Semaphore(max_concurrency)

    def _build_evaluation_messages(
        self,
        query: str,
        answer: str,
        rubric: GEvalRubric,
    ) -> list[dict[str, str]]:
        """
        构造 G-Eval Judge 提示词 Messages

        注入 Rubric 细则、CoT 强制步骤与 JSON 输出 Schema 约束。
        """
        system_msg = (
            f"你是严格的 G-Eval 评测法官 (LLM-as-Judge)，负责评估 metric=\"{rubric.metric_name}\"。\n\n"
            f"## 评估标准\n{rubric.criteria_description}\n\n"
            f"## 分数段 Rubric (1-5 分)\n{rubric.format_score_bands_text()}\n\n"
            f"## 强制 CoT 推理步骤 (必须逐步完成后再给分)\n{rubric.format_cot_steps_text()}\n\n"
            "## 输出格式\n"
            "严格返回 JSON 对象 (不含 markdown 与思考过程)，字段：\n"
            "- evaluation_steps: [{step_number, analysis}, ...] 对应上述 CoT 步骤\n"
            "- chain_of_thought_summary: 推理摘要\n"
            "- score: 1-5 整数\n"
            "- score_rationale: 对照 Rubric 的给分理由"
        )

        user_msg = (
            f"## 用户问题 (Query)\n{query}\n\n"
            f"## Agent 回复 (Answer)\n{answer}\n\n"
            "请按 CoT 步骤逐步分析，然后给出 1-5 分专业度评分。"
        )

        return [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ]

    async def score_once(
        self,
        query: str,
        answer: str,
        rubric: GEvalRubric = PROFESSIONALISM_RUBRIC,
    ) -> GEvalJudgeResponse:
        """
        单次 LLM Judge 打分 (含 parse_structured 结构化解析)
        """
        messages = self._build_evaluation_messages(query, answer, rubric)

        async with self._semaphore:
            raw = await self.llm.request_llm(
                messages=messages,
                temperature=self.temperature,
                max_tokens=4096,
            )

        return parse_structured(raw, GEvalJudgeResponse)

    @staticmethod
    def _compute_weighted_aggregate(
        metric_name: str,
        responses: list[GEvalJudgeResponse],
        weights: list[float] | None = None,
    ) -> GEvalAggregateResult:
        """
        计算多次采样的加权均值与标准差 (归一化分数域 [0.2, 1.0])
        """
        if not responses:
            raise ValueError("responses 不能为空")

        raw_scores = [r.score for r in responses]
        normalized = [r.normalized_score for r in responses]
        n = len(normalized)

        # 步骤 1：权重归一化 (默认等权)
        if weights is None:
            w = [1.0 / n] * n
        else:
            if len(weights) != n:
                raise ValueError(f"weights 长度 {len(weights)} != responses 长度 {n}")
            total = sum(weights)
            w = [x / total for x in weights]

        # 步骤 2：加权均值
        weighted_mean = sum(wi * si for wi, si in zip(w, normalized))

        # 步骤 3：加权标准差 (population std)
        variance = sum(wi * (si - weighted_mean) ** 2 for wi, si in zip(w, normalized))
        std_dev = math.sqrt(variance)

        # 步骤 4：收敛判定
        converged = std_dev < GEvalJudge.CONVERGENCE_STD_THRESHOLD

        return GEvalAggregateResult(
            metric_name=metric_name,
            sample_count=n,
            raw_scores=raw_scores,
            normalized_scores=normalized,
            weights=w,
            weighted_mean=round(weighted_mean, 4),
            std_dev=round(std_dev, 4),
            converged=converged,
            individual_responses=responses,
        )

    async def evaluate_professionalism(
        self,
        query: str,
        answer: str,
        rubric: GEvalRubric = PROFESSIONALISM_RUBRIC,
    ) -> GEvalAggregateResult:
        """
        并发多次独立采样并聚合专业度评分
        """
        print(f"   🎯 启动 G-Eval 专业度评测 (采样 {self.sample_count} 次, T={self.temperature})...")

        tasks = [
            self.score_once(query, answer, rubric)
            for _ in range(self.sample_count)
        ]
        responses = await asyncio.gather(*tasks)

        result = self._compute_weighted_aggregate(
            metric_name=rubric.metric_name,
            responses=list(responses),
        )

        return result

    def verify_convergence(self, result: GEvalAggregateResult) -> bool:
        """
        验证收敛性：归一化分数标准差 σ < 0.2
        """
        if result.converged:
            print(
                f"   ✅ 收敛验证 PASS: σ={result.std_dev:.4f} < "
                f"{self.CONVERGENCE_STD_THRESHOLD}"
            )
        else:
            print(
                f"   ❌ 收敛验证 FAIL: σ={result.std_dev:.4f} >= "
                f"{self.CONVERGENCE_STD_THRESHOLD}，建议检查 Rubric 或降低 temperature"
            )
        return result.converged

    def print_result_table(self, result: GEvalAggregateResult) -> None:
        """终端表格输出评测明细"""
        print("\n" + "─" * 60)
        print(f"{'#':<4} {'原始分':<8} {'归一化':<10} {'CoT 摘要 (前 40 字)'}")
        print("─" * 60)
        for i, resp in enumerate(result.individual_responses, 1):
            cot_preview = resp.chain_of_thought_summary[:40].replace("\n", " ")
            print(
                f"{i:<4} {resp.score:<8} {resp.normalized_score:<10.3f} {cot_preview}..."
            )
        print("─" * 60)
        print(
            f"加权均值: {result.weighted_mean:.4f}  |  "
            f"标准差 σ: {result.std_dev:.4f}  |  "
            f"收敛: {'PASS' if result.converged else 'FAIL'}"
        )
        print("─" * 60)


# ═══════════════════════════════════════════════════════════════════════════
# 标准答案调试主入口
# ═══════════════════════════════════════════════════════════════════════════

# W14 Research Agent 专业度验证样本 (固定，确保可复现)
DEMO_QUERY = (
    "请对比 ESM-2 与 ProteinBERT 在蛋白质二级结构预测中的表现，"
    "需包含定量指标与方法论差异。"
)

DEMO_ANSWER = (
    "ESM-2 采用 Masked Language Modeling (MLM) 在 UniRef50 上预训练，"
    "参数规模 8M-15B，contact prediction F1 达到 0.89，"
    "在 remote homology 判别任务上表现更优，Scaling Law 呈对数线性关系 (R²=0.997)。"
    "ProteinBERT 采用双头架构 (MLM + GO 注释预测头)，"
    "在 GO term prediction 中 AUROC=0.92，显式利用功能注释监督信号。"
    "核心差异：ESM-2 纯序列表征，ProteinBERT 融合功能标签监督。"
    "判别式任务 (分类/回归/结构预测) 推荐 ESM-2；"
    "功能注释任务推荐 ProteinBERT。"
)


async def main() -> None:
    print("=" * 70)
    print("🔬 Day 100 标准答案: G-Eval LLM-as-Judge 专业度评测引擎")
    print("=" * 70)

    judge = GEvalJudge(sample_count=5, temperature=0.2)

    result = await judge.evaluate_professionalism(DEMO_QUERY, DEMO_ANSWER)
    judge.print_result_table(result)
    converged = judge.verify_convergence(result)

    print(f"\n📊 过关验证: {'✅ 标准差 σ < 0.2，Judge 收敛' if converged else '❌ 未收敛，请调整 Rubric 或采样参数'}")


if __name__ == "__main__":
    asyncio.run(main())
