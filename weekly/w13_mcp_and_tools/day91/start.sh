#!/bin/bash

# ==============================================================================
# Day 91 生产级启动脚本 (Process Group Daemon)
# ==============================================================================

set -e

PROJECT_ROOT=$(pwd)
VENV_DIR="$PROJECT_ROOT/.venv"
API_PORT=8000

echo "🚀 [Day 91] 启动 AI 研究助手生产级环境..."

# 1. 包管理提示
if ! command -v uv &> /dev/null; then
    echo "❌ 错误: 未安装 'uv'。请参照包管理规范使用 uv 进行依赖管理。"
    exit 1
fi

echo "📦 使用项目根目录的 Workspace 依赖配置..."

# 2. 严谨的冲突端口强杀逻辑
echo "🔍 检查业务端口冲突 (Port: $API_PORT)..."
CONFLICT_PIDS=$(lsof -ti :$API_PORT || true)

if [ -n "$CONFLICT_PIDS" ]; then
    echo "⚠️ 发现冲突的旧业务进程 (PIDs: $CONFLICT_PIDS)，正在安全清理..."
    # 强制 kill 占用端口的进程，确保环境纯净
    kill -9 $CONFLICT_PIDS
    sleep 1
    echo "✅ 端口 $API_PORT 已释放。"
else
    echo "✅ 端口 $API_PORT 畅通。"
fi

# 注意：绝不触及 Qdrant (6333) 和 PostgreSQL (5432) 的端口清理，遵守基础设施隔离规范。

# 3. 启动 FastAPI 代理网关 (统一守护模式)
echo "🌐 启动企业级网关服务 (FastAPI SSE & WebSocket)..."
export PYTHONPATH="$PROJECT_ROOT/src:$PYTHONPATH"

# 使用 exec 让 uvicorn 接管主进程，方便终端 Ctrl+C 优雅关闭整个进程树
exec uv run uvicorn src.presentation.api:app --host 0.0.0.0 --port $API_PORT --reload
