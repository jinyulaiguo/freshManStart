"""
Day 98 场景三: FastAPI + WebSocket 后端 (server.py)
端口: 8100
"""

import os
import sys
import json
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

current_dir = os.path.dirname(os.path.abspath(__file__))
for d in [current_dir,
          os.path.abspath(os.path.join(current_dir, "../../day92")),
          os.path.abspath(os.path.join(current_dir, "../../day93")),
          os.path.abspath(os.path.join(current_dir, "../../day94")),
          os.path.abspath(os.path.join(current_dir, "../../day95")),
          os.path.abspath(os.path.join(current_dir, "../../day96")),
          os.path.abspath(os.path.join(current_dir, "../../day97")),
          os.path.abspath(os.path.join(current_dir, "../../../w04_prompt_and_http"))]:
    if d not in sys.path:
        sys.path.insert(0, d)

from audit_agent import AuditAgent

app = FastAPI(title="Day 98 Long Task Agent - Context Runtime Dashboard")

static_dir = os.path.join(current_dir, "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

agent = AuditAgent()


@app.get("/")
async def get_index():
    return FileResponse(os.path.join(static_dir, "index.html"))


@app.get("/api/traces/all")
async def get_traces():
    return JSONResponse(agent.get_full_trace())


@app.post("/api/reset")
async def reset():
    global agent
    agent = AuditAgent()
    return JSONResponse({"status": "reset"})


@app.websocket("/ws/audit")
async def websocket_audit(websocket: WebSocket):
    await websocket.accept()

    try:
        while True:
            data = await websocket.receive_text()
            payload = json.loads(data)
            action = payload.get("action", "")

            if action == "start":
                async def event_callback(event_type, event_data):
                    try:
                        await websocket.send_json({"type": event_type, "data": event_data})
                    except Exception:
                        pass

                try:
                    await agent.start_audit(event_callback)
                except Exception as e:
                    await websocket.send_json({"type": "error", "data": {"message": str(e)}})

            elif action == "stop":
                agent.is_running = False
                await websocket.send_json({"type": "stopped", "data": {}})

    except WebSocketDisconnect:
        agent.is_running = False
