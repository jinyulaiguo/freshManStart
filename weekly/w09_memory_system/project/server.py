"""
FastAPI Server Module.

设计方案说明：
1. **设计意图**：
   本模块通过 FastAPI 构建 Web 后端服务，提供了多层级记忆系统的 API 端点。
   配合前端 Dashboard（dashboard.html），系统可以在可视化的交互界面中展现自适应路由的抉择、短期工作记忆的状态以及长期原子事实偏好的动态消解和时间衰减。
2. **暴露的 API 接口**：
   - `GET /` : 返回 dashboard.html 交互页面。
   - `POST /api/chat` : 触发一次对话，执行路由与推理，并挂载非阻塞后台任务。
   - `GET /api/sessions` : 拉取系统当前所有已注册的 Session 及对应摘要。
   - `GET /api/memories` : 拉取特定用户的所有长期事实实体偏好（包含时间戳和艾宾浩斯留存权重）。
   - `POST /api/decay` : 手动触发时间衰减计算，并在后台淘汰冷记忆。
   - `GET /api/logs` : 实时查询后台审计日志流。
   - `GET /api/debug_info` : 获取特定 Session 的内存工作记忆详情。
"""

import sys
import os
import time
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# 物理定位主工作区，并添加 sys.path，保证导入 app 子包绝对正确
current_dir = os.path.dirname(os.path.abspath(__file__))
# current_dir 是 weekly/w09_memory_system/project
project_root = os.path.abspath(os.path.join(current_dir, "../../.."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from app.main_engine import MemoryAgentEngine
from app.memory_consolidator import FactItem as ConsolidatorFactItem

app = FastAPI(title="多层级记忆增强 Agent 系统 API")

# 支持跨域（CORS），允许自由访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 初始化核心装配引擎（使用默认的 agent_memory.db 持久化数据库，Token 限制设为 1200 字符）
engine = MemoryAgentEngine(db_path="agent_memory.db", token_limit=1200)

# 定义 API 数据契约
class ChatRequest(BaseModel):
    session_id: str
    user_id: str
    query: str

class DecayRequest(BaseModel):
    user_id: str
    decay_rate: float = 0.005

@app.on_event("startup")
async def startup_event():
    """系统启动时的前置钩子，初始化数据库 Schema。"""
    await engine.store.init_db()
    print("🚀 FastAPI 启动成功，已挂载持久化 SQLite 连接。")

@app.get("/")
async def get_dashboard():
    """返回温润知性风格 Dashboard 前端单页面。"""
    dashboard_path = os.path.join(current_dir, "dashboard.html")
    if not os.path.exists(dashboard_path):
        raise HTTPException(status_code=404, detail="未找到 dashboard.html 物理文件")
    return FileResponse(dashboard_path)

@app.post("/api/chat")
async def chat_interaction(req: ChatRequest):
    """主会话交互 API。接收提问并触发多层级记忆 Pipeline。

    Args:
        req: 对话请求契约体。

    Returns:
        对话输出包（回复、路由决策、检索开销及召回数据）。
    """
    if not req.session_id.strip() or not req.user_id.strip() or not req.query.strip():
        raise HTTPException(status_code=400, detail="session_id, user_id 或 query 不能为空")
    
    try:
        result = await engine.handle_message(
            session_id=req.session_id.strip(),
            user_id=req.user_id.strip(),
            query=req.query.strip()
        )
        return result
    except Exception as e:
        engine.log_audit("error", f"交互处理异常: {e}")
        raise HTTPException(status_code=500, detail=f"交互处理错误: {str(e)}")

@app.get("/api/sessions")
async def get_sessions_list():
    """获取全部已记录的会话 Session 元数据列表。"""
    try:
        sessions = await engine.store.list_sessions()
        return {"sessions": sessions}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/memories")
async def get_user_memories(user_id: str = Query(..., description="租户唯一标识符")):
    """获取指定租户的所有长期事实（包括时间戳与艾宾浩斯衰减权重）。"""
    if not user_id.strip():
        raise HTTPException(status_code=400, detail="user_id 不能为空")
    try:
        memories = await engine.store.load_all_memory_items(user_id.strip())
        return {"user_id": user_id, "memories": memories}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/decay")
async def trigger_time_decay(req: DecayRequest):
    """手动强制触发该用户的记忆衰减与遗忘淘汰，重算权重并清理冷记忆。"""
    if not req.user_id.strip():
        raise HTTPException(status_code=400, detail="user_id 不能为空")
    try:
        engine.log_audit("info", f"收到手动衰减请求。租户: '{req.user_id}'，衰减率: {req.decay_rate}")
        
        # 1. 载入全部长期事实
        raw_memories = await engine.store.load_all_memory_items(req.user_id.strip())
        existing_items = [
            ConsolidatorFactItem(
                fact_key=m["fact_key"],
                fact_value=m["fact_value"],
                timestamp=m["timestamp"],
                weight=m["weight"]
            ) for m in raw_memories
        ]
        
        # 2. 调用 consolidator 重算权重，此处设淘汰阈值为 0.2
        active_items, decayed_keys = engine.consolidator.apply_time_decay(
            existing_items,
            current_time=time.time(),
            decay_rate=req.decay_rate,
            threshold=0.2
        )
        
        # 3. 批量更新剩余的权重
        weights_map = {item.fact_key: item.weight for item in active_items}
        await engine.store.update_memories_weights(req.user_id.strip(), weights_map)
        
        # 4. 从数据库物理淘汰衰减值低于 0.2 的事实
        if decayed_keys:
            await engine.store.clear_decayed_memories(req.user_id.strip(), threshold=0.2)
            for k in decayed_keys:
                engine.log_audit("warning", f"[手动衰减] 事实 [{k}] 权重过低，已被淘汰。")
                
        engine.log_audit("success", f"[手动衰减] 衰减计算完成。淘汰事实数: {len(decayed_keys)}")
        return {
            "status": "success",
            "decayed_keys": decayed_keys,
            "remaining_count": len(active_items)
        }
    except Exception as e:
        engine.log_audit("error", f"手动衰减异常: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/logs")
async def get_audit_logs():
    """获取后台任务产生的审计日志列表。"""
    return {"logs": engine.audit_logs}

@app.get("/api/debug_info")
async def get_session_debug_info(session_id: str = Query(..., description="会话唯一标识符")):
    """获取指定 Session 的内存工作记忆 (Working Memory) 详情。"""
    # 如果内存中的 session 还没有被载入，先热重构
    if not engine.buffer_manager.messages and not engine.buffer_manager.current_summary:
        await engine.buffer_manager.load_state(engine.store, session_id)
        
    return {
        "session_id": session_id,
        "current_summary": engine.buffer_manager.current_summary,
        "messages": engine.buffer_manager.messages,
        "token_limit": engine.buffer_manager.token_limit,
        "is_summarizing": engine.buffer_manager._is_summarizing
    }

if __name__ == "__main__":
    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=True)
