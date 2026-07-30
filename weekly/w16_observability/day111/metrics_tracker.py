"""Day 111 · Prometheus 指标跟踪器。"""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

from prometheus_client import Counter, Gauge, Histogram

REQUESTS_TOTAL = Counter(
    "agent_requests_total",
    "Total number of agent requests",
    labelnames=("status",),
)
ACTIVE_COROUTINES = Gauge(
    "agent_active_coroutines",
    "Current number of active coroutines",
)
REQUEST_LATENCY = Histogram(
    "agent_request_latency_seconds",
    "Agent request latency seconds",
    buckets=(0.01, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 30),
)


@dataclass
class MetricsTracker:
    """请求级指标上下文：自动维护 counter/gauge/histogram。"""

    @contextmanager
    def track_request(self) -> Iterator[None]:
        start = time.monotonic()
        ACTIVE_COROUTINES.inc()
        status = "success"
        try:
            yield
        except Exception:
            status = "error"
            raise
        finally:
            elapsed = time.monotonic() - start
            REQUEST_LATENCY.observe(elapsed)
            REQUESTS_TOTAL.labels(status=status).inc()
            ACTIVE_COROUTINES.dec()
