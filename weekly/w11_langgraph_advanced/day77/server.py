"""FastAPI Web 服务后端 (Day 77 物理 SSE 流式 API - 智能 Checkpoint 锚定与空防错)

设计方案与架构说明：
----------------------------------------------------------------
本模块提供 HTTP/REST 与 SSE (Server-Sent Events) 物理流式 API，驱动 LangGraph 状态图物理推演。
1. 智能分叉节点锚定：
   - 当在尚未生成 SQL 的初始 Checkpoint 快照上启动 replay 或 edit_sql 时，系统自动智能识别并重定向到 `as_node="sql_generation"`，彻底避免在空 SQL 状态下强走 sql_execution 导致 DB 执行异常。
2. 全流程物理 SSE 动态推送。

数据流与生命周期：
------------------
[Dashboard HTML] <-> SSE EventStream <-> [server.py] <-> [sql_graph.astream()]
"""

import os
import sys
import json
import asyncio
from typing import Dict, Any, Optional, List, Tuple
from pydantic import BaseModel

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse
from langchain_core.messages import HumanMessage

# 动态将工作区根目录添加到 sys.path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from weekly.w04_prompt_and_http.utils import load_env_file
from weekly.w11_langgraph_advanced.day77.database.init_db import init_database
from weekly.w11_langgraph_advanced.day77.checkpoint.redis_checkpointer import ProductionRedisCheckpointer
from weekly.w11_langgraph_advanced.day77.graph.build_graph import build_sql_agent_graph

load_env_file()

app = FastAPI(title="Day 77 SQL Agent Web Dashboard Server (SSE Stream)", version="1.0.0")

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 全局初始化 Checkpointer 与 Compiled Graph
checkpointer = ProductionRedisCheckpointer()
sql_graph = build_sql_agent_graph(checkpointer)


# Pydantic 接口请求模型
class QueryRequest(BaseModel):
    thread_id: str
    query: str


class ApproveRequest(BaseModel):
    thread_id: str
    action: str  # "approve", "reject", "edit"
    edited_sql: Optional[str] = None


class ForkRequest(BaseModel):
    thread_id: str
    checkpoint_id: str
    fork_mode: str = "edit_sql"  # "replay", "edit_sql", "edit_query"
    new_sql: Optional[str] = None
    new_query: Optional[str] = None


@app.on_event("startup")
async def startup_event():
    """应用启动钩子：自动校验/初始化 PostgreSQL 数据库。"""
    try:
        init_database()
        print("✅ Web Dashboard 流式后端启动成功，数据库已就绪！")
    except Exception as e:
        print(f"⚠️ 数据库初始化警告: {e}")


@app.get("/", response_class=HTMLResponse)
async def get_dashboard_html():
    """渲染并返回符合 Warm Intellectual Minimalism 风格的 Web 调试 Dashboard 静态页面。"""
    html_path = os.path.join(os.path.dirname(__file__), "dashboard.html")
    if not os.path.exists(html_path):
        raise HTTPException(status_code=404, detail="未找到 dashboard.html 静态页面文件。")

    with open(html_path, "r", encoding="utf-8") as f:
        return f.read()


NODE_DISPLAY_NAMES = {
    "sql_generation": "SQL 生成节点",
    "risk_assess": "双重风控评估节点",
    "approval_gateway": "HITL 审批门禁网关",
    "sql_execution": "PostgreSQL 物理执行节点",
    "post_analysis": "并行分析子图",
    "validate": "子图: 数据质量校验",
    "summarize": "子图: 真实 LLM 摘要",
    "audit": "子图: 结构化审计",
    "merge": "子图: Barrier 屏障汇聚",
    "result": "结果汇总节点"
}


def extract_node_update(event_item: Any) -> Tuple[str, dict]:
    """强类型安全助手：精准解析 LangGraph astream 各种粒度的 event 对象。"""
    node_name = "unknown_node"
    update_dict = {}

    if isinstance(event_item, tuple) and len(event_item) >= 2:
        ns, payload = event_item[0], event_item[1]
        if isinstance(payload, dict):
            for k, v in payload.items():
                node_name = str(k)
                if isinstance(v, dict):
                    update_dict = v
                else:
                    update_dict = payload
                break
        elif isinstance(ns, (tuple, list)) and len(ns) > 0:
            node_name = str(ns[-1])
    elif isinstance(event_item, dict):
        for k, v in event_item.items():
            node_name = str(k)
            if isinstance(v, dict):
                update_dict = v
            break

    if not node_name or node_name in ["()", "tuple"]:
        node_name = "graph_step"

    return node_name, update_dict


