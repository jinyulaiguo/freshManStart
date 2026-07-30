"""Day112 LangGraph production observability graph."""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from opentelemetry import trace

DAY_DIR = Path(__file__).resolve().parent
W16_DIR = DAY_DIR.parent
DAY107 = W16_DIR / "day107"
DAY109 = W16_DIR / "day109"
DAY111 = W16_DIR / "day111"
for p in (DAY_DIR, DAY107, DAY109, DAY111):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from access_log import append_access_log  # noqa: E402
from cost_tracker import CostLedger, attach_ledger, get_ledger, reset_ledger  # noqa: E402
from graph_state import ResearchState  # noqa: E402
from metrics_registry import (  # noqa: E402
    observe_cost,
    observe_llm,
    observe_node_latency,
    observe_tokens,
    observe_tool,
)
from otel_langgraph import instrumented_node  # noqa: E402
from reflection_policy import run_reflection_tool  # noqa: E402
from metrics_tracker import MetricsTracker  # noqa: E402

CORPUS_PATH = W16_DIR / "day108" / "corpus" / "papers.json"
ACCESS_LOG_PATH = DAY_DIR / "logs" / "access.jsonl"


def _build_llm() -> ChatOpenAI:
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


def _usage_from_chunk(chunk: Any) -> tuple[int, int]:
    usage = getattr(chunk, "usage_metadata", None) or {}
    if not usage and hasattr(chunk, "response_metadata"):
        usage = (chunk.response_metadata or {}).get("token_usage") or {}
    inn = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
    out = int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
    return inn, out


