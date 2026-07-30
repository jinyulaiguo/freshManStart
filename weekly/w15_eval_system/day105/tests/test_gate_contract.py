"""Day 105 gate contract tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

W15 = Path(__file__).resolve().parents[2]
for p in (str(W15), str(W15 / "gate")):
    if p not in sys.path:
        sys.path.insert(0, p)

from contracts.schemas import CaseEvalResult, EvalRunReport  # noqa: E402
from threshold_gate_impl import ThresholdGate  # noqa: E402


def _report(tool_f1: float, faithfulness: float) -> EvalRunReport:
    return EvalRunReport(
        run_id="gate-contract",
        aggregate={"tool_f1": tool_f1, "faithfulness": faithfulness},
        thresholds=dict(ThresholdGate.DEFAULT_THRESHOLDS),
        cases=[
            CaseEvalResult(
                test_case_id="research_001",
                passed=tool_f1 >= 0.85 and faithfulness >= 0.90,
                tool_f1=tool_f1,
                faithfulness=faithfulness,
            )
        ],
    )


def test_gate_pass_at_thresholds():
    v = ThresholdGate().check(_report(0.85, 0.90), mode="pr")
    assert v.passed
    assert v.failed_metrics == []


def test_gate_fail_below_tool_f1():
    v = ThresholdGate().check(_report(0.84, 0.99), mode="pr")
    assert not v.passed
    assert "tool_f1" in v.failed_metrics


def test_gate_fail_below_faithfulness():
    v = ThresholdGate().check(_report(0.99, 0.89), mode="pr")
    assert not v.passed
    assert "faithfulness" in v.failed_metrics


def test_enforce_raises_systemexit():
    with pytest.raises(SystemExit) as exc:
        ThresholdGate().enforce(_report(0.5, 0.5), mode="pr")
    assert exc.value.code == 1
