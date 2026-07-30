"""
Day 108 · 研究助手形四阶段流水线（真实语料 + 真实 MiniMax + 真实 Phoenix）

阶段：load → rag → llm → local_compute
嵌套 Span 经 otel_nesting 写入当前 TracerProvider（由 Day107 phoenix_otel 绑定）。

运行（模块自身可执行，无 practice.py）:
  cd weekly/w16_observability/day108
  python research_pipeline.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

DAY_DIR = Path(__file__).resolve().parent
DAY107_DIR = DAY_DIR.parent / "day107"
CORPUS_PATH = DAY_DIR / "corpus" / "papers.json"

if str(DAY107_DIR) not in sys.path:
    sys.path.insert(0, str(DAY107_DIR))
if str(DAY_DIR) not in sys.path:
    sys.path.insert(0, str(DAY_DIR))

from otel_nesting import add_event, aspan, span, traced  # noqa: E402
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
    )


def load_corpus(path: Path = CORPUS_PATH) -> list[dict[str, str]]:
    with span("load", kind="CHAIN", corpus_path=str(path)):
        docs = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(docs, list) and docs, "语料为空"
        add_event("corpus_loaded", doc_count=len(docs))
        return docs


def rag_retrieve(query: str, docs: list[dict[str, str]], top_k: int = 2) -> list[dict[str, Any]]:
    """基于真实语料的词项重叠检索（非 sleep 假数据）。"""
    with span("rag", kind="RETRIEVER", query=query, corpus_size=len(docs)):
        q_terms = {t for t in re.findall(r"[a-zA-Z0-9\u4e00-\u9fff]+", query.lower()) if len(t) > 1}
        scored: list[dict[str, Any]] = []
        for doc in docs:
            text = f"{doc.get('title', '')} {doc.get('text', '')}".lower()
            overlap = sum(1 for t in q_terms if t in text)
            scored.append({**doc, "score": float(overlap)})
        scored.sort(key=lambda d: d["score"], reverse=True)
        add_event("vector_search_done", top_k=top_k, mode="term_overlap")

        with span("rerank", kind="CHAIN"):
            chunks = scored[:top_k]
            add_event("rerank_done", kept=len(chunks))
        return chunks


def llm_synthesize(query: str, chunks: list[dict[str, Any]]) -> str:
    context = "\n\n".join(
        f"[{c['doc_id']}] {c['title']}\n{c['text']}" for c in chunks
    )
    llm = _build_llm()
    with span(
        "llm",
        kind="LLM",
        model=str(getattr(llm, "model_name", None) or getattr(llm, "model", "")),
        chunk_count=len(chunks),
    ) as otel_span:
        messages = [
            SystemMessage(
                content=(
                    "你是 AI 研究助手的检索综合节点。"
                    "只依据给定文献片段回答，用中文，注明引用 doc_id。"
                    "不要编造文献中不存在的内容。"
                )
            ),
            HumanMessage(
                content=f"用户问题：{query}\n\n文献片段：\n{context}"
            ),
        ]
        # OpenInference 风格属性（手工写入，便于 Phoenix 查看）
        otel_span.set_attribute("llm.input_messages", json.dumps([
            {"role": "system", "content": messages[0].content},
            {"role": "user", "content": messages[1].content},
        ], ensure_ascii=False)[:8000])

        resp = llm.invoke(messages)
        text = resp.content if isinstance(resp.content, str) else str(resp.content)
        otel_span.set_attribute(
            "llm.output_messages",
            json.dumps([{"role": "assistant", "content": text}], ensure_ascii=False)[:8000],
        )
        usage = getattr(resp, "usage_metadata", None) or {}
        if usage:
            otel_span.set_attribute("llm.token_count.prompt", int(usage.get("input_tokens") or 0))
            otel_span.set_attribute("llm.token_count.completion", int(usage.get("output_tokens") or 0))
        return text


@traced("local_compute", kind="CHAIN")
def local_compute(draft: str) -> dict[str, Any]:
    report = {
        "title": "Research Brief",
        "body": draft.strip(),
        "word_count": len(draft.split()),
        "char_count": len(draft),
    }
    add_event("postprocess_done", chars=report["char_count"])
    return report


def run_pipeline(query: str) -> dict[str, Any]:
    with span("pipeline", kind="AGENT", query=query):
        docs = load_corpus()
        chunks = rag_retrieve(query, docs)
        draft = llm_synthesize(query, chunks)
        report = local_compute(draft)
        return {
            "query": query,
            "retrieved_doc_ids": [c["doc_id"] for c in chunks],
            "report": report,
        }


def main() -> None:
    load_repo_env()
    status = enable_phoenix_otel(verbose=True)
    query = (
        "OpenInference 如何叠在 OpenTelemetry 上帮助定位 RAG 延迟瓶颈？"
        "请结合私有化可观测性说明。"
    )
    print("[day108] Phoenix bound:", {k: v for k, v in status.items() if k != "tracer_provider"})
    print("[day108] query:", query)
    result = run_pipeline(query)
    flush_traces()
    print("[day108] result:")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print()
    print("[day108] 打开 Phoenix UI 验收嵌套 Span：")
    print(f"  {status['PHOENIX_ENDPOINT'].replace('/v1/traces', '')}")
    print(f"  project={status['PHOENIX_PROJECT_NAME']}")
    print("  期望树: pipeline → load / rag(rerank) / llm / local_compute")


if __name__ == "__main__":
    main()
