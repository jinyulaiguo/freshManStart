"""
RAG 规章制度助手可视化后端 (app.py) — FastAPI Web API 路由器

设计方案：
==========
1. 设计意图：
   将 Week 7 的多格式解析、自适应语义切块、哈希去重入库、 Lost-in-the-Middle 规避
   以及基于 Context 的流式可信脚注引用生成，以标准的 HTTP API 方式暴露。
   前端可以通过浏览器进行交互，上传文件并实时观测合规 RAG 系统的流式回答与原始文献对照。

2. 核心 API 端点：
   - `GET /` : 返回前端单页面 HTML。
   - `GET /api/status` : 返回 Qdrant 客户端的底层运行状态。
   - `GET /api/documents` : 从 Qdrant 中 scroll 倒排取出已入库的文件去重列表。
   - `POST /api/upload` : 多文档上传，保存至临时工作目录，并向后台注册任务，异步进行解析和入库。
   - `GET /api/upload/status` : 获取当前所有正在处理的文档进度详情。
   - `POST /api/query` : 接收用户查询，并采用 StreamingResponse 返回 text/event-stream。
"""

import os
import json
import shutil
import pathlib
import time
from typing import List, Dict
from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

# 导入 Day 49 经典 RAG 控制组件
from weekly.w07_classic_rag.day49.solution import ChunkIndexer, CitationRAGBot
from weekly.w07_classic_rag.day48.solution import MultiFormatDocIngestor

app = FastAPI(
    title="Policy RAG Assistant API",
    description="企业级规章制度合规问答 RAG 可视化后端"
)

# 物理路径配置 (存放在当前 Day49 目录下)
BASE_DIR = pathlib.Path(__file__).parent.resolve()
UPLOAD_DIR = BASE_DIR / "uploaded_docs"
TEMPLATE_FILE = BASE_DIR / "templates" / "index.html"

# 确保上传文件夹存在
os.makedirs(UPLOAD_DIR, exist_ok=True)

# 实例化核心 RAG 微引擎
# 连接配置使用本地 Docker 127.0.0.1，如不可用 QdrantVectorStore 内部会自动降级到 sqlite :memory:
indexer = ChunkIndexer(collection_name="company_policy", dimension=1536)
bot = CitationRAGBot(indexer, similarity_threshold=0.4)

# 全局内存任务进度表，键为文件名，值为其处理状态与进度
upload_tasks: Dict[str, dict] = {}


class QueryRequest(BaseModel):
    query: str


async def process_document_background(filename: str, saved_path: str, temp_dir: str):
    """
    后台异步文档解析与入库任务，动态向上反馈处理进度与细节说明
    """
    try:
        # Step 1: 文档文本和表格提取
        upload_tasks[filename] = {
            "filename": filename,
            "status": "processing",
            "progress": 15,
            "detail": "正在解析文档文本与表格结构...",
            "error_message": ""
        }
        
        # 实例化 Day 48 Ingestor 对该文件的临时目录进行高保真解析
        ingestor = MultiFormatDocIngestor(temp_dir)
        # scan_and_ingest 是同步物理 IO
        pages = ingestor.scan_and_ingest()
        
        if not pages:
            upload_tasks[filename] = {
                "filename": filename,
                "status": "error",
                "progress": 0,
                "detail": "解析失败",
                "error_message": "未能从此文件中提取出任何有效文本数据。"
            }
            # 清理临时工作目录
            shutil.rmtree(temp_dir, ignore_errors=True)
            return

        # Step 2: 语义切片
        upload_tasks[filename]["progress"] = 40
        upload_tasks[filename]["detail"] = "正在通过句子相似度突变进行自适应分块..."
        
        # 增量入库，recreate 设为 False，避免清空其他已存在文档
        total_chunks = await indexer.ingest_and_index(pages, recreate=False)

        # Step 3: 更新为处理成功
        upload_tasks[filename] = {
            "filename": filename,
            "status": "success",
            "progress": 100,
            "detail": f"解析并入库成功！共生成 {total_chunks} 个去重切片。",
            "error_message": ""
        }
        
        # 清理临时工作目录，保持环境整洁
        shutil.rmtree(temp_dir, ignore_errors=True)
        
    except Exception as e:
        print(f"⚠️ [Background Task] 文件 {filename} 处理异常: {e}")
        upload_tasks[filename] = {
            "filename": filename,
            "status": "error",
            "progress": 0,
            "detail": "处理失败",
            "error_message": str(e)
        }
        # 防御性清理
        shutil.rmtree(temp_dir, ignore_errors=True)


