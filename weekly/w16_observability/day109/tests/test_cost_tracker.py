"""Day 109 单元测试：CostLedger 上卷与美分计算（不强制外网）。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

DAY_DIR = Path(__file__).resolve().parents[1]
DAY108 = DAY_DIR.parent / "day108"
for p in (DAY_DIR, DAY108):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import otel_nesting as nesting
from cost_tracker import CostLedger, attach_ledger, get_ledger, reset_ledger


def test_estimate_usd_and_cents() -> None:
    ledger = CostLedger(price_input_usd_per_1m=0.15, price_output_usd_per_1m=0.60)
    # 1M in + 1M out => 0.15 + 0.60 = 0.75
    assert ledger.estimate_usd(1_000_000, 1_000_000) == 0.75
    ledger.record_node("a", latency_ms=10, input_tokens=1000, output_tokens=500)
    # 1000/1e6*0.15 + 500/1e6*0.60 = 0.00015 + 0.0003 = 0.00045
    assert ledger.estimate_usd() == 0.00045
    summary = ledger.summary(total_latency_ms=12.5)
    assert summary["cost_cents"] == 0.045
    assert summary["input_tokens"] == 1000
    assert summary["output_tokens"] == 500
    assert summary["total_latency_ms"] == 12.5


def test_concurrent_records_rollup() -> None:
    import threading

    ledger = CostLedger(price_input_usd_per_1m=1.0, price_output_usd_per_1m=2.0)

    def worker(name: str, inn: int, out: int) -> None:
        ledger.record_node(name, latency_ms=1.0, input_tokens=inn, output_tokens=out)

    threads = [
        threading.Thread(target=worker, args=("n1", 100, 10)),
        threading.Thread(target=worker, args=("n2", 200, 20)),
        threading.Thread(target=worker, args=("n3", 50, 5)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert ledger.input_tokens == 350
    assert ledger.output_tokens == 35


def test_apply_to_root_span_attributes() -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    nesting.set_test_tracer_provider(provider)
    ledger = CostLedger(price_input_usd_per_1m=0.15, price_output_usd_per_1m=0.60)
    token = attach_ledger(ledger)
    try:
        with nesting.span("pipeline", kind="AGENT") as root:
            get_ledger().record_node(
                "outline_llm", latency_ms=100, input_tokens=200, output_tokens=50, ttft_ms=30
            )
            get_ledger().record_node(
                "synthesize_llm", latency_ms=200, input_tokens=400, output_tokens=100
            )
            summary = ledger.apply_to_span(root, total_latency_ms=350)
    finally:
        reset_ledger(token)
        nesting.set_test_tracer_provider(None)

    assert summary["input_tokens"] == 600
    assert summary["output_tokens"] == 150
    finished = exporter.get_finished_spans()
    root = next(s for s in finished if s.name == "pipeline")
    assert root.attributes["cost.input_tokens"] == 600
    assert root.attributes["cost.output_tokens"] == 150
    assert root.attributes["cost.total_latency_ms"] == 350.0
