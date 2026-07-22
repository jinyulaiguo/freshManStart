"""
Day 70 CVE Triage Pipeline — FastAPI 后端服务

===================================================================================
模块设计方案 (Architectural Design)
===================================================================================
设计意图：
   本模块提供 FastAPI 异步 HTTP 服务入口，将 CVE Triage Pipeline 以 RESTful API
   形式对外暴露，供 Web Dashboard 及 CI/CD 系统调用。

端点列表：
   GET  /                                     返回 dashboard.html 静态看板
   POST /api/triage                           提交漏洞分诊请求（SSE 流式进度 + 最终结果）
   GET  /api/sessions/{thread_id}/snapshot    查询会话最新状态快照
   GET  /api/sessions/{thread_id}/history     查询会话全量 Checkpoint 历史
   GET  /api/tenants/{tenant_id}/sessions     列出租户活跃会话
   POST /api/triage/dead-loop-test            触发死循环演示熔断（教学专用）

生命周期：
   启动时：构建 MemorySaver + CompiledGraph + TenantSessionManager 单例
   关闭时：静默释放（MemorySaver 为内存存储，无持久化连接需释放）
===================================================================================
"""

import json
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from langgraph.checkpoint.memory import MemorySaver

from cve_pipeline.state import make_initial_state
from cve_pipeline.graph_builder import build_cve_triage_graph
from engines.circuit_breaker import MultiDimensionalCircuitBreaker
from engines.session_manager import TenantSessionManager, TelemetryRecorder

# =============================================================================
# 全局单例（lifespan 中初始化）
# =============================================================================

_memory_saver: MemorySaver | None = None
_compiled_graph: Any = None
_session_manager: TenantSessionManager | None = None
_circuit_breaker: MultiDimensionalCircuitBreaker | None = None
# 维护 tenant → thread_ids 映射（内存级，仅用于演示）
_tenant_threads: dict[str, list[str]] = {}

