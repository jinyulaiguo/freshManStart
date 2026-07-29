"""
Day 98 场景二: FastAPI + WebSocket 后端 (server.py)
端口: 8099
"""

import os
import sys
import json
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

current_dir = os.path.dirname(os.path.abspath(__file__))
day92_dir = os.path.abspath(os.path.join(current_dir, "../../day92"))
day93_dir = os.path.abspath(os.path.join(current_dir, "../../day93"))
day94_dir = os.path.abspath(os.path.join(current_dir, "../../day94"))
day97_dir = os.path.abspath(os.path.join(current_dir, "../../day97"))
w04_dir = os.path.abspath(os.path.join(current_dir, "../../../w04_prompt_and_http"))

for d in [current_dir, day92_dir, day93_dir, day94_dir, day97_dir, w04_dir]:
    if d not in sys.path:
        sys.path.insert(0, d)

from coding_agent import CodingAgent

app = FastAPI(
    title="Day 98 Coding Agent - Context Runtime Dashboard",
    description="多文件代码修改与安全重构场景 | 端口 8099"
)

static_dir = os.path.join(current_dir, "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

agent = CodingAgent()


@app.get("/")
async def get_index():
    return FileResponse(os.path.join(static_dir, "index.html"))


@app.get("/api/traces/cost")
async def get_cost_trace():
    return JSONResponse(agent.cost_ctrl.get_cost_trace())


@app.get("/api/traces/routing")
async def get_routing():
    return JSONResponse(agent.router.get_routing_log())


@app.get("/api/traces/approvals")
async def get_approvals():
    return JSONResponse(agent.approval_mgr.get_approval_log())


@app.post("/api/approval/{approval_id}")
async def submit_approval(approval_id: str, approved: bool = True):
    result = agent.approval_mgr.resolve_approval(approval_id, approved, "dashboard_user")
    return JSONResponse({"resolved": result, "approved": approved})


@app.post("/api/reset")
async def reset():
    global agent
    agent = CodingAgent()
    return JSONResponse({"status": "reset"})


@app.websocket("/ws/coding")
async def websocket_coding(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            payload = json.loads(data)
            task = payload.get("task", "")
            if not task:
                continue

            async def event_callback(event_type, event_data):
                try:
                    await websocket.send_json({"type": event_type, "data": event_data})
                except Exception:
                    pass

            try:
                result = await agent.execute_task(task, event_callback)
            except Exception as e:
                await websocket.send_json({"type": "error", "data": {"message": str(e)}})

    except WebSocketDisconnect:
        pass
