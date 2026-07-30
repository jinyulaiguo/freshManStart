"""Reflection policy with retry and graceful fallback."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

DAY_DIR = Path(__file__).resolve().parent
DAY110 = DAY_DIR.parent / "day110"
if str(DAY110) not in sys.path:
    sys.path.insert(0, str(DAY110))

from exception_observer import ExceptionObserver  # noqa: E402
from tools import tool_summary  # noqa: E402


def run_reflection_tool(
    *,
    doc_id: str,
    force_fail: bool = False,
    max_attempts: int = 2,
    sleep_ms: int = 120,
    log_path: Path | None = None,
) -> dict[str, Any]:
    """Execute tool with one retry; return success or fallback payload."""
    observer = ExceptionObserver(
        log_path=log_path or (DAY_DIR / "logs" / "error_latest.json"),
        local_whitelist={"doc_id", "force_fail"},
    )
    current_span = trace.get_current_span()
    last_error: dict[str, Any] | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            data = tool_summary(doc_id, force_fail=force_fail)
            current_span.set_attribute("tool.name", "fetch_citation_count")
            current_span.set_attribute("gen_ai.tool.name", "fetch_citation_count")
            current_span.set_attribute("gen_ai.operation.name", "execute_tool")
            current_span.add_event(
                "tool.success",
                {
                    "attempt": attempt,
                    "result.preview": json.dumps(data, ensure_ascii=False)[:500],
                },
            )
            return {
                "status": "success",
                "attempt": attempt,
                "data": data,
            }
        except Exception as exc:  # pragma: no cover - exercised via tests
            payload = observer.capture(exc)
            observer.record_to_span(current_span, payload)
            observer.emit_json(payload)
            current_span.record_exception(exc)
            current_span.set_status(Status(StatusCode.ERROR, str(exc)))
            current_span.add_event("tool.retry", {"attempt": attempt, "error": str(exc)})
            last_error = payload
            if attempt < max_attempts:
                time.sleep(max(0, sleep_ms) / 1000.0)

    return {
        "status": "fallback",
        "attempt": max_attempts,
        "fallback_reason": (last_error or {}).get("error_message", "unknown tool error"),
        "error": last_error or {},
    }
