"""Day 108 单元测试：OTel 嵌套包装（不强制外网 LLM）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

DAY_DIR = Path(__file__).resolve().parents[1]
if str(DAY_DIR) not in sys.path:
    sys.path.insert(0, str(DAY_DIR))

import otel_nesting as nesting
from research_pipeline import CORPUS_PATH, load_corpus, rag_retrieve


@pytest.fixture()
def memory_tracer():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    nesting.set_test_tracer_provider(provider)
    yield exporter
    nesting.set_test_tracer_provider(None)
    exporter.clear()


def test_nested_spans_export_tree(memory_tracer: InMemorySpanExporter) -> None:
    with nesting.span("pipeline", kind="AGENT"):
        with nesting.span("load", kind="CHAIN"):
            nesting.add_event("corpus_loaded", doc_count=1)
        with nesting.span("rag", kind="RETRIEVER"):
            with nesting.span("rerank", kind="CHAIN"):
                pass

    spans = memory_tracer.get_finished_spans()
    names = {s.name for s in spans}
    assert names >= {"pipeline", "load", "rag", "rerank"}
    load = next(s for s in spans if s.name == "load")
    assert load.attributes.get("openinference.span.kind") == "CHAIN"
    assert any(e.name == "corpus_loaded" for e in load.events)


def test_traced_decorator(memory_tracer: InMemorySpanExporter) -> None:
    @nesting.traced("local_compute", kind="CHAIN")
    def work() -> int:
        nesting.add_event("done")
        return 42

    assert work() == 42
    finished = memory_tracer.get_finished_spans()
    assert any(s.name == "local_compute" for s in finished)


def test_real_corpus_rag_retrieve(memory_tracer: InMemorySpanExporter) -> None:
    docs = load_corpus(CORPUS_PATH)
    assert len(docs) >= 3
    chunks = rag_retrieve("OpenInference OpenTelemetry RAG latency", docs, top_k=2)
    assert len(chunks) == 2
    assert all("doc_id" in c for c in chunks)
    assert CORPUS_PATH.is_file()
    raw = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    assert isinstance(raw, list)
