from __future__ import annotations

import sys
from pathlib import Path

DAY_DIR = Path(__file__).resolve().parents[1]
if str(DAY_DIR) not in sys.path:
    sys.path.insert(0, str(DAY_DIR))

from metrics_registry import (
    COST_USD_TOTAL,
    TOOL_CALLS_TOTAL,
    observe_cost,
    observe_llm,
    observe_node_latency,
    observe_tokens,
    observe_tool,
)


def test_metrics_observe_helpers() -> None:
    tool_before = TOOL_CALLS_TOTAL.labels(tool="fetch_citation_count", status="success")._value.get()
    cost_before = COST_USD_TOTAL._value.get()
    observe_node_latency("rag_retrieve", 0.2)
    observe_llm("synthesize_llm", 0.3, 0.05)
    observe_tool("fetch_citation_count", "success")
    observe_tokens(11, 7)
    observe_cost(0.002)
    assert TOOL_CALLS_TOTAL.labels(tool="fetch_citation_count", status="success")._value.get() == tool_before + 1
    assert COST_USD_TOTAL._value.get() == cost_before + 0.002
