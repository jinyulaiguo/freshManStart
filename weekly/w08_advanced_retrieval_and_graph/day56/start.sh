#!/usr/bin/env bash
# File: start.sh
# Description: 一键启动可视化推理分析器看板脚本（Mac OS）

# 1. 激活虚拟环境
VENV_PATH="/Users/zhouyi/03.AI/03.freshManStart/.venv/bin/activate"
if [ -f "$VENV_PATH" ]; then
    echo "-> 正在激活虚拟环境..."
    source "$VENV_PATH"
else
    echo "⚠️ 未找到虚拟环境，将使用全局 Python 环境。"
fi

# 2. 导出 python path，确保 python 导入正常
export PYTHONPATH="/Users/zhouyi/03.AI/03.freshManStart:$PYTHONPATH"

# 3. 异步启动浏览器打开看板页面（延迟 1.5 秒等 Python 服务端就绪）
(
    sleep 1.5
    echo "-> 正在自动为您打开可视化推理看板..."
    open "http://localhost:8000/"
) &

# 4. 运行后端服务器
echo "-> 正在启动 HTTP & SSE 推理后端服务器..."
python /Users/zhouyi/03.AI/03.freshManStart/weekly/w08_advanced_retrieval_and_graph/day56/server.py
