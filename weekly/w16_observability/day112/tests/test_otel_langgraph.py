from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

DAY_DIR = Path(__file__).resolve().parents[1]
if str(DAY_DIR) not in sys.path:
    sys.path.insert(0, str(DAY_DIR))

from otel_langgraph import instrumented_node, set_test_tracer_provider


def test_instrumented_node_emits_span() -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    set_test_tracer_provider(provider)

    @instrumented_node("demo_node", kind="CHAIN")
    async def _node(state):
        return {"ok": True}

    out = asyncio.run(_node({"query": "hello"}))
    assert out["ok"] is True
    spans = exporter.get_finished_spans()
    assert any(s.name == "LangGraph Node demo_node" for s in spans)
    set_test_tracer_provider(None)