async def query_event_generator(thread_id: str, query: str):
    """SSE 物理流式事件生成器。"""
    try:
        config = {"configurable": {"thread_id": thread_id}}
        initial_state = {
            "messages": [HumanMessage(content=query)],
            "generated_sql": None,
            "sql_params": None,
            "risk_level": "safe",
            "risk_analysis": None,
            "approval_status": "pending",
            "execution_result": None,
            "error_log": [],
            "audit_trail": [f"Web user initiated query: '{query}'"]
        }

        yield {
            "event": "start",
            "data": json.dumps({"message": f"开始推演查询: '{query}'", "step": 1})
        }

        async for event in sql_graph.astream(initial_state, config, stream_mode="updates", subgraphs=True):
            node_name, node_update = extract_node_update(event)
            audit_logs = node_update.get("audit_trail", []) if isinstance(node_update, dict) else []
            friendly_name = NODE_DISPLAY_NAMES.get(node_name, node_name)
            last_log = audit_logs[-1] if audit_logs else f"【{friendly_name}】推演阶段完成"

            step_num = 1
            if "sql_gen" in node_name: step_num = 1
            elif "risk" in node_name: step_num = 2
            elif "approval" in node_name or "sql_exec" in node_name: step_num = 3
            elif "analysis" in node_name or "subgraph" in node_name or node_name in ["validate", "summarize", "audit", "merge"]: step_num = 4
            elif "result" in node_name: step_num = 5

            yield {
                "event": "node_update",
                "data": json.dumps({
                    "node": friendly_name,
                    "step": step_num,
                    "log": last_log,
                    "update": {
                        "generated_sql": node_update.get("generated_sql") if isinstance(node_update, dict) else None,
                        "risk_level": node_update.get("risk_level") if isinstance(node_update, dict) else None,
                        "risk_analysis": node_update.get("risk_analysis") if isinstance(node_update, dict) else None,
                        "execution_result": node_update.get("execution_result") if isinstance(node_update, dict) else None
                    }
                })
            }

        snapshot = sql_graph.get_state(config)
        is_interrupted = snapshot.next == ("approval_gateway",)

        yield {
            "event": "finish",
            "data": json.dumps({
                "is_interrupted": is_interrupted,
                "next": list(snapshot.next),
                "state": {
                    "generated_sql": snapshot.values.get("generated_sql"),
                    "sql_params": snapshot.values.get("sql_params"),
                    "risk_level": snapshot.values.get("risk_level"),
                    "risk_analysis": snapshot.values.get("risk_analysis"),
                    "approval_status": snapshot.values.get("approval_status"),
                    "execution_result": snapshot.values.get("execution_result"),
                    "error_log": snapshot.values.get("error_log", []),
                    "audit_trail": snapshot.values.get("audit_trail", [])
                }
            })
        }

        yield {
            "event": "end",
            "data": json.dumps({"status": "complete"})
        }
    except asyncio.CancelledError:
        pass


@app.post("/api/stream_query")
async def stream_query(req: QueryRequest):
    return EventSourceResponse(query_event_generator(req.thread_id, req.query))


