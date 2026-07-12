#!/bin/bash
# AetherMind V2 FastAPI 服务拉起脚本

# 1. 自动定位项目根目录与 Python 虚拟环境
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
WORKSPACE_DIR="$DIR/../../.."

echo "=================================================="
echo "AetherMind V2 - 企业级 AI 记忆增强助手引擎启动中..."
echo "=================================================="

# 2. 加载 .env 环境变量并导出，供 Python 进程读取
ENV_PATH="$DIR/.env"
if [ -f "$ENV_PATH" ]; then
    echo "正在从本地 .env 加载环境变量配置..."
    export $(grep -v '^#' "$ENV_PATH" | xargs)
else
    # 兜底加载根目录下的 .env
    ROOT_ENV_PATH="$WORKSPACE_DIR/.env"
    if [ -f "$ROOT_ENV_PATH" ]; then
        echo "本地未找到 .env，正在从工作区根目录加载环境变量配置..."
        export $(grep -v '^#' "$ROOT_ENV_PATH" | xargs)
    else
        echo "警告: 未检测到任何 .env 文件，请确保大模型 Key 环境变量已设置！"
    fi
fi

# 3. 设置 PYTHONPATH，确保 aether_mind 模块可被正确寻址导入
export PYTHONPATH="$WORKSPACE_DIR:$DIR:$PYTHONPATH"

# 4. 自动检测并释放 8000 端口冲突
PORT=8000
echo "正在检查端口 $PORT 是否被占用..."
PIDS=$(lsof -t -i:$PORT)
if [ -n "$PIDS" ]; then
    echo "警告: 端口 $PORT 已被以下进程占用，PID(s): $(echo $PIDS | xargs)"
    echo "正在释放端口并终止冲突进程..."
    # 尝试发送 SIGTERM 信号优雅终止
    echo $PIDS | xargs kill -15 2>/dev/null
    sleep 1.5
    
    # 再次检查端口释放状态
    REMAINING_PIDS=$(lsof -t -i:$PORT)
    if [ -n "$REMAINING_PIDS" ]; then
        echo "进程未完全退出，正在强制终止 (SIGKILL)，PID(s): $(echo $REMAINING_PIDS | xargs)"
        echo $REMAINING_PIDS | xargs kill -9 2>/dev/null
        sleep 1
    fi
    echo "端口 $PORT 已成功释放。"
else
    echo "端口 $PORT 未被占用，可安全启动。"
fi

# 5. 判断并使用 uv 虚拟环境中的 python 物理执行
VENV_PYTHON="$WORKSPACE_DIR/.venv/bin/python"
if [ -f "$VENV_PYTHON" ]; then
    echo "检测到工作区虚拟环境，使用 venv python 拉起服务..."
    "$WORKSPACE_DIR/.venv/bin/uvicorn" server:app --host 127.0.0.1 --port 8000 --reload
else
    echo "未检测到 venv 虚拟环境，尝试使用系统全局 uvicorn 拉起服务..."
    uvicorn server:app --host 127.0.0.1 --port 8000 --reload
fi
