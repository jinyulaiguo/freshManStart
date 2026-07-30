"""LangGraph node-level tracing helpers for Day 112."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from graph_state import ResearchState

NodeFn = Callable[[ResearchState], Awaitable[dict[str, Any]]]
_test_provider: trace.TracerProvider | None = None


def set_test_tracer_provider(provider: trace.TracerProvider | None) -> None:
    global _test_provider
    _test_provider = provider


def _next_visit(state: ResearchState, node_name: str) -> int:
    visits = dict(state.get("node_visits") or {})
    count = int(visits.get(node_name, 0)) + 1
    visits[node_name] = count
    return count


def _common_attributes(
    *,
    node_name: str,
    kind: str,
    query: str,
    visit_count: int,
) -> dict[str, Any]:
    return {
        "openinference.span.kind": kind,
        "gen_ai.operation.name": "invoke_workflow",
        "gen_ai.provider.name": "minimax",
        "gen_ai.request.model": "MiniMax-M3",
        "gen_ai.langgraph.node": node_name,
        "gen_ai.langgraph.visit_count": visit_count,
        "node.name": node_name,
        "query.preview": query[:240],
    }


def instrumented_node(node_name: str, *, kind: str) -> Callable[[NodeFn], NodeFn]:
    """Wrap a LangGraph async node with robust OTel context propagation."""

    def decorator(fn: NodeFn) -> NodeFn:
        async def wrapped(state: ResearchState) -> dict[str, Any]:
            parent_ctx = otel_context.get_current()
            token = otel_context.attach(parent_ctx)
            try:
                tracer = (
                    _test_provider.get_tracer("freshman.w16.day112.langgraph")
                    if _test_provider is not None
                    else trace.get_tracer("freshman.w16.day112.langgraph")
                )
                visit_count = _next_visit(state, node_name)
                query = str(state.get("query", ""))

                with tracer.start_as_current_span(f"LangGraph Node {node_name}") as span:
                    t0 = time.monotonic()
                    for key, value in _common_attributes(
                        node_name=node_name,
                        kind=kind,
                        query=query,
                        visit_count=visit_count,
                    ).items():
                        span.set_attribute(key, value)
                    try:
                        delta = await fn(state)
                    except Exception as exc:
                        span.record_exception(exc)
                        span.set_status(Status(StatusCode.ERROR, str(exc)))
                        raise
                    finally:
                        span.set_attribute(
                            "duration_ms",
                            round((time.monotonic() - t0) * 1000.0, 3),
                        )

                visits = dict(state.get("node_visits") or {})
                visits[node_name] = visit_count
                visited_nodes = list(state.get("visited_nodes") or [])
                visited_nodes.append(node_name)

                merged = dict(delta)
                merged["node_visits"] = visits
                merged["visited_nodes"] = visited_nodes
                return merged
            finally:
                otel_context.detach(token)

        return wrapped

    return decorator
