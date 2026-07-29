"""
Day 98 场景一: FastAPI + WebSocket 后端 (server.py)

===============================================================================
设计方案说明 (Architecture Design Specification)
===============================================================================

1. 设计意图 (Design Intent):
   提供 Research Agent 场景的 Web 服务端点。通过 FastAPI 代理前端页面，
   WebSocket 实时推送 Agent 执行流事件，REST API 提供审计数据查询接口。

2. 核心路由:
   - GET /           → 返回 Dashboard (index.html)
   - WebSocket /ws/research → 实时推送 Agent 执行流
   - GET /api/traces/decision-log → 返回决策日志
   - GET /api/traces/layout → 返回布局分析
   - GET /api/traces/security → 返回安全警报
   - GET /api/traces/all → 返回全链路审计数据
===============================================================================
"""

import os
import sys
import json
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

current_dir = os.path.dirname(os.path.abspath(__file__))
# 确保导入路径
day92_dir = os.path.abspath(os.path.join(current_dir, "../../day92"))
day93_dir = os.path.abspath(os.path.join(current_dir, "../../day93"))
day96_dir = os.path.abspath(os.path.join(current_dir, "../../day96"))
day97_dir = os.path.abspath(os.path.join(current_dir, "../../day97"))
w04_dir = os.path.abspath(os.path.join(current_dir, "../../../w04_prompt_and_http"))

for d in [current_dir, day92_dir, day93_dir, day96_dir, day97_dir, w04_dir]:
    if d not in sys.path:
        sys.path.insert(0, d)

from research_agent import ResearchAgent

# ═══════════════════════════════════════════════════════════════════════════
# FastAPI 应用初始化
# ═══════════════════════════════════════════════════════════════════════════

app = FastAPI(
    title="Day 98 Research Agent - Context Runtime Dashboard",
    description="论文检索与深度总结场景 | Enterprise Context Runtime Platform"
)

# 静态文件
static_dir = os.path.join(current_dir, "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# 全局 Agent 实例
agent = ResearchAgent()


@app.get("/")
async def get_index():
    """返回 Dashboard 主页"""
    return FileResponse(os.path.join(static_dir, "index.html"))


@app.get("/api/traces/all")
async def get_all_traces():
    """返回全链路审计数据"""
    return JSONResponse(agent.get_trace_data())


@app.get("/api/traces/decision-log")
async def get_decision_log():
    """返回最新一轮的 Assembly 决策日志"""
    if agent.all_decision_logs:
        return JSONResponse(agent.all_decision_logs[-1])
    return JSONResponse([])


@app.get("/api/traces/security")
async def get_security_alerts():
    """返回所有安全警报"""
    return JSONResponse(agent.all_security_alerts)


@app.get("/api/traces/routing")
async def get_routing_log():
    """返回路由决策日志"""
    return JSONResponse(agent.gateway.get_routing_log_json())


@app.post("/api/reset")
async def reset_agent():
    """重置 Agent 状态"""
    global agent
    agent = ResearchAgent()
    return JSONResponse({"status": "reset", "message": "Agent 已重置"})


@app.websocket("/ws/research")
async def websocket_research(websocket: WebSocket):
    """
    WebSocket 实时推送 Agent 执行流

    客户端发送: {"query": "用户查询内容"}
    服务端推送: {"type": "event_type", "data": {...}}
    """
    await websocket.accept()

    try:
        while True:
            data = await websocket.receive_text()
            payload = json.loads(data)
            query = payload.get("query", "")

            if not query:
                await websocket.send_json({
                    "type": "error",
                    "data": {"message": "查询内容不能为空"}
                })
                continue

            # 定义事件回调，将事件推送给前端
            async def event_callback(event_type: str, event_data: dict):
                try:
                    await websocket.send_json({
                        "type": event_type,
                        "data": event_data
                    })
                except Exception:
                    pass  # WebSocket 已断开则忽略

            # 执行 Agent 查询
            try:
                result = await agent.execute_query(
                    query=query,
                    event_callback=event_callback
                )
            except Exception as e:
                await websocket.send_json({
                    "type": "error",
                    "data": {"message": f"Agent 执行错误: {str(e)}"}
                })

    except WebSocketDisconnect:
        pass
    except Exception:
        pass
