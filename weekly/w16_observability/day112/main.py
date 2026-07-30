"""Day112 executable entrypoint."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from prometheus_client import start_http_server

DAY_DIR = Path(__file__).resolve().parent
W16_DIR = DAY_DIR.parent
DAY107 = W16_DIR / "day107"
if str(DAY107) not in sys.path:
    sys.path.insert(0, str(DAY107))

from phoenix_otel import enable_phoenix_otel, flush_traces, load_repo_env  # noqa: E402
from research_graph import run_research_assistant  # noqa: E402


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Day112 production observability graph")
    parser.add_argument("--total", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--serve-seconds", type=int, default=180)
    parser.add_argument("--serve-forever", action="store_true")
    return parser.parse_args()


async def _synthetic(total: int, concurrency: int) -> None:
    sem = asyncio.Semaphore(concurrency)

    async def worker(idx: int) -> None:
        async with sem:
            if idx % 25 == 0:
                await run_research_assistant("故障注入: force_fail 验证回退路径")
            else:
                await asyncio.sleep(0.02 + (idx % 6) * 0.01)

    await asyncio.gather(*(worker(i) for i in range(1, total + 1)))


def _print_metrics_snapshot(port: int) -> None:
    text = urlopen(f"http://0.0.0.0:{port}/metrics", timeout=10).read().decode("utf-8")
    pattern = re.compile(
        r"^(agent_requests_total|agent_active_coroutines|agent_request_latency_seconds_bucket|agent_node_latency_seconds_bucket|agent_tool_calls_total|agent_tokens_total|agent_cost_usd_total)"
    )
    lines = [line for line in text.splitlines() if pattern.match(line)]
    print("[day112] metrics snapshot:")
    for line in lines[:80]:
        print(line)


async def _run(total: int, concurrency: int) -> dict[str, Any]:
    success = await run_research_assistant("OpenInference 如何帮助定位 RAG 延迟并控制成本？")
    failure = await run_research_assistant("故障注入: force_fail 验证回退路径")
    await _synthetic(total, concurrency)
    return {"success": success, "failure": failure}


def main() -> None:
    args = _parse_args()
    load_repo_env()
    status = enable_phoenix_otel(verbose=True)
    port = int(os.getenv("AGENT_METRICS_PORT", "9108"))
    start_http_server(port, addr="0.0.0.0")
    print(f"[day112] /metrics: http://0.0.0.0:{port}/metrics")
    print("[day112] phoenix:", {k: v for k, v in status.items() if k != "tracer_provider"})
    result = asyncio.run(_run(args.total, args.concurrency))
    flush_traces()
    print("[day112] success summary:")
    print(json.dumps(result["success"].get("cost_summary", {}), ensure_ascii=False, indent=2))
    print("[day112] failure reflection status:", result["failure"].get("reflection_status"))
    _print_metrics_snapshot(port)
    if args.serve_forever:
        print("[day112] keep serving forever")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("[day112] stopped")
        return
    if args.serve_seconds > 0:
        print(f"[day112] keep serving /metrics for {args.serve_seconds}s")
        time.sleep(args.serve_seconds)


if __name__ == "__main__":
    main()
