"""Day 112 graph state contract."""

from __future__ import annotations

from typing import Any, TypedDict


class ResearchState(TypedDict, total=False):
    """Shared state for Day112 research assistant graph."""

    query: str
    docs: list[dict[str, str]]
    chunks: list[dict[str, Any]]
    outline: str
    answer: str
    tool_result: str
    report: dict[str, Any]
    error: dict[str, Any]
    reflection_status: str
    fallback_reason: str
    node_visits: dict[str, int]
    visited_nodes: list[str]
