from __future__ import annotations

import sys
from pathlib import Path

DAY_DIR = Path(__file__).resolve().parents[1]
if str(DAY_DIR) not in sys.path:
    sys.path.insert(0, str(DAY_DIR))

from reflection_policy import run_reflection_tool


def test_reflection_success() -> None:
    result = run_reflection_tool(doc_id="DOC-001", force_fail=False, max_attempts=1)
    assert result["status"] == "success"
    assert int(result["data"]["citation_count"]) > 0


def test_reflection_fallback(tmp_path: Path) -> None:
    result = run_reflection_tool(
        doc_id="DOC-FAIL",
        force_fail=True,
        max_attempts=2,
        sleep_ms=1,
        log_path=tmp_path / "error.json",
    )
    assert result["status"] == "fallback"
    assert "fallback_reason" in result
