from __future__ import annotations

import sys
from pathlib import Path

DAY_DIR = Path(__file__).resolve().parents[1]
if str(DAY_DIR) not in sys.path:
    sys.path.insert(0, str(DAY_DIR))

from metrics_tracker import MetricsTracker, REQUESTS_TOTAL, ACTIVE_COROUTINES, REQUEST_LATENCY


def _counter_value(status: str) -> float:
    return REQUESTS_TOTAL.labels(status=status)._value.get()


def test_track_success_and_error() -> None:
    tracker = MetricsTracker()

    ok0 = _counter_value("success")
    err0 = _counter_value("error")

    with tracker.track_request():
        pass

    try:
        with tracker.track_request():
            raise ValueError("boom")
    except ValueError:
        pass

    assert _counter_value("success") == ok0 + 1
    assert _counter_value("error") == err0 + 1
    assert ACTIVE_COROUTINES._value.get() == 0
    samples = REQUEST_LATENCY.collect()[0].samples
    count_sample = next(s for s in samples if s.name.endswith("_count"))
    assert count_sample.value >= 2
