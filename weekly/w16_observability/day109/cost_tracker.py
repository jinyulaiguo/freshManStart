"""
Day 109 · Token / Latency / 美分成本账本（上卷到根 Trace）

并发安全：threading.Lock + contextvars，供 asyncio.gather 下多 Node 上报。
"""

from __future__ import annotations

import os
import threading
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from opentelemetry.trace import Span

_ledger_var: ContextVar[CostLedger | None] = ContextVar("day109_cost_ledger", default=None)


@dataclass
class NodeCost:
    name: str
    latency_ms: float
    input_tokens: int = 0
    output_tokens: int = 0
    ttft_ms: float | None = None


@dataclass
class CostLedger:
    """可观测性成本追踪：子 Node 上报 → 根 Span Attribute 汇总。"""

    price_input_usd_per_1m: float
    price_output_usd_per_1m: float
    nodes: list[NodeCost] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @classmethod
    def from_env(cls) -> CostLedger:
        return cls(
            price_input_usd_per_1m=float(
                os.getenv("LLM_PRICE_INPUT_USD_PER_1M", "0.15")
            ),
            price_output_usd_per_1m=float(
                os.getenv("LLM_PRICE_OUTPUT_USD_PER_1M", "0.60")
            ),
        )

    def record_node(
        self,
        name: str,
        *,
        latency_ms: float,
        input_tokens: int = 0,
        output_tokens: int = 0,
        ttft_ms: float | None = None,
    ) -> None:
        with self._lock:
            self.nodes.append(
                NodeCost(
                    name=name,
                    latency_ms=float(latency_ms),
                    input_tokens=int(input_tokens),
                    output_tokens=int(output_tokens),
                    ttft_ms=ttft_ms,
                )
            )

    @property
    def input_tokens(self) -> int:
        with self._lock:
            return sum(n.input_tokens for n in self.nodes)

    @property
    def output_tokens(self) -> int:
        with self._lock:
            return sum(n.output_tokens for n in self.nodes)

    def estimate_usd(self, input_tokens: int | None = None, output_tokens: int | None = None) -> float:
        inn = self.input_tokens if input_tokens is None else input_tokens
        out = self.output_tokens if output_tokens is None else output_tokens
        usd = (inn / 1_000_000.0) * self.price_input_usd_per_1m + (
            out / 1_000_000.0
        ) * self.price_output_usd_per_1m
        return round(usd, 8)

    def summary(self, *, total_latency_ms: float | None = None) -> dict[str, Any]:
        with self._lock:
            nodes_snap = list(self.nodes)
        inn = sum(n.input_tokens for n in nodes_snap)
        out = sum(n.output_tokens for n in nodes_snap)
        usd = self.estimate_usd(inn, out)
        latency = (
            total_latency_ms
            if total_latency_ms is not None
            else sum(n.latency_ms for n in nodes_snap)
        )
        return {
            "total_latency_ms": round(float(latency), 3),
            "input_tokens": inn,
            "output_tokens": out,
            "total_tokens": inn + out,
            "cost_usd": usd,
            "cost_cents": round(usd * 100.0, 4),
            "price_input_usd_per_1m": self.price_input_usd_per_1m,
            "price_output_usd_per_1m": self.price_output_usd_per_1m,
            "nodes": [
                {
                    "name": n.name,
                    "latency_ms": n.latency_ms,
                    "input_tokens": n.input_tokens,
                    "output_tokens": n.output_tokens,
                    "ttft_ms": n.ttft_ms,
                }
                for n in nodes_snap
            ],
        }

    def apply_to_span(self, root_span: Span, *, total_latency_ms: float) -> dict[str, Any]:
        data = self.summary(total_latency_ms=total_latency_ms)
        root_span.set_attribute("cost.input_tokens", data["input_tokens"])
        root_span.set_attribute("cost.output_tokens", data["output_tokens"])
        root_span.set_attribute("cost.total_tokens", data["total_tokens"])
        root_span.set_attribute("cost.usd", data["cost_usd"])
        root_span.set_attribute("cost.cents", data["cost_cents"])
        root_span.set_attribute("cost.total_latency_ms", data["total_latency_ms"])
        return data


def attach_ledger(ledger: CostLedger):
    return _ledger_var.set(ledger)


def reset_ledger(token) -> None:
    _ledger_var.reset(token)


def get_ledger() -> CostLedger:
    ledger = _ledger_var.get()
    if ledger is None:
        raise RuntimeError("当前无 CostLedger，请先 attach_ledger")
    return ledger
