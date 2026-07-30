"""
Day 107 · 真实可执行入口：Phoenix OTEL + Day106 ReAct Agent

运行:
  python traced_agent.py
"""

from __future__ import annotations

import sys
from pathlib import Path

DAY_DIR = Path(__file__).resolve().parent
DAY106_DIR = DAY_DIR.parent / "day106"
for p in (DAY_DIR, DAY106_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from agent_core import run_agent
from phoenix_otel import enable_phoenix_otel, flush_traces


def main() -> None:
    status = enable_phoenix_otel(verbose=True)
    printable = {k: v for k, v in status.items() if k != "tracer_provider"}
    print("[day107] Phoenix bound:", printable)
    query = (
        "请查询 SKU-2002 的库存与单价，然后按采购 2 件计算报价小计，"
        "并说明库存是否足够。"
    )
    print("[day107] query:", query)
    answer = run_agent(query)
    flush_traces()
    print("[day107] answer:")
    print(answer)
    print()
    ui = printable["PHOENIX_ENDPOINT"].replace("/v1/traces", "")
    print(f"[day107] Phoenix UI: {ui}  project={printable['PHOENIX_PROJECT_NAME']}")


if __name__ == "__main__":
    main()
