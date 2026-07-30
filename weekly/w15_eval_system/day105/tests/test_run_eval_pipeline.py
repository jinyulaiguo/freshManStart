"""Day 105 unit tests: MockTraceRunner / offline pipeline / gate contract."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

DAY105 = Path(__file__).resolve().parent.parent
W15 = DAY105.parent
REPO = W15.parent.parent

for p in (str(REPO), str(W15), str(W15 / "evaluators"), str(W15 / "gate"), str(W15 / "reporter")):
    if p not in sys.path:
        sys.path.insert(0, p)

from contracts.schemas import (  # noqa: E402
    EvalRunReport,
    ExpectedToolCall,
    GoldenCase,
    GoldenCaseMetadata,
    GoldenCategory,
    load_golden_dataset,
)
from agent_runner.mock_runner import MockTraceRunner  # noqa: E402
from agent_runner.research_adapter import (  # noqa: E402
    _extract_contexts,
    ResearchAgentTraceAdapter,
)
from run_eval import EvalPipeline  # noqa: E402
from threshold_gate_impl import ThresholdGate  # noqa: E402
from eval_reporter_impl import EvalReporter  # noqa: E402


GOLDEN = DAY105 / "golden_dataset.jsonl"


def _tiny_case(case_id: str = "research_001") -> GoldenCase:
    return GoldenCase(
        test_case_id=case_id,
        query="请总结 ESM-2 在接触预测任务上的定量表现与训练范式。",
        category=GoldenCategory.NORMAL_RETRIEVAL,
        expected_tools=[
            ExpectedToolCall(
                name="rag_search",
                args={"query": "ESM-2 contact prediction", "top_k": 10},
            )
        ],
        ground_truth=(
            "ESM-2 采用 Masked Language Modeling，contact prediction F1 约为 0.89，"
            "在 remote homology 判别任务上表现稳定。"
        ),
        metadata=GoldenCaseMetadata(difficulty="easy"),
    )


def test_golden_dataset_has_50_cases():
    assert GOLDEN.exists()
    cases = load_golden_dataset(GOLDEN)
    assert len(cases) == 50
    assert cases[0].test_case_id.startswith("research_")


def test_mock_perfect_trace_matches_tools():
    case = _tiny_case()
    trace = MockTraceRunner(scenario="default").build_trace(case)
    assert [t.name for t in trace.tool_calls] == ["rag_search"]
    assert trace.tool_calls[0].args["top_k"] == 10
    assert trace.final_answer == case.ground_truth
    assert len(trace.retrieved_contexts) >= 1


def test_mock_demo_fail_drops_tool_and_hallucinates():
    case = _tiny_case("research_002")
    # 单工具 Case：漏调 → 空 tool_calls
    case2 = case.model_copy(
        update={
            "expected_tools": [
                ExpectedToolCall(name="rag_search", args={"query": "x", "top_k": 5}),
                ExpectedToolCall(
                    name="retrieve_memory", args={"user_id": "researcher_001"}
                ),
            ]
        }
    )
    trace = MockTraceRunner(
        scenario="demo_fail",
        fail_case_ids=["research_002"],
    ).build_trace(case2)
    assert len(trace.tool_calls) == 1
    assert trace.tool_calls[0].name == "rag_search"
    assert "Quantum Attention" in trace.final_answer


def test_extract_contexts_from_decision_log():
    class FakeAssembly:
        decision_log = [
            {"selected": True, "content": "A" * 40},
            {"selected": False, "content": "ignored"},
            {"selected": True, "content": "B" * 40},
        ]
        payload = []

    ctx = _extract_contexts(FakeAssembly())
    assert len(ctx) == 2


def test_offline_pipeline_pass_and_fail_gate():
    cases = load_golden_dataset(GOLDEN)[:5]

    async def _run(scenario: str) -> EvalRunReport:
        pipe = EvalPipeline(
            agent_mode="mock",
            scenario=scenario,  # type: ignore[arg-type]
            metrics="gate",
            offline=True,
            concurrency=4,
        )
        return await pipe.run(cases, run_id=f"test-{scenario}")

    pass_report = asyncio.run(_run("default"))
    assert pass_report.aggregate["tool_f1"] >= 0.85
    assert pass_report.aggregate["faithfulness"] >= 0.90
    verdict = ThresholdGate().check(pass_report, mode="pr")
    assert verdict.passed

    fail_report = asyncio.run(_run("demo_fail"))
    assert fail_report.aggregate["tool_f1"] < 0.85
    verdict_fail = ThresholdGate().check(fail_report, mode="pr")
    assert not verdict_fail.passed

    diff = EvalReporter().compare(pass_report, fail_report)
    assert "research_002" in diff.regressed_ids
    md = EvalReporter().render_markdown(diff)
    assert "regressed" in md.lower()


def test_gate_enforce_exit_code():
    cases = load_golden_dataset(GOLDEN)[:5]
    pipe = EvalPipeline(agent_mode="mock", scenario="demo_fail", metrics="gate", offline=True)
    report = asyncio.run(pipe.run(cases, run_id="gate-exit"))
    with pytest.raises(SystemExit) as exc:
        ThresholdGate().enforce(report, mode="pr")
    assert exc.value.code == 1


def test_research_adapter_importable():
    """确保 Adapter 类可构造（不强制跑 live LLM）。"""
    # ResearchAgent 依赖 W14 本地模块；导入路径应可用
    assert ResearchAgentTraceAdapter is not None
    assert callable(_extract_contexts)
