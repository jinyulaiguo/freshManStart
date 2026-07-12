"""
AetherMind FastAPI Server Entry Point
====================================

设计方案:
---------
该模块为 AetherMind 系统提供 FastAPI 异步 HTTP 服务入口。
- **并发与流式响应 (SSE)**：核心交互端点 `POST /api/chat` 支持标准 SSE (Server-Sent Events)
  事件流输出。利用 `sse-starlette` 将大模型生成的 Token 及中间推理 Trace 日志实时推送至前端。
- **多存储自动组装**：基于全局配置文件 `config.py` 中的开关，
  在启动时动态切换 SQLite / PostgreSQL 后端及物理/模拟 Qdrant，构建主引擎单例。
- **在线文档导入 (RAG)**：`POST /api/documents` 支持上传纯文本文件，
  并在后台完成分块向量化与 GraphRAG 图谱重构。
- **极简一体化**：`GET /` 端点直接提供 Dashboard 静态调试看板 HTML，实现一键启动即可使用。

结构说明:
---------
- lifespan: FastAPI 异步生命周期管理器，处理启动时引擎构建与反向索引重建、关闭时连接释放。
- ChatRequest: 会话请求体 Pydantic 契约。
- server endpoints: `/`, `/api/chat`, `/api/documents`。
"""

import json
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, File, UploadFile, HTTPException, Depends
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel, Field

from aether_mind.config import settings
from aether_mind.storage.sqlite import SQLiteStore
from aether_mind.storage.postgres import PostgreSQLStore
from aether_mind.storage.qdrant import QdrantVectorStore
from aether_mind.core.engine import MemoryAgentEngine
from aether_mind.utils.logging import logger

# === 1. 动态建立数据库后端实例 ===
if settings.db_backend == "postgres":
    # 拼装 PostgreSQL DSN 连接串
    dsn = (
        f"postgresql://{settings.postgres_user}:{settings.postgres_password}"
        f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
    )
    db = PostgreSQLStore(dsn)
else:
    # 默认 SQLite 路径
    db = SQLiteStore(settings.sqlite_db_path)

# === 2. 动态实例化 Qdrant 客户端 ===
vector_store = QdrantVectorStore(
    host=settings.qdrant_host,
    port=settings.qdrant_port,
    api_key=settings.qdrant_api_key
)

# === 3. 装配 Master 引擎 ===
engine = MemoryAgentEngine(db, vector_store)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI 生命周期管理器，处理系统热启动与关闭。
    """
    # 启动阶段：初始化关系表、向量集合，并从 Qdrant 加载重建图谱
    await engine.initialize()
    logger.info("[lifespan] AetherMind 引擎启动就绪。")
    yield
    # 关闭阶段：安全释放 PostgreSQL 连接池
    if hasattr(db, "close"):
        await db.close()
    logger.info("[lifespan] AetherMind 连接资源已安全释放。")


app = FastAPI(
    title="AetherMind API",
    description="企业级多会话 AI 研究助手后端服务",
    version="0.2.0",
    lifespan=lifespan
)

# 配置 CORS 跨域，支持 Dashboard 在不同主机下调用
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)


class ChatRequest(BaseModel):
    """
    对话请求 Pydantic 参数限制。
    """
    session_id: str = Field(..., description="会话唯一 ID")
    user_id: str = Field(..., description="租户用户唯一 ID")
    query: str = Field(..., description="用户提问问题")


@app.get("/", response_class=HTMLResponse)
async def read_dashboard():
    """
    一体化集成端点：直接载入返回本地的 dashboard.html 调试看板页面。
    """
    current_dir = os.path.dirname(os.path.abspath(__file__))
    html_path = os.path.join(current_dir, "dashboard.html")
    
    if not os.path.exists(html_path):
        raise HTTPException(status_code=404, detail="Dashboard UI file not found.")
        
    with open(html_path, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest):
    """
    SSE 流式交互端点。逐个推送 Trace 追踪和 Token 文本。
    """
    logger.info(f"[API Chat] session_id: {request.session_id}, query: {request.query[:30]}...")

    # 使用生成器将引擎数据转换为标准的 SSE "data: ..." 结构化行
    async def event_generator():
        try:
            async for event in engine.handle_message_stream(
                session_id=request.session_id,
                user_id=request.user_id,
                query=request.query
            ):
                # 以 JSON 格式输出，方便前端 JS 统一解析
                yield {"data": json.dumps(event)}
        except Exception as err:
            logger.error(f"[SSE 发生未捕获异常] {str(err)}", exc_info=True)
            yield {"data": json.dumps({"type": "error", "content": f"Internal Server Error: {str(err)}"}) }

    return EventSourceResponse(event_generator())


@app.post("/api/documents")
async def upload_document(file: UploadFile = File(...)):
    """
    知识库上传端点。切片并导入向量数据库与 GraphRAG 图谱。
    """
    logger.info(f"[API Upload] 接收到文件上传: {file.filename}")
    
    # 限制上传格式为纯文本，便于教学解析
    if not file.filename.lower().endswith((".txt", ".md", ".json", ".pdf")):
        raise HTTPException(
            status_code=400, 
            detail="仅支持上传 .txt, .md, .json 或 .pdf 类型的文档文件。"
        )

    try:
        raw_bytes = await file.read()
        
        # 根据文件类型提取文本
        if file.filename.lower().endswith(".pdf"):
            import io
            from pypdf import PdfReader
            
            try:
                reader = PdfReader(io.BytesIO(raw_bytes))
                pdf_text_parts = []
                for page in reader.pages:
                    page_text = page.extract_text()
                    if page_text:
                        pdf_text_parts.append(page_text)
                text_content = "\n".join(pdf_text_parts)
            except Exception as pdf_err:
                raise ValueError(f"PDF 文档解析失败，可能格式损坏: {str(pdf_err)}")
        else:
            text_content = raw_bytes.decode("utf-8")
        
        # 调度 RAGEngine 进行切片、向量计算、图谱增量更新与社区重建
        chunks_count = await engine.rag_engine.index_document(
            file_name=file.filename,
            content=text_content,
            vector_store=vector_store
        )

        
        return {
            "status": "accepted",
            "file_name": file.filename,
            "chunks_count": chunks_count,
            "message": "文档读取切片并向量化、图谱重构分析完毕。"
        }
        
    except Exception as e:
        logger.error(f"[API Upload Error] {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"文件处理失败: {str(e)}")
