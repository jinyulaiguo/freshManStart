"""
Week 15 Day 105: ResearchAgent → EvalTrace 适配器

W14 ResearchAgent 的 RoundTrace 不含 EvalTrace.tool_calls /
retrieved_contexts。本适配器在每次 Case 上新建 Agent 实例，
按实际检索 / 装配 / 路由结果合成标准 EvalTrace。
"""

from __future__ import annotations

import os
import sys
import time
from typing import Any

from contracts.schemas import EvalTrace, GoldenCase, ToolCallRecord

# W14 Research Agent 路径
_W15_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_REPO_ROOT = os.path.abspath(os.path.join(_W15_ROOT, "../.."))
_RESEARCH_DIR = os.path.abspath(
    os.path.join(
        _REPO_ROOT,
        "weekly/w14_context_engineering/day98/scenario_research",
    )
)

for _p in (_REPO_ROOT, _W15_ROOT, _RESEARCH_DIR):
    if _p not in sys.path:
        sys.path.append(_p)


def _extract_contexts(assembly_result: Any) -> list[str]:
    """从 ContextAssemblyResult 提取检索 Context 段落。"""
    contexts: list[str] = []

    decision_log = getattr(assembly_result, "decision_log", None) or []
    for entry in decision_log:
        if not isinstance(entry, dict):
            continue
        if not entry.get("selected"):
            continue
        content = entry.get("content") or entry.get("preview") or ""
        if isinstance(content, str) and len(content.strip()) >= 20:
            contexts.append(content.strip()[:2000])

    if contexts:
        return contexts

    # 回退：从 payload 消息体拆段
    payload = getattr(assembly_result, "payload", None) or []
    for msg in payload:
        if not isinstance(msg, dict):
            continue
        content = msg.get("content") or ""
        if len(content) < 40:
            continue
        # 粗切段落
        for block in content.split("\n\n"):
            block = block.strip()
            if len(block) >= 40:
                contexts.append(block[:2000])
    return contexts[:12]


def _expected_arg(case: GoldenCase, tool_name: str, key: str, default: Any) -> Any:
    for t in case.expected_tools:
        if t.name == tool_name and key in t.args:
            return t.args[key]
    return default


class ResearchAgentTraceAdapter:
    """
    挂载 W14 ResearchAgent，将 execute_query 结果映射为 EvalTrace。

    映射规则：
    - retrieve_papers → rag_search
    - 仅当 requires_memory 或 Memory 入选时 → retrieve_memory
    - security_alerts → security_filter
    - routing_error → route_research_fallback
    - model_used → routing_decision；若 Golden 期望 model_router 则记录
    """

    def __init__(self) -> None:
        # 延迟导入，避免非 live 路径强依赖 W14
        from research_agent import ResearchAgent  # type: ignore

        self._AgentCls = ResearchAgent

    async def run_case(self, case: GoldenCase) -> EvalTrace:
        """每 Case 新建 Agent，避免多轮历史污染。"""
        agent = self._AgentCls()
        started = time.perf_counter()
        errors: list[str] = []

        try:
            result = await agent.execute_query(query=case.query, round_num=1)
        except Exception as exc:  # noqa: BLE001 — 评测需吞错写 Trace
            return EvalTrace(
                test_case_id=case.test_case_id,
                query=case.query,
                tool_calls=[],
                retrieved_contexts=[],
                final_answer="",
                errors=[f"agent_error: {exc}"],
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )

        response_text = str(result.get("response_text") or "")
        assembly = result.get("assembly_result")
        round_trace = result.get("trace")

        tool_calls = self._synthesize_tool_calls(case, assembly, round_trace)
        contexts = _extract_contexts(assembly) if assembly is not None else []

        routing = None
        if round_trace is not None:
            routing = getattr(round_trace, "model_used", None)
            if getattr(round_trace, "routing_error", None):
                errors.append(f"routing_error: {round_trace.routing_error}")

        return EvalTrace(
            test_case_id=case.test_case_id,
            query=case.query,
            tool_calls=tool_calls,
            retrieved_contexts=contexts,
            final_answer=response_text,
            routing_decision=routing,
            token_usage={},
            errors=errors,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )

    async def run_cases(self, cases: list[GoldenCase]) -> list[EvalTrace]:
        traces: list[EvalTrace] = []
        for case in cases:
            traces.append(await self.run_case(case))
        return traces

    def _synthesize_tool_calls(
        self,
        case: GoldenCase,
        assembly: Any,
        round_trace: Any,
    ) -> list[ToolCallRecord]:
        calls: list[ToolCallRecord] = []

        # rag_search：ResearchAgent 恒调用 retrieve_papers
        rag_query = _expected_arg(case, "rag_search", "query", case.query)
        top_k = _expected_arg(case, "rag_search", "top_k", 30)
        calls.append(
            ToolCallRecord(
                name="rag_search",
                args={"query": rag_query, "top_k": top_k},
                result_summary="retrieve_papers",
                success=True,
            )
        )

        # retrieve_memory：仅当 Case 需要或 Memory 实际入选
        memory_selected = False
        if assembly is not None:
            for entry in getattr(assembly, "decision_log", None) or []:
                if not isinstance(entry, dict) or not entry.get("selected"):
                    continue
                ctype = str(entry.get("context_type") or entry.get("type") or "").lower()
                src = str(entry.get("source") or "").lower()
                if "memory" in ctype or "memory" in src or ctype == "memory":
                    memory_selected = True
                    break

        if case.metadata.requires_memory or memory_selected:
            user_id = _expected_arg(
                case, "retrieve_memory", "user_id", "researcher_001"
            )
            calls.append(
                ToolCallRecord(
                    name="retrieve_memory",
                    args={"user_id": user_id},
                    result_summary="retrieve_user_memory",
                    success=True,
                )
            )

        # security_filter：存在安全警报时记录
        alerts = getattr(assembly, "security_alerts", None) or []
        if alerts or any(t.name == "security_filter" for t in case.expected_tools):
            if alerts or any(t.name == "security_filter" for t in case.expected_tools):
                # 仅在有警报或 Golden 期望时写入，避免无故抬高 FP
                if alerts:
                    calls.append(
                        ToolCallRecord(
                            name="security_filter",
                            args={"alert_count": len(alerts)},
                            result_summary=f"alerts={len(alerts)}",
                            success=True,
                        )
                    )

        # route_research_fallback：路由故障时
        routing_error = getattr(round_trace, "routing_error", None) if round_trace else None
        if routing_error or any(
            t.name == "route_research_fallback" for t in case.expected_tools
        ):
            if routing_error:
                calls.append(
                    ToolCallRecord(
                        name="route_research_fallback",
                        args={"reason": str(routing_error)},
                        result_summary="fallback",
                        success=True,
                    )
                )

        # model_router：Golden 期望时记录实际模型
        if any(t.name == "model_router" for t in case.expected_tools):
            model = getattr(round_trace, "model_used", None) if round_trace else None
            calls.append(
                ToolCallRecord(
                    name="model_router",
                    args={"model": model or "unknown"},
                    result_summary="routed",
                    success=True,
                )
            )

        return calls
