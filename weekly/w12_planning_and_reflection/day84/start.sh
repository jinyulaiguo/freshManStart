#!/bin/bash
# ============================================================================
# Day 84 综合实战: Web Dashboard 服务启动脚本 (start.sh)
# 说明: 一键自动清理旧进程并拉起 FastAPI Web 界面 (http://localhost:8000)
# ============================================================================

set -e

echo "🚀 [Day 84 启动脚本] 正在启动 Advanced Industry Research Agent Web Dashboard..."

# 获取当前脚本所在目录与项目根目录
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/../../.." && pwd )"

cd "$PROJECT_ROOT"

# 自动检测并停止占用 8000 端口的残余旧进程
OLD_PID=$(lsof -ti:8000 2>/dev/null || true)
if [ -n "$OLD_PID" ]; then
    echo "🧹 [端口清理] 检测到端口 8000 已被残余旧进程 (PID: $OLD_PID) 占用，正在自动清理停止..."
    kill -9 $OLD_PID 2>/dev/null || true
    sleep 0.5
    echo "✅ [端口清理] 端口 8000 释放成功。"
fi

# 加载 Python 虚拟环境 (如果存在)
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# 检查 Python3
if ! command -v python3 &> /dev/null; then
    echo "❌ 错误: 未检测到 python3 命令！"
    exit 1
fi

echo "🌐 Web Dashboard 访问地址: http://localhost:8000"
echo "按 Ctrl+C 可停止服务"
echo "--------------------------------------------------------------------------------"

python3 weekly/w12_planning_and_reflection/day84/server.py
