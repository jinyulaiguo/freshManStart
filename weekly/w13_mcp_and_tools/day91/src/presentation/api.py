import asyncio
import json
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from langchain_core.messages import HumanMessage
import os

import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from src.infrastructure.observability import get_logger
from src.agent_domain.workflow import graph

logger = get_logger("api_gateway")

app = FastAPI(title="AI Research Assistant API")

# 获取静态文件路径
static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
async def get_index():
    return FileResponse(os.path.join(static_dir, "index.html"))

@app.websocket("/ws/chat")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    logger.info("WebSocket client connected")
    try:
        while True:
            data = await websocket.receive_text()
            payload = json.loads(data)
            query = payload.get("query", "")
            
            if not query:
                continue
                
            logger.info("Received query", query=query)
            
            # 开启 astream_events 流式执行 LangGraph
            # 在企业级环境中应传入 config (包含 thread_id 以便 Checkpointer 生效)
            config = {"configurable": {"thread_id": "session_1"}}
            
            async for event in graph.astream_events(
                {"messages": [HumanMessage(content=query)], "correlation_id": "req-123"},
                config=config,
                version="v2"
            ):
                event_type = event["event"]
                # 过滤出我们要发送给前端的数据
                if event_type == "on_chat_model_stream":
                    chunk = event["data"]["chunk"].content
                    if chunk:
                        await websocket.send_json({"type": "token", "content": chunk})
                elif event_type == "on_chat_model_start":
                    await websocket.send_json({"type": "info", "content": "LLM Start generating..."})
                elif event_type == "on_chat_model_end":
                    await websocket.send_json({"type": "info", "content": "LLM Finished generating."})
                elif event_type == "on_tool_start":
                    tool_name = event["name"]
                    await websocket.send_json({"type": "tool_start", "content": f"Invoking tool: {tool_name}..."})
                elif event_type == "on_tool_end":
                    tool_name = event["name"]
                    output = event["data"].get("output", "")
                    await websocket.send_json({"type": "tool_end", "content": f"Tool {tool_name} finished.", "output": str(output)})
                elif event_type == "on_custom_event" and event.get("name") == "mcp_routing":
                    data = event.get("data", {})
                    strategy = data.get("strategy")
                    servers = data.get("selected_servers", [])
                    await websocket.send_json({
                        "type": "info", 
                        "content": f"🎯 MCP Gateway Semantic Routing:\n- Strategy: {strategy}\n- Selected Servers: {servers}"
                    })
                elif event_type == "on_chain_start":
                    name = event["name"]
                    # Ignore internal LangGraph chains, only log our custom nodes or graph
                    if name in ["router", "agent", "workflow"]:
                        await websocket.send_json({"type": "info", "content": f"Node Started: {name}"})
                elif event_type == "on_chain_end":
                    name = event["name"]
                    if name in ["router", "agent", "workflow"]:
                        await websocket.send_json({"type": "info", "content": f"Node Ended: {name}"})
                        
            # 如果流中没有收到任何内容，我们至少发送一个响应结束标识
            await websocket.send_json({"type": "done"})
            
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.error("WebSocket error", error=str(e))
        await websocket.send_json({"type": "error", "content": str(e)})