@app.get("/", response_class=HTMLResponse)
async def read_index():
    """渲染前端 HTML 页面"""
    if not os.path.exists(TEMPLATE_FILE):
        raise HTTPException(status_code=404, detail="模板 index.html 文件不存在，请检查 templates/ 目录结构。")
    with open(TEMPLATE_FILE, "r", encoding="utf-8") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content)


@app.get("/api/status")
async def get_status():
    """获取 Qdrant 客户端底层运行状态"""
    return {
        "is_memory_mode": indexer.vector_store.is_memory_mode,
        "collection_name": indexer.collection_name
    }


@app.get("/api/documents")
async def get_documents():
    """从向量数据库 scroll 检索所有点，提取 payload 中去重的原始文件名列表"""
    try:
        # Step 1: 调用 Qdrant 底层 client 进行点遍历（不拉取 Vector 节省宽带）
        res, _ = indexer.vector_store.client.scroll(
            collection_name=indexer.collection_name,
            limit=500,
            with_payload=True,
            with_vectors=False
        )
        
        seen_docs = set()
        docs = []
        
        # Step 2: 解析点列表并执行去重
        for point in res:
            payload = point.payload or {}
            source_file = payload.get("source_path", "")
            if source_file and source_file not in seen_docs:
                seen_docs.add(source_file)
                file_ext = os.path.splitext(source_file)[1].replace(".", "")
                docs.append({
                    "name": source_file,
                    "type": file_ext
                })
        return docs
    except Exception as e:
        print(f"⚠️ [Web API] 获取已入库文档列表失败: {e}")
        return []


@app.post("/api/upload")
async def upload_documents(background_tasks: BackgroundTasks, files: List[UploadFile] = File(...)):
    """
    接收上传的文件并立即返回，在后台进行异步切片向量化处理
    """
    if not files:
        raise HTTPException(status_code=400, detail="未检测到任何上传的文件。")

    uploaded_files_info = []

    for file in files:
        filename = file.filename
        
        # 为本次文件处理创建一个物理隔离的临时目录，避免后台并发时发生 IO 冲突
        task_temp_dir = UPLOAD_DIR / f"task_{int(time.time() * 1000)}_{filename}"
        os.makedirs(task_temp_dir, exist_ok=True)
        
        saved_path = task_temp_dir / filename
        
        # 保存上传的文件到磁盘
        with open(saved_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
            
        # 在进度注册表里初始化当前文件的 Pending 状态
        upload_tasks[filename] = {
            "filename": filename,
            "status": "pending",
            "progress": 5,
            "detail": "已上传，排队等待解析...",
            "error_message": ""
        }
        
        # 添加后台任务
        background_tasks.add_task(
            process_document_background,
            filename,
            str(saved_path),
            str(task_temp_dir)
        )
        
        uploaded_files_info.append(filename)

    return {
        "status": "success",
        "message": f"成功接收了 {len(uploaded_files_info)} 个文件，已加入后台处理队列。",
        "files": uploaded_files_info
    }


@app.get("/api/upload/status")
async def get_upload_status():
    """
    获取后台所有正在处理的文档进度
    """
    return upload_tasks


@app.post("/api/query")
async def query_rag(request: QueryRequest):
    """
    核心 SSE 流式问答 API。
    通过 StreamingResponse 吐出 JSON 格式的 Event，使前端能实时渲染回答和对应文献审计表。
    """
    query_text = request.query.strip()
    if not query_text:
        raise HTTPException(status_code=400, detail="查询内容不能为空。")

    # 异步非阻塞生成器
    async def sse_generator():
        try:
            # 顺序迭代 bot.answer_stream 推出的状态与 token 包
            async for packet in bot.answer_stream(query_text):
                yield f"data: {json.dumps(packet, ensure_ascii=False)}\n\n"
            # 协议收尾标记
            yield "data: [DONE]\n\n"
        except Exception as e:
            print(f"⚠️ [SSE Stream] 生成发生严重崩溃异常: {e}")
            error_packet = {
                "type": "delta",
                "content": f"\n\n\033[31m[系统异常] 请求处理失败: {str(e)}\033[0m"
            }
            yield f"data: {json.dumps(error_packet, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(sse_generator(), media_type="text/event-stream")
