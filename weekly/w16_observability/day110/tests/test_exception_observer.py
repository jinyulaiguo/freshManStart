from __future__ import annotations

import json
from pathlib import Path
import sys

DAY_DIR = Path(__file__).resolve().parents[1]
if str(DAY_DIR) not in sys.path:
    sys.path.insert(0, str(DAY_DIR))

from exception_observer import ExceptionObserver


def _boom() -> None:
    dividend = 10
    divisor = 0
    tool_name = "tool_divide"
    _ = dividend / divisor


def test_capture_and_mask() -> None:
    observer = ExceptionObserver(
        log_path=Path('/tmp/day110_test.json'),
        local_whitelist={"dividend", "divisor", "tool_name"},
    )
    try:
        _boom()
    except Exception as exc:
        payload = observer.capture(exc)

    assert payload["error_type"] == "ZeroDivisionError"
    assert payload["locals"]["dividend"] == "10"
    assert payload["locals"]["divisor"] == "0"
    assert payload["locals"]["tool_name"] == "'tool_divide'"
    assert payload["traceback"]


def test_emit_json(tmp_path: Path) -> None:
    path = tmp_path / "err.json"
    observer = ExceptionObserver(log_path=path, local_whitelist=set())
    payload = {"error_type": "X", "traceback": [], "locals": {}}
    observer.emit_json(payload)
    loaded = json.loads(path.read_text(encoding='utf-8'))
    assert loaded["error_type"] == "X"