DASHBOARD_HTML_PATH = Path(__file__).parent / "dashboard.html"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI 异步生命周期管理器。"""
    global _memory_saver, _compiled_graph, _session_manager, _circuit_breaker

    _memory_saver = MemorySaver()
    _compiled_graph = build_cve_triage_graph(checkpointer=_memory_saver)
    _session_manager = TenantSessionManager(_compiled_graph)
    _circuit_breaker = MultiDimensionalCircuitBreaker(
        _compiled_graph,
        recursion_limit=15,
        max_token_budget=8000,
        max_latency_ms=120_000,
    )
    print("[CVE Pipeline] 服务启动完毕 ✅")
    yield
    print("[CVE Pipeline] 服务关闭。")


app = FastAPI(
    title="CVE Triage Pipeline API",
    description="企业级多租户 CVE 漏洞分诊与自动修复 Pipeline",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================================================================
# 请求/响应模型
# =============================================================================

class TriageRequest(BaseModel):
    raw_input: str = Field(..., min_length=5, description="漏洞描述文本（至少5字符）")
    tenant_id: str = Field(default="default_tenant", description="多租户标识符")
    thread_id: str | None = Field(default=None, description="会话 thread_id（不填则自动生成）")


class TriageResponse(BaseModel):
    thread_id: str
    severity: str
    cve_id: str
    vulnerability_type: str
    validation_verdict: str
    compliance_report: str
    risk_score: float
    is_circuit_broken: bool
    telemetry: dict


class DeadLoopTestRequest(BaseModel):
    tenant_id: str = Field(default="demo_tenant")
    recursion_limit: int = Field(default=6, ge=3, le=20)


# =============================================================================
# API 端点
# =============================================================================

@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    """返回 Web 调试看板 HTML 页面。"""
    if DASHBOARD_HTML_PATH.exists():
        return HTMLResponse(content=DASHBOARD_HTML_PATH.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>CVE Triage Pipeline</h1><p>Dashboard 文件未找到。</p>")


@app.post("/api/triage", response_model=TriageResponse)
async def run_triage(req: TriageRequest):
    """提交漏洞分诊请求，执行完整 Pipeline 并返回结果。

    Pipeline 执行步骤：
    1. 生成 thread_id（若未提供）
    2. 构建初始 State
    3. 通过 MultiDimensionalCircuitBreaker 执行图（含熔断保护）
    4. 提取 Telemetry 摘要
    5. 返回结构化结果
    """
    thread_id = req.thread_id or TenantSessionManager.generate_thread_id(req.tenant_id)
    request_trace_id = str(uuid.uuid4())[:8]

    initial = make_initial_state(
        raw_input=req.raw_input,
        tenant_id=req.tenant_id,
        request_trace_id=request_trace_id,
    )

    thread_config = {"configurable": {"thread_id": thread_id}}

    # 通过熔断控制器执行（含 recursion_limit 透传）
    final_state = _circuit_breaker.execute(initial, thread_config)

    # 记录 tenant → thread 映射
    if req.tenant_id not in _tenant_threads:
        _tenant_threads[req.tenant_id] = []
    if thread_id not in _tenant_threads[req.tenant_id]:
        _tenant_threads[req.tenant_id].append(thread_id)

    telemetry = TelemetryRecorder.extract_summary(final_state)

    return TriageResponse(
        thread_id=thread_id,
        severity=final_state.get("severity", "UNKNOWN"),
        cve_id=final_state.get("cve_id", "UNKNOWN"),
        vulnerability_type=final_state.get("vulnerability_type", "Unknown"),
        validation_verdict=final_state.get("validation_verdict", "PENDING"),
        compliance_report=final_state.get("compliance_report", ""),
        risk_score=final_state.get("risk_score", 0.0),
        is_circuit_broken=final_state.get("is_circuit_broken", False),
        telemetry=telemetry,
    )


@app.get("/api/sessions/{thread_id}/snapshot")
async def get_session_snapshot(thread_id: str):
    """查询指定 thread_id 的最新状态快照。"""
    snapshot = _session_manager.get_latest_snapshot(thread_id)
    if not snapshot or not snapshot.values:
        raise HTTPException(status_code=404, detail=f"未找到 thread_id={thread_id} 的会话快照")
    return {
        "thread_id": thread_id,
        "next_nodes": list(snapshot.next) if snapshot.next else [],
        "severity": snapshot.values.get("severity"),
        "validation_verdict": snapshot.values.get("validation_verdict"),
        "message_count": len(snapshot.values.get("messages", [])),
        "total_tokens": snapshot.values.get("total_llm_tokens", 0),
        "is_circuit_broken": snapshot.values.get("is_circuit_broken", False),
    }


@app.post("/api/triage/stream")
async def run_triage_stream(req: TriageRequest):
    """提交漏洞分诊请求，流式下发 SSE 节点进度事件与最终结果。"""
    thread_id = req.thread_id or TenantSessionManager.generate_thread_id(req.tenant_id)
    request_trace_id = str(uuid.uuid4())[:8]

    initial = make_initial_state(
        raw_input=req.raw_input,
        tenant_id=req.tenant_id,
        request_trace_id=request_trace_id,
    )

    thread_config = {"configurable": {"thread_id": thread_id}}

    if req.tenant_id not in _tenant_threads:
        _tenant_threads[req.tenant_id] = []
    if thread_id not in _tenant_threads[req.tenant_id]:
        _tenant_threads[req.tenant_id].append(thread_id)

    async def event_generator():
        # 首先下发 start 事件
        yield f"data: {json.dumps({'type': 'start', 'thread_id': thread_id})}\n\n"

        async for item in _circuit_breaker.aexecute_stream(initial, thread_config):
            yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/sessions/{thread_id}/history")
async def get_session_history(thread_id: str):
    """查询指定 thread_id 的全量 Checkpoint 历史版本（正向时间线：v0=初始态, vN=最新终态）。"""
    raw_history = _session_manager.get_checkpoint_history(thread_id)
    # LangGraph get_state_history 默认返回逆序（最新在前），反转为正向时间线演进顺序
    chronological_history = list(reversed(raw_history))
    return {
        "thread_id": thread_id,
        "checkpoint_count": len(chronological_history),
        "checkpoints": [
            {
                "version_index": i,
                "checkpoint_id": snap.config.get("configurable", {}).get("checkpoint_id", "N/A"),
                "message_count": len(snap.values.get("messages", [])) if snap.values else 0,
                "severity": snap.values.get("severity", "N/A") if snap.values else "N/A",
                "next_nodes": list(snap.next) if snap.next else [],
            }
            for i, snap in enumerate(chronological_history)
        ],
    }


@app.get("/api/sessions/{thread_id}/checkpoints/{checkpoint_id}")
async def get_specific_checkpoint(thread_id: str, checkpoint_id: str):
    """查询指定 Checkpoint ID 的完整 State 值（用于 Checkpoint 历史选择器）。"""
    values = _session_manager.rollback_to_checkpoint(thread_id, checkpoint_id)
    if values is None:
        raise HTTPException(status_code=404, detail=f"未找到 checkpoint_id={checkpoint_id}")

    # 清洗无法直接 JSON 序列化的 BaseMessage 对象
    clean_values = dict(values)
    if "messages" in clean_values:
        clean_values["messages"] = [
            {"type": getattr(m, "type", "message"), "content": getattr(m, "content", str(m))}
            for m in clean_values["messages"]
        ]

    return {
        "thread_id": thread_id,
        "checkpoint_id": checkpoint_id,
        "values": clean_values,
    }


@app.get("/api/tenants/{tenant_id}/sessions")
async def get_tenant_sessions(tenant_id: str):
    """列出指定租户的所有已知活跃会话摘要。"""
    known_threads = _tenant_threads.get(tenant_id, [])
    summaries = _session_manager.list_all_sessions_for_tenant(tenant_id, known_threads)
    return {
        "tenant_id": tenant_id,
        "session_count": len(summaries),
        "sessions": summaries,
    }


@app.post("/api/triage/dead-loop-test")
async def trigger_dead_loop_demo(req: DeadLoopTestRequest):
    """触发死循环演示熔断（教学专用端点）。

    故意构造 patch_generator 节点永远返回 FAIL 的场景，
    观察 recursion_limit 熔断与 MultiDimensionalCircuitBreaker 降级机制。
    """
    from langgraph.graph import StateGraph, START, END
    from cve_pipeline.state import CVETriageState

    # 构建一个 node_a → node_b → node_a 死循环图
    loop_count = [0]

    def loop_node_a(state):
        loop_count[0] += 1
        return {
            "patch_retry_count": loop_count[0],
            "node_latency_log": [{
                "node": "dead_loop_a",
                "latency_ms": 1,
                "tokens_used": 0,
                "patch_fingerprint": "dead0000",
            }],
        }

    def loop_node_b(state):
        return {"node_latency_log": [{"node": "dead_loop_b", "latency_ms": 1, "tokens_used": 0}]}

    wf = StateGraph(CVETriageState)
    wf.add_node("node_a", loop_node_a)
    wf.add_node("node_b", loop_node_b)
    wf.add_edge(START, "node_a")
    wf.add_edge("node_a", "node_b")
    wf.add_edge("node_b", "node_a")
    loop_graph = wf.compile()

    breaker = MultiDimensionalCircuitBreaker(loop_graph, recursion_limit=req.recursion_limit)
    initial = make_initial_state(
        raw_input="死循环熔断演示请求",
        tenant_id=req.tenant_id,
        request_trace_id="demo-loop-" + str(uuid.uuid4())[:6],
    )

    result = breaker.execute(initial)

    return {
        "is_circuit_broken": result.get("is_circuit_broken"),
        "degradation_payload": result.get("degradation_payload"),
        "total_loop_iterations": loop_count[0],
        "message": "死循环熔断演示完成！请查看 degradation_payload 中的四维诊断数据。",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8070, reload=True)
