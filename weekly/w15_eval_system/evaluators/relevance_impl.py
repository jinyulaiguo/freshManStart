"""
Week 15 Day 102 参考标准答案: Relevance 切题检测探针 (relevance_impl.py)

===============================================================================
设计方案说明 (Architecture Design Specification)
===============================================================================

1. 设计意图 (Design Intent):
   即使回复对 Context 完全忠实，仍可能答非所问。本模块实现独立的 Relevance
   探针：仅消费 query + final_answer，输出 0-1 相关性分、是否切题与
   missing_aspects，与 Faithfulness 物理隔离，避免 Prompt 互相污染。

2. 核心类与数据流结构 (Class & Data Flow):
   - RelevanceEvaluator:
     - _build_messages(): 切题判定 Judge Prompt
     - evaluate(): request_llm + parse_structured → ProbeScoreResult
     - verify_off_topic() / verify_on_topic(): 阈值门禁
   - RelevanceJudgeResponse: contracts/schemas.py 契约

3. 核心用例设计意图 (Test Case Design Intent):
   固定 Query「对比 ESM-2 与 ProteinBERT 定量指标」：
   - 切题回复: 直接对比 F1 / AUROC → score >= 0.7
   - 偏题回复: 讨论天气 / 无关体育话题 → score <= 0.3
   - 部分切题: 只提 ESM-2 不提对比 → missing_aspects 非空、分数中等偏低
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
from contracts.schemas import ProbeScoreResult, RelevanceJudgeResponse


# ═══════════════════════════════════════════════════════════════════════════
# RelevanceEvaluator 微引擎
# ═══════════════════════════════════════════════════════════════════════════

class RelevanceEvaluator:
    """
    Relevance 探针：检测 final_answer 是否切实解答用户 query。

    Parameters
    ----------
    llm_client:
        Week 4 LLMClient 实例。
    temperature:
        Judge 采样温度，默认 0.1。
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
        构造 Query–Answer 切题判定 Prompt。

        Returns
        -------
        list[dict[str, str]]
            OpenAI 风格 messages。
        """
        system_msg = (
            "你是 Answer Relevance 评测法官。唯一任务：判断回复是否在回答用户问题。\n"
            "不要评价事实真伪、指标是否同基准、论证深度或文采。\n\n"
            "## 强制评分锚点 (Few-shot)\n"
            "例1 Query=对比 A 与 B 的定量指标；Answer=分别给出 A/B 各一项指标并简述差异\n"
            "  → score=0.9, is_on_topic=true, missing_aspects=[]\n"
            "例2 Query=同上；Answer=只谈 A，完全不提 B\n"
            "  → score=0.5, is_on_topic=true, missing_aspects=[\"未覆盖 B\"]\n"
            "例3 Query=同上；Answer=讨论天气或电影\n"
            "  → score=0.0, is_on_topic=false, missing_aspects=[\"未回答对比问题\"]\n\n"
            "## 硬性规则\n"
            "- 只要回复主体在谈 Query 点名的对象与意图，score 必须 >= 0.8；\n"
            "- 禁止因「不同下游任务指标」「缺少参数量」「对比不够深入」扣到 0.7 以下；\n"
            "- 完全跑题才允许 score <= 0.3。\n\n"
            "## 输出格式\n"
            "严格返回 JSON 对象，字段必须包含：\n"
            "score (0~1), is_on_topic (bool), missing_aspects (string[]), rationale (string)"
        )

        user_msg = (
            f"## User Query\n{query}\n\n"
            f"## Agent Answer\n{answer}\n\n"
            "请严格按评分锚点给分。若回复已同时提及 Query 中的对比对象并给出定量信息，"
            "score 必须 >= 0.8。"
        )

        return [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ]

    async def evaluate(
        self,
        test_case_id: str,
        query: str,
        answer: str,
    ) -> ProbeScoreResult:
        """
        对单条回复执行 Relevance 评测。

        Parameters
        ----------
        test_case_id:
            用例 ID。
        query:
            用户问题。
        answer:
            Agent final_answer。

        Returns
        -------
        ProbeScoreResult
            metric_name=\"relevance\" 的探针结果。
        """
        # 步骤 1：构造 Prompt 并请求 LLM
        messages = self._build_messages(query, answer)
        raw = await self.llm.request_llm(
            messages=messages,
            temperature=self.temperature,
            max_tokens=2048,
            response_format={"type": "json_object"},
        )

        # 步骤 2：结构化解析
        judge = parse_structured(raw, RelevanceJudgeResponse)

        return ProbeScoreResult(
            metric_name="relevance",
            test_case_id=test_case_id,
            score=round(judge.score, 4),
            passed=judge.score >= self.ON_TOPIC_MIN_SCORE and judge.is_on_topic,
            missing_aspects=list(judge.missing_aspects),
            summary=judge.rationale,
            raw_judge=judge.model_dump(),
        )

    def verify_off_topic(self, result: ProbeScoreResult) -> bool:
        """偏题回复过关：score <= 0.3。"""
        ok = result.score <= self.OFF_TOPIC_MAX_SCORE
        tag = "PASS" if ok else "FAIL"
        print(
            f"   [{tag}] 偏题校验: score={result.score:.4f} "
            f"{'<=' if ok else '>'} {self.OFF_TOPIC_MAX_SCORE}"
        )
        return ok

    def verify_on_topic(self, result: ProbeScoreResult) -> bool:
        """切题回复过关：score >= 0.7。"""
        ok = result.score >= self.ON_TOPIC_MIN_SCORE
        tag = "PASS" if ok else "FAIL"
        print(
            f"   [{tag}] 切题校验: score={result.score:.4f} "
            f"{'>=' if ok else '<'} {self.ON_TOPIC_MIN_SCORE}"
        )
        return ok


# ═══════════════════════════════════════════════════════════════════════════
# 固定样本
# ═══════════════════════════════════════════════════════════════════════════

DEMO_QUERY = "请对比 ESM-2 与 ProteinBERT 的定量指标差异。"

SAMPLES: list[tuple[str, str, str, str]] = [
    # (label, test_case_id, answer, expect)  expect in {on_topic, off_topic}
    (
        "切题对比",
        "research_on_topic",
        (
            "针对 ESM-2 与 ProteinBERT 的定量指标对比："
            "ESM-2 的 contact prediction F1=0.89；"
            "ProteinBERT 的 GO term prediction AUROC=0.92。"
            "因此判别式结构任务更看重 ESM-2，功能注释任务更看重 ProteinBERT。"
        ),
        "on_topic",
    ),
    (
        "完全偏题",
        "research_off_topic",
        "今天天气晴朗，适合去公园跑步，与蛋白质语言模型没有任何关系。",
        "off_topic",
    ),
    (
        "话题漂移",
        "research_drift",
        (
            "我推荐你去看一部关于人工智能的科幻电影，"
            "里面有很多酷炫的机器人场景，非常值得周末观看。"
        ),
        "off_topic",
    ),
]


def print_result(label: str, result: ProbeScoreResult) -> None:
    """终端输出单条探针明细。"""
    print(f"\n── {label} ({result.test_case_id}) ──")
    print(f"   score={result.score:.4f}  passed={result.passed}")
    print(f"   summary: {result.summary[:120]}")
    if result.missing_aspects:
        print(f"   missing_aspects: {result.missing_aspects}")


# ═══════════════════════════════════════════════════════════════════════════
# 标准答案调试主入口
# ═══════════════════════════════════════════════════════════════════════════

async def main() -> None:
    print("=" * 70)
    print("🔬 Day 102 标准答案: RelevanceEvaluator 切题检测探针")
    print("=" * 70)

    evaluator = RelevanceEvaluator(temperature=0.1)
    all_pass = True

    for label, case_id, answer, expect in SAMPLES:
        print(f"\n🎯 评测场景: {label}")
        result = await evaluator.evaluate(case_id, DEMO_QUERY, answer)
        print_result(label, result)

        if expect == "on_topic":
            ok = evaluator.verify_on_topic(result)
        else:
            ok = evaluator.verify_off_topic(result)

        if not ok:
            all_pass = False

    print(
        f"\n📊 过关验证: "
        f"{'✅ 切题高分 + 偏题极低分全部通过' if all_pass else '❌ 存在场景未达阈值'}"
    )


if __name__ == "__main__":
    asyncio.run(main())
