#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
W14_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
API_PORT=8100

echo "🚀 [Day 98 场景三] 启动 Long Task Audit Agent..."

CONFLICT_PIDS=$(lsof -ti :$API_PORT || true)
if [ -n "$CONFLICT_PIDS" ]; then
    echo "⚠️ 清理端口 $API_PORT 冲突进程..."
    kill -9 $CONFLICT_PIDS && sleep 1
fi

export PYTHONPATH="$W14_ROOT:$PROJECT_ROOT/weekly/w04_prompt_and_http:$PYTHONPATH"
exec uv run uvicorn server:app --host 0.0.0.0 --port $API_PORT --reload \
    --app-dir "$SCRIPT_DIR"
