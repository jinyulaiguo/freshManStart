#!/usr/bin/env bash
# Day 105: 启动 Eval Dashboard（FastAPI + WebSocket）
# 页面交互触发真实 LLM Judge / 可选 live ResearchAgent
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
W15_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
API_PORT="${API_PORT:-8105}"

echo "🚀 [Day 105] 启动 Eval Dashboard..."
echo "   仓库: $REPO_ROOT"
echo "   目录: $SCRIPT_DIR"
echo "   端口: $API_PORT"

# 1) 端口清理（不碰 5432/6379/6333）
echo "🔍 检查端口 $API_PORT ..."
CONFLICT_PIDS=$(lsof -ti :"$API_PORT" || true)
if [ -n "$CONFLICT_PIDS" ]; then
  echo "⚠️  释放占用进程: $CONFLICT_PIDS"
  kill -9 $CONFLICT_PIDS || true
  sleep 1
fi

# 2) 加载 .env（若存在）以便 MINIMAX_* 进入进程
if [ -f "$REPO_ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$REPO_ROOT/.env"
  set +a
  echo "✅ 已加载 $REPO_ROOT/.env"
fi

if [ -z "${MINIMAX_API_KEY:-}" ]; then
  echo "⚠️  未检测到 MINIMAX_API_KEY —— 页面默认真实 Judge 将失败；可勾选 Offline 调试。"
else
  echo "✅ MINIMAX_API_KEY 已就绪 · model=${MINIMAX_MODEL:-unset}"
fi

export PYTHONPATH="$W15_ROOT:$REPO_ROOT/weekly/w04_prompt_and_http:${PYTHONPATH:-}"

echo "🌐 Dashboard → http://localhost:$API_PORT"
echo "   打开页面后点击「运行评测」触发真实 LLM 流水线"
cd "$SCRIPT_DIR"
exec uv run uvicorn server:app --host 0.0.0.0 --port "$API_PORT" --reload \
  --reload-dir "$SCRIPT_DIR" \
  --reload-dir "$W15_ROOT"
