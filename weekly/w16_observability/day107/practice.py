"""
Week 16 Day 107 练习入口: 本地 Phoenix + OpenInference 追踪

===============================================================================
练习目标
===============================================================================
1. 确认本地 Phoenix（docker compose）已在 :6006 运行。
2. 通过 phoenix_otel 注册 OTLP Exporter + LangChainInstrumentor。
3. 复用 Day 106 的零改动 ReAct Agent，在 Phoenix UI 还原 LLM I/O 与工具 Span。

运行:
  cd weekly/w16_observability/day107
  python practice.py
===============================================================================
"""

from __future__ import annotations

import sys
from pathlib import Path

DAY_DIR = Path(__file__).resolve().parent
DAY106_DIR = DAY_DIR.parent / "day106"
if str(DAY106_DIR) not in sys.path:
    sys.path.insert(0, str(DAY106_DIR))
if str(DAY_DIR) not in sys.path:
    sys.path.insert(0, str(DAY_DIR))

from agent_core import run_agent  # noqa: E402
from phoenix_otel import enable_phoenix_otel, flush_traces  # noqa: E402

DEFAULT_QUERY = (
    "请查询 SKU-2002 的库存与单价，然后按采购 2 件计算报价小计，"
    "并说明库存是否足够。"
)


def main() -> None:
    status = enable_phoenix_otel(verbose=True)
    printable = {k: v for k, v in status.items() if k != "tracer_provider"}
    print("[Day107] Phoenix / OpenInference bound:")
    for k, v in printable.items():
        print(f"  {k}={v}")

    print(f"[Day107] query: {DEFAULT_QUERY}")
    answer = run_agent(DEFAULT_QUERY)
    flush_traces()
    print("[Day107] agent answer:")
    print(answer)
    print()
    print("[Day107] 打开 http://0.0.0.0:6006 （勿用 localhost）")
    print(f"         项目: {status['PHOENIX_PROJECT_NAME']}")
    print("         验收: Trace 中可见 LLM input/output 与 lookup_stock / calc_quote")


if __name__ == "__main__":
    main()
