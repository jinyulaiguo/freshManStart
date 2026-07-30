"""Prometheus metrics registry for Day112."""

from __future__ import annotations

import sys
from pathlib import Path

from prometheus_client import Counter, Histogram

DAY_DIR = Path(__file__).resolve().parent
DAY111 = DAY_DIR.parent / "day111"
if str(DAY111) not in sys.path:
    sys.path.insert(0, str(DAY111))

from metrics_tracker import ACTIVE_COROUTINES, REQUEST_LATENCY, REQUESTS_TOTAL  # noqa: E402

NODE_LATENCY = Histogram(
    "agent_node_latency_seconds",
    "Per LangGraph node latency in seconds",
    labelnames=("node",),
    buckets=(0.01, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10),
)
LLM_CALL_DURATION = Histogram(
    "agent_llm_call_duration_seconds",
    "LLM call duration in seconds by node",
    labelnames=("node",),
    buckets=(0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 20),
)
LLM_TTFT_SECONDS = Histogram(
    "agent_llm_ttft_seconds",
    "LLM time-to-first-token in seconds by node",
    labelnames=("node",),
    buckets=(0.05, 0.1, 0.2, 0.5, 1, 2, 5),
)
TOOL_CALLS_TOTAL = Counter(
    "agent_tool_calls_total",
    "Tool calls by tool and status",
    labelnames=("tool", "status"),
)
TOKENS_TOTAL = Counter(
    "agent_tokens_total",
    "Token totals by type",
    labelnames=("type",),
)
COST_USD_TOTAL = Counter(
    "agent_cost_usd_total",
    "Estimated cost in USD",
)


def observe_node_latency(node: str, seconds: float) -> None:
    NODE_LATENCY.labels(node=node).observe(max(0.0, seconds))


def observe_llm(node: str, duration_s: float, ttft_s: float | None) -> None:
    LLM_CALL_DURATION.labels(node=node).observe(max(0.0, duration_s))
    if ttft_s is not None:
        LLM_TTFT_SECONDS.labels(node=node).observe(max(0.0, ttft_s))


def observe_tool(tool: str, status: str) -> None:
    TOOL_CALLS_TOTAL.labels(tool=tool, status=status).inc()


def observe_tokens(input_tokens: int, output_tokens: int) -> None:
    TOKENS_TOTAL.labels(type="input").inc(max(0, int(input_tokens)))
    TOKENS_TOTAL.labels(type="output").inc(max(0, int(output_tokens)))


def observe_cost(cost_usd: float) -> None:
    COST_USD_TOTAL.inc(max(0.0, float(cost_usd)))


__all__ = [
    "ACTIVE_COROUTINES",
    "REQUEST_LATENCY",
    "REQUESTS_TOTAL",
    "COST_USD_TOTAL",
    "LLM_CALL_DURATION",
    "LLM_TTFT_SECONDS",
    "NODE_LATENCY",
    "TOKENS_TOTAL",
    "TOOL_CALLS_TOTAL",
    "observe_cost",
    "observe_llm",
    "observe_node_latency",
    "observe_tokens",
    "observe_tool",
]
