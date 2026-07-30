"""Day 111 · 可执行入口：真实链路 + 指标暴露 + 100 次高频模拟。"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
import time
from pathlib import Path
from urllib.request import urlopen

from prometheus_client import start_http_server

DAY_DIR = Path(__file__).resolve().parent
W16 = DAY_DIR.parent
DAY109 = W16 / "day109"

for p in (DAY_DIR, DAY109):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from metrics_tracker import MetricsTracker
from costed_graph import run_costed_graph
from phoenix_otel import enable_phoenix_otel, flush_traces, load_repo_env


async def _real_request(tracker: MetricsTracker) -> None:
    query = "真实链路验证: OpenInference 与 Phoenix 可观测性要点"
    with tracker.track_request():
        await run_costed_graph(query)


async def _synthetic_request(tracker: MetricsTracker, idx: int) -> None:
    # 高频压测走轻量路径，避免 100 次真实 LLM 造成不必要成本
    with tracker.track_request():
        await asyncio.sleep(0.02 + (idx % 5) * 0.01)


async def run_high_freq_simulation(total: int = 100, concurrency: int = 20) -> None:
    tracker = MetricsTracker()
    # 至少 1 次真实链路，满足“真实场景”约束
    await _real_request(tracker)

    sem = asyncio.Semaphore(concurrency)

    async def worker(i: int) -> None:
        async with sem:
            await _synthetic_request(tracker, i)

    await asyncio.gather(*(worker(i) for i in range(1, total + 1)))


def _print_metrics_snapshot(port: int) -> None:
    text = urlopen(f"http://0.0.0.0:{port}/metrics", timeout=10).read().decode("utf-8")
    keep = []
    pattern = re.compile(r"^(agent_requests_total|agent_active_coroutines|agent_request_latency_seconds_bucket|agent_request_latency_seconds_sum|agent_request_latency_seconds_count)")
    for line in text.splitlines():
        if pattern.match(line):
            keep.append(line)
    print("[day111] metrics snapshot:")
    for line in keep[:40]:
        print(line)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Day111 metrics exporter")
    parser.add_argument("--total", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--serve-seconds", type=int, default=180, help="模拟后继续暴露/metrics秒数")
    parser.add_argument("--serve-forever", action="store_true", help="持续暴露/metrics直到手动停止")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    load_repo_env()
    status = enable_phoenix_otel(verbose=True)

    port = int(os.getenv("AGENT_METRICS_PORT", "9108"))
    start_http_server(port, addr="0.0.0.0")
    print(f"[day111] /metrics on http://0.0.0.0:{port}/metrics")
    print(f"[day111] phoenix project={status['PHOENIX_PROJECT_NAME']}")

    asyncio.run(run_high_freq_simulation(total=args.total, concurrency=args.concurrency))
    flush_traces()
    _print_metrics_snapshot(port)

    if args.serve_forever:
        print("[day111] keep serving /metrics forever (Ctrl+C stop)")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("[day111] stopped")
        return

    if args.serve_seconds > 0:
        print(f"[day111] keep serving /metrics for {args.serve_seconds}s")
        time.sleep(args.serve_seconds)


if __name__ == "__main__":
    main()
