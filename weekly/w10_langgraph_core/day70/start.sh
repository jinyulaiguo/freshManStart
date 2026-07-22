#!/usr/bin/env bash
# Day 70 CVE Triage Pipeline — 一键启动脚本
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
VENV_PYTHON="$PROJECT_ROOT/.venv/bin/python"
PORT=8070

echo "======================================================================"
echo "🚀 Day 70: Enterprise CVE Triage Pipeline — 启动中..."
echo "======================================================================"

# 自动检测并清理端口占用
PID=$(lsof -ti:$PORT 2>/dev/null || true)
if [ -n "$PID" ]; then
  echo "⚠️ 发现端口 $PORT 被进程 (PID: $PID) 占用，正在执行清理..."
  kill -9 $PID 2>/dev/null || true
  sleep 0.5
  echo "✅ 端口 $PORT 占用已成功释放"
fi

cd "$SCRIPT_DIR"

if command -v uv &> /dev/null; then
  echo "📦 使用 uv 执行服务..."
  echo "🌐 启动 Web 服务器 → http://127.0.0.1:$PORT"
  echo "   按 Ctrl+C 停止服务"
  echo "======================================================================"
  uv run uvicorn server:app --host 0.0.0.0 --port $PORT --reload
elif [ -f "$VENV_PYTHON" ]; then
  echo "🌐 启动 Web 服务器 → http://127.0.0.1:$PORT"
  echo "   按 Ctrl+C 停止服务"
  echo "======================================================================"
  "$VENV_PYTHON" -m uvicorn server:app --host 0.0.0.0 --port $PORT --reload
else
  echo "❌ 未找到虚拟环境或 uv 命令"
  echo "   请先在项目根目录执行: uv sync"
  exit 1
fi