async def fork_event_generator(req: ForkRequest):
    """SSE 物理流式 Time Travel 分叉事件生成器 (支持智能节点选择与防空机制)。"""
    try:
        config = {"configurable": {"thread_id": req.thread_id}}
        history_snapshots = list(sql_graph.get_state_history(config))

        target_snap = None
        for snap in history_snapshots:
            if snap.config["configurable"]["checkpoint_id"] == req.checkpoint_id:
                target_snap = snap
                break

        if not target_snap:
            yield {
                "event": "error",
                "data": json.dumps({"message": f"未找到 checkpoint_id 为 {req.checkpoint_id} 的历史快照。"})
            }
            return

        fork_config = target_snap.config
        existing_sql = target_snap.values.get("generated_sql")

        if req.fork_mode == "replay":
            # 若原快照中已有生成好的 SQL -> 从 risk_assess 原重用 SQL 执行；若尚无 SQL -> 智能退回 sql_generation 重构
            target_as_node = "risk_assess" if existing_sql else "sql_generation"
            new_config = sql_graph.update_state(
                fork_config,
                {
                    "approval_status": "approved",
                    "execution_result": None,
                    "error_log": [],
                    "audit_trail": [f"Web Time Travel Fault Replay triggered (as_node='{target_as_node}')."]
                },
                as_node=target_as_node
            )
        elif req.fork_mode == "edit_query" and req.new_query:
            new_config = sql_graph.update_state(
                fork_config,
                {
                    "messages": [HumanMessage(content=req.new_query)],
                    "generated_sql": None,
                    "execution_result": None,
                    "approval_status": "pending",
                    "error_log": [],
                    "audit_trail": [f"Web Time Travel created new query fork: '{req.new_query}'"]
                },
                as_node="sql_generation"
            )
        else:
            # edit_sql 模式
            sql_to_use = req.new_sql or existing_sql
            target_as_node = "risk_assess" if sql_to_use else "sql_generation"
            
            patch_state = {
                "approval_status": "edited",
                "execution_result": None,
                "error_log": [],
                "audit_trail": [f"Web Time Travel Fork created (mode='edit_sql')."]
            }
            if sql_to_use:
                patch_state["generated_sql"] = sql_to_use

            new_config = sql_graph.update_state(
                fork_config,
                patch_state,
                as_node=target_as_node
            )

        yield {
            "event": "start",
            "data": json.dumps({"message": f"发起 3 维 Time Travel 分叉重发 ({req.fork_mode})", "step": 1})
        }

        async for event in sql_graph.astream(None, new_config, stream_mode="updates", subgraphs=True):
            node_name, node_update = extract_node_update(event)
            audit_logs = node_update.get("audit_trail", []) if isinstance(node_update, dict) else []
            friendly_name = NODE_DISPLAY_NAMES.get(node_name, node_name)
            last_log = audit_logs[-1] if audit_logs else f"【{friendly_name}】重发阶段完成"

            step_num = 1
            if "sql_gen" in node_name: step_num = 1
            elif "risk" in node_name: step_num = 2
            elif "approval" in node_name or "sql_exec" in node_name: step_num = 3
            elif "analysis" in node_name or "subgraph" in node_name or node_name in ["validate", "summarize", "audit", "merge"]: step_num = 4
            elif "result" in node_name: step_num = 5

            yield {
                "event": "node_update",
                "data": json.dumps({
                    "node": friendly_name,
                    "step": step_num,
                    "log": last_log,
                    "update": {
                        "generated_sql": node_update.get("generated_sql") if isinstance(node_update, dict) else None,
                        "risk_level": node_update.get("risk_level") if isinstance(node_update, dict) else None,
                        "risk_analysis": node_update.get("risk_analysis") if isinstance(node_update, dict) else None,
                        "execution_result": node_update.get("execution_result") if isinstance(node_update, dict) else None
                    }
                })
            }

        latest_config = {"configurable": {"thread_id": req.thread_id}}
        final_snap = sql_graph.get_state(latest_config)
        is_interrupted = final_snap.next == ("approval_gateway",)

        yield {
            "event": "finish",
            "data": json.dumps({
                "is_interrupted": is_interrupted,
                "next": list(final_snap.next),
                "state": {
                    "generated_sql": final_snap.values.get("generated_sql"),
                    "sql_params": final_snap.values.get("sql_params"),
                    "risk_level": final_snap.values.get("risk_level"),
                    "risk_analysis": final_snap.values.get("risk_analysis"),
                    "approval_status": final_snap.values.get("approval_status"),
                    "execution_result": final_snap.values.get("execution_result"),
                    "error_log": final_snap.values.get("error_log", []),
                    "audit_trail": final_snap.values.get("audit_trail", [])
                }
            })
        }

        yield {
            "event": "end",
            "data": json.dumps({"status": "complete"})
        }
    except asyncio.CancelledError:
        pass


@app.post("/api/stream_fork")
async def stream_fork(req: ForkRequest):
    return EventSourceResponse(fork_event_generator(req))


