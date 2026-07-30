"""Day 110 · 异常观测器：traceback 结构化 + 脱敏 + Span 事件。"""

from __future__ import annotations

import json
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from opentelemetry.trace import Span


def _mask_value(value: Any, *, max_len: int = 160) -> str:
    text = repr(value)
    if len(text) > max_len:
        return text[:max_len] + "...<truncated>"
    return text


@dataclass
class ExceptionObserver:
    log_path: Path
    local_whitelist: set[str]

    def capture(self, exc: BaseException) -> dict[str, Any]:
        tb = exc.__traceback__
        frames: list[dict[str, Any]] = []
        last_locals: dict[str, Any] = {}

        while tb is not None:
            frame = tb.tb_frame
            frame_info = {
                "file": frame.f_code.co_filename,
                "function": frame.f_code.co_name,
                "line": tb.tb_lineno,
            }
            frames.append(frame_info)
            if tb.tb_next is None:
                for key in self.local_whitelist:
                    if key in frame.f_locals:
                        last_locals[key] = _mask_value(frame.f_locals[key])
            tb = tb.tb_next

        payload = {
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "traceback": frames,
            "locals": last_locals,
            "stacktrace_text": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[:6000],
        }
        return payload

    def record_to_span(self, span: Span, payload: dict[str, Any]) -> None:
        span.set_attribute("error.type", payload.get("error_type", ""))
        span.set_attribute("error.message", payload.get("error_message", ""))
        span.add_event(
            "exception.structured",
            attributes={
                "error.type": payload.get("error_type", ""),
                "error.message": payload.get("error_message", ""),
                "traceback.frames": json.dumps(payload.get("traceback", []), ensure_ascii=False)[:8000],
                "locals.whitelisted": json.dumps(payload.get("locals", {}), ensure_ascii=False)[:8000],
            },
        )

    def emit_json(self, payload: dict[str, Any]) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print("[day110][error.json]")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
