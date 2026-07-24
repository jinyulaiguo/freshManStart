"""
Day 84 综合实战: Web Dashboard 后端 API 服务器 (FastAPI)

【设计说明】
遵守 AGENTS.md 规范 1 与规范 10。
提供 Day 84 Advanced Industry Research Agent 的 Web 交互与 Dashboard 调试 API 服务。
1. 静态托管 dashboard.html。
2. POST /api/research: 驱动 LangGraph 控制流，以 SSE (Server-Sent Events) 流式推送节点流转与实时日志。
3. GET /api/status: 探活与 Qdrant 基础设施状态。
"""

import sys
import os
import json
import asyncio
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# 将项目根目录添加到 sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../")))

from weekly.w04_prompt_and_http.utils import load_env_file
from weekly.w12_planning_and_reflection.day84.graph.research_graph import build_research_graph
from weekly.w12_planning_and_reflection.day84.evaluation.research_logger import ResearchLogger

load_env_file()

app = FastAPI(title="Advanced Industry Research Agent Dashboard", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logger = ResearchLogger()


@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    """返回温润知性极简主义 Web 控制台 HTML 页面"""
    html_path = os.path.join(os.path.dirname(__file__), "dashboard.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Dashboard HTML Not Found</h1>"


@app.get("/api/health")
async def health_check():
    """探活接口"""
    return {"status": "ok", "service": "Research Agent Web Engine"}


@app.post("/api/research/stream")
async def run_research_stream(request: Request):
    """
    流式 SSE 接口，实时推送 LangGraph 各节点流转事件与中间状态
    """
    body = await request.json()
    user_query = body.get("query", "分析2026年医疗AI行业发展趋势")

    async def event_generator():
        graph = build_research_graph()
        initial_state = {
            "user_query": user_query,
            "planner_call_count": 0,
            "loop_counter": 0,
            "observations": {},
            "variables": {},
            "reflections": []
        }
        config = {"configurable": {"thread_id": f"web_session_{int(asyncio.get_event_loop().time())}"}}

        # 发送起始事件
        start_payload = json.dumps({"event": "START", "query": user_query}, ensure_ascii=False)
        yield f"data: {start_payload}\n\n"

        final_report = ""
        async for event in graph.astream(initial_state, config=config):
            for node_name, state_update in event.items():
                payload = {
                    "event": "NODE_TRANSITION",
                    "node": node_name,
                    "update_keys": list(state_update.keys()) if isinstance(state_update, dict) else [],
                    "state_preview": {}
                }

                if isinstance(state_update, dict):
                    if "plan" in state_update:
                        payload["state_preview"]["plan"] = state_update["plan"]
                    if "critic_result" in state_update and state_update["critic_result"]:
                        c_res = state_update["critic_result"]
                        payload["state_preview"]["critic"] = c_res.model_dump() if hasattr(c_res, "model_dump") else str(c_res)
                    if "reflections" in state_update:
                        payload["state_preview"]["reflections"] = state_update["reflections"]
                    if "verification_result" in state_update and state_update["verification_result"]:
                        v_res = state_update["verification_result"]
                        payload["state_preview"]["verifier"] = v_res.model_dump() if hasattr(v_res, "model_dump") else str(v_res)
                    if "final_report" in state_update:
                        final_report = state_update["final_report"]
                        payload["state_preview"]["final_report"] = final_report

                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                await asyncio.sleep(0.1)

        # 补全获取最终报告
        state_snap = graph.get_state(config)
        if not final_report:
            final_report = state_snap.values.get("final_report", state_snap.values.get("draft_report", "生成完成"))

        done_payload = json.dumps({
            "event": "COMPLETED",
            "final_report": final_report,
            "reflections": state_snap.values.get("reflections", []),
            "loop_counter": state_snap.values.get("loop_counter", 0)
        }, ensure_ascii=False)
        yield f"data: {done_payload}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


if __name__ == "__main__":
    print("🌐 正在启动 Research Agent Web Dashboard 服务器 (http://localhost:8000)...")
    uvicorn.run(app, host="0.0.0.0", port=8000)
