from __future__ import annotations

import asyncio
import sys
from pathlib import Path

DAY_DIR = Path(__file__).resolve().parents[1]
if str(DAY_DIR) not in sys.path:
    sys.path.insert(0, str(DAY_DIR))

import research_graph


async def _fake_stream_llm(*, span_name: str, system: str, user: str):
    _ = (span_name, system, user)
    return "mock answer", 10, 20, 120.0, 450.0


def test_graph_success_and_fallback(monkeypatch) -> None:
    monkeypatch.setattr(research_graph, "_stream_llm", _fake_stream_llm)
    ok = asyncio.run(research_graph.run_research_assistant("正常请求"))
    assert ok.get("reflection_status") == "success"
    assert ok.get("report")

    failed = asyncio.run(research_graph.run_research_assistant("故障注入 force_fail"))
    assert failed.get("reflection_status") == "fallback"
    assert "系统降级" in str(failed.get("answer", ""))
