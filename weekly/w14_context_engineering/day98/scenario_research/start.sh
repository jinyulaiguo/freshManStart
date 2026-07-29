#!/bin/bash

# ==============================================================================
# Day 98 场景一: Research Agent 启动脚本
# 端口: 8098
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
W14_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
API_PORT=8098

echo "🚀 [Day 98 场景一] 启动 Research Agent Context Runtime..."
echo "   项目根目录: $PROJECT_ROOT"
echo "   场景目录: $SCRIPT_DIR"

# 1. 端口冲突清理
echo "🔍 检查业务端口冲突 (Port: $API_PORT)..."
CONFLICT_PIDS=$(lsof -ti :$API_PORT || true)

if [ -n "$CONFLICT_PIDS" ]; then
    echo "⚠️ 发现冲突进程 (PIDs: $CONFLICT_PIDS)，正在清理..."
    kill -9 $CONFLICT_PIDS
    sleep 1
    echo "✅ 端口 $API_PORT 已释放。"
else
    echo "✅ 端口 $API_PORT 畅通。"
fi

# 注意：绝不触及基础设施端口 (PostgreSQL 5432, Redis 6379, Qdrant 6333)

# 2. 设置 PYTHONPATH (导入 Day 92~97 微引擎 + W04 工具)
export PYTHONPATH="$W14_ROOT:$PROJECT_ROOT/weekly/w04_prompt_and_http:$PYTHONPATH"

# 3. 启动 FastAPI 服务
echo "🌐 启动 Research Agent Dashboard (http://localhost:$API_PORT)..."
exec uv run uvicorn server:app --host 0.0.0.0 --port $API_PORT --reload \
    --reload-dir "$SCRIPT_DIR" --reload-dir "$W14_ROOT"
