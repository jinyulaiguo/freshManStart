"""
Day 109 · 并发研究助手形图 + 成本上卷（真实 MiniMax → Phoenix）

运行:
  python costed_graph.py
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

DAY_DIR = Path(__file__).resolve().parent
W16 = DAY_DIR.parent
DAY107 = W16 / "day107"
DAY108 = W16 / "day108"
CORPUS_PATH = DAY108 / "corpus" / "papers.json"

for p in (DAY_DIR, DAY107, DAY108):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from cost_tracker import (  # noqa: E402
    CostLedger,
    attach_ledger,
    get_ledger,
    reset_ledger,
)
from otel_nesting import add_event, aspan, span  # noqa: E402
from phoenix_otel import enable_phoenix_otel, flush_traces, load_repo_env  # noqa: E402


def _build_llm() -> ChatOpenAI:
    import os

    api_key = os.getenv("MINIMAX_API_KEY")
    if not api_key:
        raise ValueError("缺少 MINIMAX_API_KEY")
    return ChatOpenAI(
        model=os.getenv("MINIMAX_MODEL", "MiniMax-M3"),
        api_key=api_key,
        base_url=os.getenv("MINIMAX_BASE_URL", "https://api.minimax.chat/v1"),
        temperature=0,
        timeout=90.0,
        streaming=True,
    )


def _usage_from_response(resp: Any) -> tuple[int, int]:
    usage = getattr(resp, "usage_metadata", None) or {}
    if not usage and hasattr(resp, "response_metadata"):
        usage = (resp.response_metadata or {}).get("token_usage") or {}
    inn = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
    out = int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
    return inn, out


async def node_load() -> list[dict[str, str]]:
    async with aspan("load", kind="CHAIN", corpus_path=str(CORPUS_PATH)) as otel_span:
        t0 = time.monotonic()
        docs = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
        latency = (time.monotonic() - t0) * 1000
        add_event("corpus_loaded", doc_count=len(docs))
        get_ledger().record_node("load", latency_ms=latency)
        otel_span.set_attribute("node.latency_ms", round(latency, 3))
        return docs


async def node_rag(query: str, docs: list[dict[str, str]]) -> list[dict[str, Any]]:
    async with aspan("rag", kind="RETRIEVER", query=query) as otel_span:
        t0 = time.monotonic()
        q_terms = {
            t
            for t in re.findall(r"[a-zA-Z0-9\u4e00-\u9fff]+", query.lower())
            if len(t) > 1
        }
        scored: list[dict[str, Any]] = []
        for doc in docs:
            text = f"{doc.get('title', '')} {doc.get('text', '')}".lower()
            overlap = sum(1 for t in q_terms if t in text)
            scored.append({**doc, "score": float(overlap)})
        scored.sort(key=lambda d: d["score"], reverse=True)
        chunks = scored[:2]
        latency = (time.monotonic() - t0) * 1000
        add_event("retrieve_done", kept=len(chunks))
        get_ledger().record_node("rag", latency_ms=latency)
        otel_span.set_attribute("node.latency_ms", round(latency, 3))
        return chunks


async def _stream_llm(
    *,
    span_name: str,
    system: str,
    user: str,
) -> tuple[str, int, int, float | None]:
    llm = _build_llm()
    async with aspan(span_name, kind="LLM", model=str(llm.model_name)) as otel_span:
        t0 = time.monotonic()
        ttft_ms: float | None = None
        parts: list[str] = []
        otel_span.set_attribute(
            "llm.input_messages",
            json.dumps(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                ensure_ascii=False,
            )[:8000],
        )
        messages = [SystemMessage(content=system), HumanMessage(content=user)]
        # astream 拿 TTFT；再 invoke 一次拿 usage 不划算——改用 astream 累计后读 usage_metadata
        final_msg = None
        async for chunk in llm.astream(messages):
            piece = chunk.content if isinstance(chunk.content, str) else ""
            if piece and ttft_ms is None:
                ttft_ms = (time.monotonic() - t0) * 1000
                otel_span.set_attribute("ttft_ms", round(ttft_ms, 3))
            if piece:
                parts.append(piece)
            final_msg = chunk
        text = "".join(parts)
        latency = (time.monotonic() - t0) * 1000
        otel_span.set_attribute(
            "llm.output_messages",
            json.dumps([{"role": "assistant", "content": text}], ensure_ascii=False)[
                :8000
            ],
        )
        inn, out = 0, 0
        if final_msg is not None:
            inn, out = _usage_from_response(final_msg)
        # 部分兼容网关在 stream 末包不带 usage：回退估算
        if inn == 0 and out == 0:
            inn = max(1, len(system + user) // 4)
            out = max(1, len(text) // 4)
            otel_span.set_attribute("llm.token_count.estimated", True)
        otel_span.set_attribute("llm.token_count.prompt", inn)
        otel_span.set_attribute("llm.token_count.completion", out)
        otel_span.set_attribute("node.latency_ms", round(latency, 3))
        get_ledger().record_node(
            span_name,
            latency_ms=latency,
            input_tokens=inn,
            output_tokens=out,
            ttft_ms=ttft_ms,
        )
        return text, inn, out, ttft_ms


async def node_outline_llm(query: str) -> str:
    text, _, _, _ = await _stream_llm(
        span_name="outline_llm",
        system="你是研究助手的提纲节点。用中文输出不超过 5 条要点提纲，不要长文。",
        user=f"为问题生成检索综合提纲：{query}",
    )
    return text


async def node_synthesize_llm(
    query: str, chunks: list[dict[str, Any]], outline: str
) -> str:
    context = "\n\n".join(
        f"[{c['doc_id']}] {c['title']}\n{c['text']}" for c in chunks
    )
    text, _, _, _ = await _stream_llm(
        span_name="synthesize_llm",
        system=(
            "你是 AI 研究助手的综合节点。结合提纲与文献片段用中文作答，"
            "注明 doc_id，不要编造文献外事实。"
        ),
        user=f"问题：{query}\n\n提纲：\n{outline}\n\n文献：\n{context}",
    )
    return text


async def run_costed_graph(query: str) -> dict[str, Any]:
    ledger = CostLedger.from_env()
    token = attach_ledger(ledger)
    try:
        async with aspan("pipeline", kind="AGENT", query=query) as root:
            t0 = time.monotonic()
            docs = await node_load()
            # 并发：检索 || 提纲 LLM
            chunks, outline = await asyncio.gather(
                node_rag(query, docs),
                node_outline_llm(query),
            )
            answer = await node_synthesize_llm(query, chunks, outline)
            total_latency = (time.monotonic() - t0) * 1000
            summary = ledger.apply_to_span(root, total_latency_ms=total_latency)
            return {
                "query": query,
                "retrieved_doc_ids": [c["doc_id"] for c in chunks],
                "outline": outline,
                "answer": answer,
                "cost_summary": summary,
            }
    finally:
        reset_ledger(token)


def main() -> None:
    load_repo_env()
    status = enable_phoenix_otel(verbose=True)
    query = (
        "OpenInference 如何帮助定位 RAG 延迟？结合 Token 成本与私有化 Phoenix 说明。"
    )
    print(
        "[day109] Phoenix bound:",
        {k: v for k, v in status.items() if k != "tracer_provider"},
    )
    print("[day109] query:", query)
    result = asyncio.run(run_costed_graph(query))
    flush_traces()
    print("[day109] cost_summary:")
    print(json.dumps(result["cost_summary"], ensure_ascii=False, indent=2))
    print()
    print("[day109] answer preview:")
    print((result["answer"] or "")[:500])
    print()
    print("[day109] Phoenix UI:", status["PHOENIX_ENDPOINT"].replace("/v1/traces", ""))
    print("  根 Span 属性: cost.usd / cost.cents / cost.input_tokens / cost.total_latency_ms")
    print("  LLM Span: ttft_ms + llm.token_count.*")


if __name__ == "__main__":
    main()
