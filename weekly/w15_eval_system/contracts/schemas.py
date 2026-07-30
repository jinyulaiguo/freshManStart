"""
Week 15 Eval Pipeline 共享数据契约 (contracts/schemas.py)

===============================================================================
设计方案说明 (Architecture Design Specification)
===============================================================================

1. 设计意图 (Design Intent):
   Golden Dataset、Agent 运行轨迹 (EvalTrace) 与评测结果 (EvalResult) 是 Week 15
   全链路评测流水线的唯一数据格式真相源 (Single Source of Truth)。所有微引擎
   (SyntheticGenerator、ToolExecutionEvaluator、FaithfulnessEvaluator、EvalReporter)
   均依赖本模块的 Pydantic 契约进行序列化/反序列化与防御性校验，杜绝 JSONL
   字段漂移导致的 Silent Failure。

2. 核心类与数据流结构 (Class & Data Flow):
   - ExpectedToolCall: 期望工具名 + 参数字典
   - GoldenCaseMetadata: 难度、边界 Case 标记、Memory 依赖、来源文档
   - GoldenCase: Golden Dataset 单条测试用例完整契约
   - ToolCallRecord: Agent 实际运行轨迹中的单次工具调用
   - EvalTrace: Agent 单次运行的完整 Trace 快照
   - CaseEvalResult: 单条用例的多指标评测结果
   - EvalRunReport: 整次评测运行的聚合报告 (持久化为 eval_result.json)

3. 核心用例设计意图 (Test Case Design Intent):
   GoldenCase 必须能表达 W14 Research Agent 的全部评测维度：RAG 检索参数
   (rag_search)、Memory 召回 (retrieve_memory)、路由决策 (model_router) 及
   最终回答 ground_truth，供 Day 101-105 各 Evaluator 无歧义消费。
===============================================================================
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import AliasChoices, BaseModel, Field, field_validator, model_validator


# ═══════════════════════════════════════════════════════════════════════════
# Golden Dataset 契约
# ═══════════════════════════════════════════════════════════════════════════

class DifficultyLevel(str, Enum):
    """测试用例难度分级"""
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class GoldenCategory(str, Enum):
    """Golden Dataset 业务意图分类 (与 W14 Research Agent 场景对齐)"""
    NORMAL_RETRIEVAL = "normal_retrieval_summary"
    MULTI_PAPER_COMPARISON = "multi_paper_comparison"
    PROMPT_INJECTION = "prompt_injection_boundary"
    MEMORY_DEPENDENT = "memory_dependent"
    TOOL_PARAM_EDGE = "tool_param_edge"
    ROUTING_FALLBACK = "routing_fallback"
    CROSS_DOCUMENT = "cross_document_reasoning"


class ExpectedToolCall(BaseModel):
    """期望 Agent 调用的工具及其标准参数"""
    name: str = Field(..., min_length=1, description="工具注册名，如 rag_search")
    args: dict[str, Any] = Field(default_factory=dict, description="期望参数字典")


class GoldenCaseMetadata(BaseModel):
    """Golden Case 扩展元数据"""
    difficulty: DifficultyLevel = DifficultyLevel.MEDIUM
    edge_case: Optional[str] = Field(None, description="边界 Case 描述标签")
    requires_memory: bool = False
    source_doc: Optional[str] = Field(None, description="合成来源文档 ID 或路径")
    is_injection_test: bool = False
    paper_ids: list[str] = Field(default_factory=list, description="关联论文语料 ID")
    dataset_version: str = "v1"


class GoldenCase(BaseModel):
    """
    Golden Dataset 单条测试用例完整契约

    对应 docs/week_15_eval_system.md Day 99 定义的 JSONL 行格式。
    """
    test_case_id: str = Field(..., pattern=r"^research_\d{3}$")
    query: str = Field(..., min_length=10)
    category: GoldenCategory
    expected_tools: list[ExpectedToolCall] = Field(..., min_length=1)
    ground_truth: str = Field(..., min_length=20)
    metadata: GoldenCaseMetadata = Field(default_factory=GoldenCaseMetadata)

    @field_validator("test_case_id")
    @classmethod
    def validate_id_prefix(cls, v: str) -> str:
        if not v.startswith("research_"):
            raise ValueError("test_case_id 必须以 research_ 为前缀")
        return v

    def to_jsonl_line(self) -> str:
        """序列化为 JSONL 单行"""
        return self.model_dump_json()

    @classmethod
    def from_jsonl_line(cls, line: str) -> "GoldenCase":
        """从 JSONL 单行反序列化"""
        return cls.model_validate_json(line.strip())


# ═══════════════════════════════════════════════════════════════════════════
# Agent 运行轨迹 (EvalTrace) 契约 — Day 101+ 消费
# ═══════════════════════════════════════════════════════════════════════════

class ToolCallRecord(BaseModel):
    """Agent 实际执行的单次工具调用记录"""
    name: str
    args: dict[str, Any] = Field(default_factory=dict)
    result_summary: Optional[str] = None
    latency_ms: Optional[float] = None
    success: bool = True


class EvalTrace(BaseModel):
    """
    Agent 单次运行的完整 Trace 快照

    run_eval.py 收集后传递给各 Evaluator 进行打分。
    """
    test_case_id: str
    query: str
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    retrieved_contexts: list[str] = Field(default_factory=list)
    final_answer: str = ""
    routing_decision: Optional[str] = None
    token_usage: dict[str, int] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    duration_ms: Optional[float] = None


# ═══════════════════════════════════════════════════════════════════════════
# 评测结果契约 — Day 104 EvalReporter 消费
# ═══════════════════════════════════════════════════════════════════════════

class CaseEvalResult(BaseModel):
    """单条 Golden Case 的多维度评测结果"""
    test_case_id: str
    passed: bool
    tool_precision: Optional[float] = None
    tool_recall: Optional[float] = None
    tool_f1: Optional[float] = None
    param_accuracy: Optional[float] = None
    faithfulness: Optional[float] = None
    relevance: Optional[float] = None
    professionalism: Optional[float] = None
    failure_reasons: list[str] = Field(default_factory=list)


class EvalRunReport(BaseModel):
    """整次评测运行的聚合报告 (持久化为 eval_result.json)"""
    run_id: str
    git_sha: Optional[str] = None
    judge_model: Optional[str] = None
    dataset_version: str = "v1"
    dataset_path: str = ""
    started_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    finished_at: Optional[str] = None
    aggregate: dict[str, float] = Field(default_factory=dict)
    thresholds: dict[str, float] = Field(default_factory=dict)
    cases: list[CaseEvalResult] = Field(default_factory=list)

    def save_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            self.model_dump_json(indent=2),
            encoding="utf-8"
        )

    @classmethod
    def load_json(cls, path: Path) -> "EvalRunReport":
        return cls.model_validate_json(path.read_text(encoding="utf-8"))


# ═══════════════════════════════════════════════════════════════════════════
# JSONL 文件读写工具
# ═══════════════════════════════════════════════════════════════════════════

def load_golden_dataset(path: Path) -> list[GoldenCase]:
    """从 JSONL 文件加载 Golden Dataset，跳过空行"""
    cases: list[GoldenCase] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            cases.append(GoldenCase.from_jsonl_line(stripped))
        except Exception as exc:
            raise ValueError(f"JSONL 第 {line_no} 行解析失败: {exc}") from exc
    return cases


def save_golden_dataset(cases: list[GoldenCase], path: Path) -> None:
    """将 Golden Dataset 写入 JSONL 文件 (每行一条)"""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [case.to_jsonl_line() for case in cases]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def validate_dataset_uniqueness(cases: list[GoldenCase]) -> None:
    """防御性校验 test_case_id 全局唯一"""
    seen: set[str] = set()
    for case in cases:
        if case.test_case_id in seen:
            raise ValueError(f"重复的 test_case_id: {case.test_case_id}")
        seen.add(case.test_case_id)


# ═══════════════════════════════════════════════════════════════════════════
# LLM 合成批次响应契约 — 配合 llm_reliability_adapter.parse_structured
# ═══════════════════════════════════════════════════════════════════════════

class SyntheticCaseDraft(BaseModel):
    """
    LLM 合成的单条 Golden Case 草稿 (不含 test_case_id，由系统分配)

    供 SyntheticGenerator 通过 parse_structured 解析 LLM 批次响应后，
    再升级为完整 GoldenCase。
    """
    query: str = Field(..., min_length=10)
    expected_tools: list[ExpectedToolCall] = Field(..., min_length=1)
    ground_truth: str = Field(..., min_length=20)
    metadata: GoldenCaseMetadata = Field(default_factory=GoldenCaseMetadata)


class GoldenBatchResponse(BaseModel):
    """
    LLM 批次合成响应契约

    必须使用 JSON 对象 {\"cases\": [...]} 格式，以便 llm_reliability_adapter
    的 BracketExtractor 精准提取并剥离 <think> 污染。
    """
    cases: list[SyntheticCaseDraft] = Field(..., min_length=1)


# ═══════════════════════════════════════════════════════════════════════════
# G-Eval LLM-as-Judge 契约 — Day 100 消费
# ═══════════════════════════════════════════════════════════════════════════

class GEvalEvaluationStep(BaseModel):
    """G-Eval CoT 评测步骤单条记录"""
    step_number: int = Field(..., ge=1, le=10)
    analysis: str = Field(..., min_length=3)


class GEvalJudgeResponse(BaseModel):
    """
    G-Eval 单次 Judge 响应契约

    强制 LLM 先输出分步推理 (evaluation_steps)，再给出 1-5 分最终评分。
    供 parse_structured 解析，剥离思考链污染。
    """
    evaluation_steps: list[GEvalEvaluationStep] = Field(..., min_length=2)
    chain_of_thought_summary: str = Field(..., min_length=5)
    score: int = Field(..., ge=1, le=5, description="1-5 分 Likert 专业度评分")
    score_rationale: str = Field(..., min_length=5)

    @property
    def normalized_score(self) -> float:
        """将 1-5 分映射至 [0.2, 1.0] 归一化区间"""
        return self.score / 5.0


class GEvalAggregateResult(BaseModel):
    """多次独立采样的 G-Eval 聚合评测结果"""
    metric_name: str
    sample_count: int
    raw_scores: list[int] = Field(..., min_length=1)
    normalized_scores: list[float] = Field(..., min_length=1)
    weights: list[float] = Field(default_factory=list)
    weighted_mean: float
    std_dev: float
    converged: bool = Field(description="归一化分数标准差是否 < 0.2")
    individual_responses: list[GEvalJudgeResponse] = Field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════
# Tool Execution 评测契约 — Day 101 消费
# ═══════════════════════════════════════════════════════════════════════════

class ToolMatchDetail(BaseModel):
    """
    单次期望工具调用与实际 Trace 的匹配明细

    供 Day 104 EvalReporter Diff 报告定位具体参数误差。
    """
    expected_name: str
    actual_name: Optional[str] = None
    name_matched: bool = False
    param_matched: bool = False
    param_errors: list[str] = Field(
        default_factory=list,
        description="参数级误差描述，如 'top_k: expected=30 actual=5'",
    )


class ToolExecutionResult(BaseModel):
    """
    单条 Golden Case 的工具调用 Precision / Recall / F1 评测结果

    确定性指标，无需 LLM，可在 CI 中零成本复现。
    """
    test_case_id: str
    precision: float = Field(..., ge=0.0, le=1.0)
    recall: float = Field(..., ge=0.0, le=1.0)
    f1: float = Field(..., ge=0.0, le=1.0)
    param_accuracy: float = Field(
        ..., ge=0.0, le=1.0,
        description="name 已匹配的对中，参数完全正确的比例",
    )
    true_positives: int = Field(..., ge=0)
    false_positives: int = Field(..., ge=0)
    false_negatives: int = Field(..., ge=0)
    matched_details: list[ToolMatchDetail] = Field(default_factory=list)
    unmatched_actual: list[str] = Field(
        default_factory=list,
        description="实际多调且未被期望消费的工具名列表",
    )
    unmatched_expected: list[str] = Field(
        default_factory=list,
        description="期望中未被实际调用消费的工具名列表",
    )


class ToolExecutionBatchResult(BaseModel):
    """批量评测聚合结果 (供 Day 103 CI 阈值门禁消费)"""
    case_count: int
    mean_precision: float
    mean_recall: float
    mean_f1: float
    mean_param_accuracy: float
    cases: list[ToolExecutionResult] = Field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════
# Faithfulness / Relevance 探针契约 — Day 102 消费
# ═══════════════════════════════════════════════════════════════════════════

class ClaimVerdict(BaseModel):
    """
    单条 claim 的 Context 支撑判定

    Faithfulness 探针将 answer 拆解为原子声明后逐条审计。
    """
    claim: str = Field(..., min_length=3, description="从 answer 拆解出的原子声明")
    supported: bool = Field(..., description="是否能在 retrieved_contexts 中找到支撑")
    evidence_snippet: Optional[str] = Field(
        None,
        description="支撑该 claim 的 Context 片段摘录；不支持时为 null",
    )
    reason: str = Field(..., min_length=3, description="判定理由")


class FaithfulnessJudgeResponse(BaseModel):
    """
    Faithfulness LLM Judge 结构化响应

    强制输出 claims 数组，分数由 supported/total 确定性计算，禁止 LLM 随意给分。
    """
    claims: list[ClaimVerdict] = Field(..., min_length=1)
    summary: str = Field(..., min_length=5, description="幻觉审计摘要")

    @property
    def score(self) -> float:
        """Faithfulness = |supported claims| / |all claims|"""
        if not self.claims:
            return 0.0
        supported = sum(1 for c in self.claims if c.supported)
        return round(supported / len(self.claims), 4)

    @property
    def unsupported_claims(self) -> list[ClaimVerdict]:
        return [c for c in self.claims if not c.supported]


class RelevanceJudgeResponse(BaseModel):
    """
    Relevance LLM Judge 结构化响应

    判定 answer 是否切实解答 query，输出 0-1 分与偏题诊断。
    """
    score: float = Field(..., ge=0.0, le=1.0, description="相关性得分 [0, 1]")
    is_on_topic: bool = Field(..., description="是否切题回答了用户问题")
    missing_aspects: list[str] = Field(
        default_factory=list,
        description="Query 中未被回答的关键方面",
    )
    rationale: str = Field(
        ...,
        min_length=5,
        description="给分与偏题判定理由",
        validation_alias=AliasChoices("rationale", "reason", "score_rationale"),
    )

    model_config = {"populate_by_name": True}


class ProbeScoreResult(BaseModel):
    """单探针评测结果 (Faithfulness 或 Relevance 统一外壳)"""
    metric_name: Literal["faithfulness", "relevance"]
    test_case_id: str
    score: float = Field(..., ge=0.0, le=1.0)
    passed: bool = Field(description="是否达到该探针的过关阈值")
    unsupported_claims: list[str] = Field(
        default_factory=list,
        description="Faithfulness 未支撑声明列表；Relevance 场景为空",
    )
    missing_aspects: list[str] = Field(
        default_factory=list,
        description="Relevance 缺失方面；Faithfulness 场景为空",
    )
    summary: str = ""
    raw_judge: Optional[dict[str, Any]] = Field(
        None,
        description="Judge 原始结构化响应摘要，供审计",
    )


# ═══════════════════════════════════════════════════════════════════════════
# CI Threshold Gate 契约 — Day 103 消费
# ═══════════════════════════════════════════════════════════════════════════

class GateCheckItem(BaseModel):
    """单指标阈值比对明细"""
    metric_name: str
    actual: float
    threshold: float
    passed: bool
    delta: float = Field(description="actual - threshold，负值表示未达标差额")


class GateVerdict(BaseModel):
    """
    ThresholdGate 对整次 EvalRunReport 的门禁裁决

    passed=False 时 CI 必须以非 0 exit code 退出以拦截合入。
    """
    passed: bool
    mode: str = Field(description="pr | full | demo_pass | demo_fail")
    checks: list[GateCheckItem] = Field(default_factory=list)
    failed_metrics: list[str] = Field(default_factory=list)
    message: str = ""

    @property
    def exit_code(self) -> int:
        """CI 退出码：通过 0，拦截 1"""
        return 0 if self.passed else 1


# ═══════════════════════════════════════════════════════════════════════════
# Regression Diff 契约 — Day 104 EvalReporter 消费
# ═══════════════════════════════════════════════════════════════════════════

class MetricDelta(BaseModel):
    """聚合指标相对 baseline 的绝对变动"""
    metric_name: str
    baseline: float
    current: float
    delta: float = Field(description="current - baseline")
    status: Literal["improved", "regressed", "unchanged"]


class CaseDelta(BaseModel):
    """单条 test_case 相对 baseline 的通过态与指标变动"""
    test_case_id: str
    baseline_passed: Optional[bool] = None
    current_passed: Optional[bool] = None
    status: Literal["regressed", "improved", "unchanged", "added", "removed"]
    metric_deltas: dict[str, float] = Field(
        default_factory=dict,
        description="各指标 current-baseline，如 tool_f1 / faithfulness",
    )
    failure_reasons: list[str] = Field(default_factory=list)


class RegressionReport(BaseModel):
    """两次 EvalRunReport 的完整回归差异报告"""
    baseline_run_id: str
    current_run_id: str
    baseline_git_sha: Optional[str] = None
    current_git_sha: Optional[str] = None
    aggregate_deltas: list[MetricDelta] = Field(default_factory=list)
    case_deltas: list[CaseDelta] = Field(default_factory=list)
    regressed_ids: list[str] = Field(default_factory=list)
    improved_ids: list[str] = Field(default_factory=list)

    def to_markdown(self) -> str:
        """由 EvalReporter.render_markdown 填充前的占位；完整渲染在 reporter 内实现。"""
        return (
            f"# Eval Regression Report\n\n"
            f"- baseline: `{self.baseline_run_id}`\n"
            f"- current: `{self.current_run_id}`\n"
            f"- regressed: {len(self.regressed_ids)}\n"
            f"- improved: {len(self.improved_ids)}\n"
        )