async def approve_event_generator(thread_id: str, action: str, edited_sql: Optional[str]):
    try:
        config = {"configurable": {"thread_id": thread_id}}
        snapshot = sql_graph.get_state(config)

        if snapshot.next != ("approval_gateway",):
            yield {
                "event": "error",
                "data": json.dumps({"message": "当前不处于挂起待审批状态。"})
            }
            return

        if action == "edit" and edited_sql:
            sql_graph.update_state(
                config,
                {
                    "generated_sql": edited_sql,
                    "approval_status": "edited",
                    "audit_trail": [f"Web auditor edited SQL to: '{edited_sql}' and approved."]
                },
                as_node="risk_assess"
            )
        elif action == "reject":
            sql_graph.update_state(
                config,
                {
                    "approval_status": "rejected",
                    "audit_trail": ["Web auditor REJECTED execution."]
                },
                as_node="risk_assess"
            )
        else:
            sql_graph.update_state(
                config,
                {
                    "approval_status": "approved",
                    "audit_trail": ["Web auditor APPROVED execution."]
                },
                as_node="risk_assess"
            )

        async for event in sql_graph.astream(None, config, stream_mode="updates", subgraphs=True):
            node_name, node_update = extract_node_update(event)
            audit_logs = node_update.get("audit_trail", []) if isinstance(node_update, dict) else []
            friendly_name = NODE_DISPLAY_NAMES.get(node_name, node_name)
            last_log = audit_logs[-1] if audit_logs else f"【{friendly_name}】解冻阶段完成"

            step_num = 3
            if "sql_exec" in node_name: step_num = 3
            elif "analysis" in node_name or "subgraph" in node_name or node_name in ["validate", "summarize", "audit", "merge"]: step_num = 4
            elif "result" in node_name: step_num = 5

            yield {
                "event": "node_update",
                "data": json.dumps({
                    "node": friendly_name,
                    "step": step_num,
                    "log": last_log,
                    "update": {
                        "generated_sql": node_update.get("generated_sql") if isinstance(node_update, dict) else None,
                        "execution_result": node_update.get("execution_result") if isinstance(node_update, dict) else None
                    }
                })
            }

        final_snap = sql_graph.get_state(config)
        yield {
            "event": "finish",
            "data": json.dumps({
                "is_interrupted": False,
                "next": list(final_snap.next),
                "state": {
                    "generated_sql": final_snap.values.get("generated_sql"),
                    "sql_params": final_snap.values.get("sql_params"),
                    "risk_level": final_snap.values.get("risk_level"),
                    "risk_analysis": final_snap.values.get("risk_analysis"),
                    "approval_status": final_snap.values.get("approval_status"),
                    "execution_result": final_snap.values.get("execution_result"),
                    "error_log": final_snap.values.get("error_log", []),
                    "audit_trail": final_snap.values.get("audit_trail", [])
                }
            })
        }
    except asyncio.CancelledError:
        pass


@app.post("/api/stream_approve")
async def stream_approve(req: ApproveRequest):
    return EventSourceResponse(approve_event_generator(req.thread_id, req.action, req.edited_sql))


@app.get("/api/history/{thread_id}")
async def get_history(thread_id: str):
    config = {"configurable": {"thread_id": thread_id}}
    history_snapshots = list(sql_graph.get_state_history(config))

    result = []
    for snap in history_snapshots:
        cp_id = snap.config["configurable"]["checkpoint_id"]
        parent_id = snap.parent_config["configurable"]["checkpoint_id"] if snap.parent_config else None

        result.append({
            "checkpoint_id": cp_id,
            "parent_checkpoint_id": parent_id,
            "next": list(snap.next),
            "generated_sql": snap.values.get("generated_sql"),
            "query": snap.values.get("messages")[-1].content if snap.values.get("messages") else "N/A",
            "risk_level": snap.values.get("risk_level"),
            "approval_status": snap.values.get("approval_status"),
            "audit_count": len(snap.values.get("audit_trail", []))
        })

    return {"thread_id": thread_id, "history": result}


@app.post("/api/reset_db")
async def reset_db():
    try:
        init_database()
        return {"status": "SUCCESS", "message": "PostgreSQL 沙箱数据库已重新重置！"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=True)
