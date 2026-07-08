#!/bin/bash

# ==============================================================================
# AI Research Assistant Knowledge Engine — 一键启动与热导入脚本
# ==============================================================================
# 设计意图：
# 1. 一键后台拉起 Qdrant 本地 Docker 数据库容器。
# 2. 轮询等待 Qdrant 向量服务端口就绪。
# 3. 自动执行离线 Ingest 知识导入流水线，处理 test_data 样例异构文档。
# 4. 自动拉起本地 FastAPI Web 服务器并呼出 UI 可观测面板。
# ==============================================================================

# 设置严格错误拦截
set -e

# 定位当前脚本所在的物理目录
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_DIR="$(cd "${PROJECT_DIR}/../../../" && pwd)"

echo "================================================================================"
echo "🚀 正在启动 AI Research Assistant RAG 知识引擎可视化终端..."
echo "================================================================================"

# 1. 轮询等待 Qdrant 服务上线
echo "⏱️ [Step 1/3] 正在等待已运行的 Qdrant 数据库就绪..."
RETRIES=15
READY=0
for i in $(seq 1 $RETRIES); do
  if curl -s -f http://127.0.0.1:6333/ > /dev/null 2>&1; then
    READY=1
    break
  fi
  echo "⌛ 数据库就绪探测中 ($i/$RETRIES)..."
  sleep 1
done

if [ $READY -eq 0 ]; then
  echo "❌ [Error] 未探测到 127.0.0.1:6333 上的 Qdrant 服务，请确保您的本地 Docker 容器已启动。"
  exit 1
fi
echo "✅ Qdrant 数据库连接成功。"

# 2. 执行默认数据导入流水线 (Ingestion)
echo "📥 [Step 2/3] 正在扫描并执行离线数据 Ingest 导入流水线..."
cd "${WORKSPACE_DIR}"
./.venv/bin/python -m weekly.w06_embedding_and_vector_db.project.main ingest --dir "./weekly/w06_embedding_and_vector_db/project/test_data/"

# 3. 启动 Web 可视化控制台并自动打开浏览器
echo "🌐 [Step 3/3] 正在启动 FastAPI 可视化看版服务..."
./.venv/bin/python -m weekly.w06_embedding_and_vector_db.project.main ui --port 8000
