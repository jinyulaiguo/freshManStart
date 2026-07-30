"""Structured JSONL access logging for Day112."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def append_access_log(
    *,
    log_path: Path,
    trace_id: str,
    query: str,
    status: str,
    latency_ms: float,
    cost_usd: float,
    visited_nodes: list[str],
    metadata: dict[str, Any] | None = None,
) -> None:
    payload = {
        "ts": datetime.now(UTC).isoformat(),
        "trace_id": trace_id,
        "query_preview": query[:200],
        "status": status,
        "latency_ms": round(latency_ms, 3),
        "cost_usd": round(cost_usd, 8),
        "visited_nodes": visited_nodes,
    }
    if metadata:
        payload["metadata"] = metadata

    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError:
        # 日志落盘失败不应中断主链路
        return
