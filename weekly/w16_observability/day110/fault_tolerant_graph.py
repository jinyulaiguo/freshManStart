"""Day 110 · 故障注入图：真实 LLM + 工具异常 + 结构化异常日志。"""

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
from opentelemetry.trace import Status, StatusCode

DAY_DIR = Path(__file__).resolve().parent
W16 = DAY_DIR.parent
DAY107 = W16 / "day107"
DAY108 = W16 / "day108"
CORPUS_PATH = DAY108 / "corpus" / "papers.json"
LOG_PATH = DAY_DIR / "logs" / "error_latest.json"

for p in (DAY_DIR, DAY107, DAY108):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from exception_observer import ExceptionObserver
from otel_nesting import add_event, aspan
from phoenix_otel import enable_phoenix_otel, flush_traces, load_repo_env


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
    )


def load_corpus() -> list[dict[str, str]]:
    docs = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    return docs


def rag_pick(query: str, docs: list[dict[str, str]]) -> list[dict[str, Any]]:
    q_terms = {t for t in re.findall(r"[a-zA-Z0-9\u4e00-\u9fff]+", query.lower()) if len(t) > 1}
    scored = []
    for doc in docs:
        text = f"{doc.get('title','')} {doc.get('text','')}".lower()
        overlap = sum(1 for t in q_terms if t in text)
        scored.append({**doc, "score": float(overlap)})
    scored.sort(key=lambda d: d["score"], reverse=True)
    return scored[:2]


def tool_divide(dividend: float, divisor: float) -> float:
    tool_name = "tool_divide"
    return dividend / divisor


async def run_fault_graph(query: str) -> dict[str, Any]:
    observer = ExceptionObserver(
        log_path=LOG_PATH,
        local_whitelist={"dividend", "divisor", "tool_name"},
    )

    async with aspan("pipeline", kind="AGENT", query=query):
        async with aspan("load", kind="CHAIN"):
            docs = load_corpus()
            add_event("corpus_loaded", count=len(docs))

        async with aspan("rag", kind="RETRIEVER"):
            chunks = rag_pick(query, docs)
            add_event("retrieve_done", kept=len(chunks))

        async with aspan("llm", kind="LLM", model=_build_llm().model_name) as llm_span:
            context = "\n\n".join(f"[{c['doc_id']}] {c['title']}\n{c['text']}" for c in chunks)
            messages = [
                SystemMessage(content="你是研究助手，请基于文献简要回答。"),
                HumanMessage(content=f"问题：{query}\n\n文献：\n{context}"),
            ]
            t0 = time.monotonic()
            resp = _build_llm().invoke(messages)
            llm_span.set_attribute("llm.latency_ms", round((time.monotonic() - t0) * 1000, 3))
            answer = resp.content if isinstance(resp.content, str) else str(resp.content)

        async with aspan("tool_divide", kind="TOOL") as tool_span:
            dividend = 42
            divisor = 0
            tool_name = "tool_divide"
            try:
                _ = tool_divide(dividend, divisor)
            except Exception as exc:
                payload = observer.capture(exc)
                observer.record_to_span(tool_span, payload)
                observer.emit_json(payload)
                tool_span.record_exception(exc)
                tool_span.set_status(Status(StatusCode.ERROR, str(exc)))
                raise

        return {"answer": answer}


def main() -> None:
    load_repo_env()
    status = enable_phoenix_otel(verbose=True)
    query = "请解释 OpenInference 与 OTel 在私有化观测中的关系。"
    print("[day110] Phoenix:", {k: v for k, v in status.items() if k != "tracer_provider"})

    try:
        asyncio.run(run_fault_graph(query))
    except ZeroDivisionError as exc:
        print(f"[day110] expected exception captured: {type(exc).__name__}: {exc}")
        print(f"[day110] structured log written: {LOG_PATH}")
    finally:
        flush_traces()

    print("[day110] 打开 Phoenix 检查 tool_divide Span 是否 ERROR 红色")


if __name__ == "__main__":
    main()