async def _stream_llm(
    *,
    span_name: str,
    system: str,
    user: str,
) -> tuple[str, int, int, float | None, float]:
    llm = _build_llm()
    tracer = trace.get_tracer("freshman.w16.day112.llm")
    t0 = time.monotonic()
    ttft_ms: float | None = None
    parts: list[str] = []
    final_chunk = None
    messages = [SystemMessage(content=system), HumanMessage(content=user)]
    with tracer.start_as_current_span(span_name) as span:
        span.set_attribute("openinference.span.kind", "LLM")
        span.set_attribute("gen_ai.operation.name", "chat")
        span.set_attribute("gen_ai.provider.name", "minimax")
        span.set_attribute("gen_ai.request.model", str(llm.model_name))
        span.set_attribute(
            "llm.input_messages",
            json.dumps(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                ensure_ascii=False,
            )[:8000],
        )
        async for chunk in llm.astream(messages):
            content = chunk.content if isinstance(chunk.content, str) else ""
            if content and ttft_ms is None:
                ttft_ms = (time.monotonic() - t0) * 1000
                span.set_attribute("ttft_ms", round(ttft_ms, 3))
            if content:
                parts.append(content)
            final_chunk = chunk

        text = "".join(parts)
        inn, out = (0, 0) if final_chunk is None else _usage_from_chunk(final_chunk)
        if inn == 0 and out == 0:
            inn = max(1, len(system + user) // 4)
            out = max(1, len(text) // 4)
            span.set_attribute("llm.token_count.estimated", True)
        span.set_attribute("llm.token_count.prompt", inn)
        span.set_attribute("llm.token_count.completion", out)
        span.set_attribute("gen_ai.usage.input_tokens", inn)
        span.set_attribute("gen_ai.usage.output_tokens", out)
        span.set_attribute(
            "llm.output_messages",
            json.dumps([{"role": "assistant", "content": text}], ensure_ascii=False)[:8000],
        )

    elapsed_ms = (time.monotonic() - t0) * 1000
    return text, inn, out, ttft_ms, elapsed_ms


@instrumented_node("load_corpus", kind="CHAIN")
async def node_load_corpus(state: ResearchState) -> dict[str, Any]:
    t0 = time.monotonic()
    docs = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    elapsed = time.monotonic() - t0
    observe_node_latency("load_corpus", elapsed)
    get_ledger().record_node("load_corpus", latency_ms=elapsed * 1000)
    return {"docs": docs}


@instrumented_node("rag_retrieve", kind="RETRIEVER")
async def node_rag_retrieve(state: ResearchState) -> dict[str, Any]:
    t0 = time.monotonic()
    query = str(state.get("query", ""))
    docs = state.get("docs") or []
    terms = {
        token
        for token in re.findall(r"[a-zA-Z0-9\u4e00-\u9fff]+", query.lower())
        if len(token) > 1
    }
    scored: list[dict[str, Any]] = []
    for doc in docs:
        text = f"{doc.get('title', '')} {doc.get('text', '')}".lower()
        overlap = sum(1 for term in terms if term in text)
        scored.append({**doc, "score": float(overlap)})
    scored.sort(key=lambda x: x["score"], reverse=True)
    chunks = scored[:2]
    elapsed = time.monotonic() - t0
    observe_node_latency("rag_retrieve", elapsed)
    get_ledger().record_node("rag_retrieve", latency_ms=elapsed * 1000)
    return {"chunks": chunks}


@instrumented_node("outline_llm", kind="LLM")
async def node_outline_llm(state: ResearchState) -> dict[str, Any]:
    query = str(state.get("query", ""))
    text, inn, out, ttft_ms, elapsed_ms = await _stream_llm(
        span_name="outline_llm_call",
        system="你是研究助手提纲节点。输出不超过5条中文要点。",
        user=f"请针对问题生成提纲：{query}",
    )
    get_ledger().record_node(
        "outline_llm",
        latency_ms=elapsed_ms,
        input_tokens=inn,
        output_tokens=out,
        ttft_ms=ttft_ms,
    )
    observe_node_latency("outline_llm", elapsed_ms / 1000.0)
    observe_llm("outline_llm", elapsed_ms / 1000.0, None if ttft_ms is None else ttft_ms / 1000.0)
    observe_tokens(inn, out)
    return {"outline": text}


@instrumented_node("synthesize_llm", kind="LLM")
async def node_synthesize_llm(state: ResearchState) -> dict[str, Any]:
    query = str(state.get("query", ""))
    chunks = state.get("chunks") or []
    outline = str(state.get("outline", ""))
    context = "\n\n".join(
        f"[{chunk['doc_id']}] {chunk['title']}\n{chunk['text']}" for chunk in chunks
    )
    text, inn, out, ttft_ms, elapsed_ms = await _stream_llm(
        span_name="synthesize_llm_call",
        system="你是AI研究助手综合节点。回答时需引用doc_id，避免编造。",
        user=f"问题：{query}\n\n提纲：\n{outline}\n\n文献：\n{context}",
    )
    get_ledger().record_node(
        "synthesize_llm",
        latency_ms=elapsed_ms,
        input_tokens=inn,
        output_tokens=out,
        ttft_ms=ttft_ms,
    )
    observe_node_latency("synthesize_llm", elapsed_ms / 1000.0)
    observe_llm(
        "synthesize_llm",
        elapsed_ms / 1000.0,
        None if ttft_ms is None else ttft_ms / 1000.0,
    )
    observe_tokens(inn, out)
    return {"answer": text}


@instrumented_node("tool_reflect", kind="TOOL")
async def node_tool_reflect(state: ResearchState) -> dict[str, Any]:
    t0 = time.monotonic()
    chunks = state.get("chunks") or []
    doc_id = str(chunks[0]["doc_id"]) if chunks else "DOC-FAIL"
    query = str(state.get("query", ""))
    # "故障注入" query会触发工具失败，演示 fallback 分支。
    force_fail = "故障注入" in query or "force_fail" in query.lower()
    result = run_reflection_tool(doc_id=doc_id, force_fail=force_fail)
    elapsed = time.monotonic() - t0
    observe_node_latency("tool_reflect", elapsed)
    get_ledger().record_node("tool_reflect", latency_ms=elapsed * 1000)
    # Prometheus / 告警约定 status=success|error；业务降级状态仍写 reflection_status=fallback
    metric_status = "success" if result["status"] == "success" else "error"
    observe_tool("fetch_citation_count", metric_status)
    if result["status"] == "success":
        return {
            "tool_result": json.dumps(result["data"], ensure_ascii=False),
            "reflection_status": "success",
        }
    return {
        "tool_result": "",
        "reflection_status": "fallback",
        "fallback_reason": str(result.get("fallback_reason", "tool failed")),
        "error": result.get("error", {}),
    }


def route_reflection(state: ResearchState) -> str:
    return "fallback" if state.get("reflection_status") == "fallback" else "success"


@instrumented_node("fallback_response", kind="CHAIN")
async def node_fallback_response(state: ResearchState) -> dict[str, Any]:
    answer = str(state.get("answer", ""))
    reason = str(state.get("fallback_reason", "tool unavailable"))
    text = f"{answer}\n\n[系统降级] 工具不可用，已回退到基础答案。原因：{reason}"
    return {"answer": text}


@instrumented_node("postprocess", kind="CHAIN")
async def node_postprocess(state: ResearchState) -> dict[str, Any]:
    answer = str(state.get("answer", "")).strip()
    report = {
        "title": "Research Brief",
        "answer": answer,
        "retrieved_doc_ids": [chunk["doc_id"] for chunk in (state.get("chunks") or [])],
        "tool_result": state.get("tool_result", ""),
    }
    return {"report": report}


def build_graph() -> Any:
    builder = StateGraph(ResearchState)
    builder.add_node("load_corpus", node_load_corpus)
    builder.add_node("rag_retrieve", node_rag_retrieve)
    builder.add_node("outline_llm", node_outline_llm)
    builder.add_node("synthesize_llm", node_synthesize_llm)
    builder.add_node("tool_reflect", node_tool_reflect)
    builder.add_node("fallback_response", node_fallback_response)
    builder.add_node("postprocess", node_postprocess)
    builder.add_edge(START, "load_corpus")
    builder.add_edge("load_corpus", "rag_retrieve")
    builder.add_edge("rag_retrieve", "outline_llm")
    builder.add_edge("outline_llm", "synthesize_llm")
    builder.add_edge("synthesize_llm", "tool_reflect")
    builder.add_conditional_edges(
        "tool_reflect",
        route_reflection,
        {"success": "postprocess", "fallback": "fallback_response"},
    )
    builder.add_edge("fallback_response", "postprocess")
    builder.add_edge("postprocess", END)
    return builder.compile()


_GRAPH: Any | None = None


def _get_graph() -> Any:
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_graph()
    return _GRAPH


async def run_research_assistant(query: str) -> dict[str, Any]:
    tracker = MetricsTracker()
    ledger = CostLedger.from_env()
    token = attach_ledger(ledger)
    tracer = trace.get_tracer("freshman.w16.day112.pipeline")
    t0 = time.monotonic()
    status = "success"
    with tracker.track_request():
        try:
            with tracer.start_as_current_span("pipeline") as root:
                root.set_attribute("openinference.span.kind", "AGENT")
                root.set_attribute("gen_ai.operation.name", "invoke_workflow")
                root.set_attribute("gen_ai.provider.name", "minimax")
                result = await _get_graph().ainvoke({"query": query})
                total_latency_ms = (time.monotonic() - t0) * 1000.0
                summary = ledger.apply_to_span(root, total_latency_ms=total_latency_ms)
                observe_cost(float(summary["cost_usd"]))
                append_access_log(
                    log_path=ACCESS_LOG_PATH,
                    trace_id=f"{root.get_span_context().trace_id:032x}",
                    query=query,
                    status=status,
                    latency_ms=summary["total_latency_ms"],
                    cost_usd=summary["cost_usd"],
                    visited_nodes=list(result.get("visited_nodes") or []),
                    metadata={
                        "input_tokens": summary["input_tokens"],
                        "output_tokens": summary["output_tokens"],
                    },
                )
                result["cost_summary"] = summary
                return result
        except Exception:
            status = "error"
            raise
        finally:
            reset_ledger(token)


def run_research_assistant_sync(query: str) -> dict[str, Any]:
    return asyncio.run(run_research_assistant(query))
