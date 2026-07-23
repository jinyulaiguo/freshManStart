#!/usr/bin/env bash

# Day 77 物理拉起 Web 服务与 Dashboard 看板启动脚本
# 规范要求：收拢在 Day 77 Project 阶段目录中，物理校验环境并启动 FastAPI 服务

set -e

echo "======================================================================"
echo "🚀 启动 Day 77: 企业级 SQL 执行 Agent (Web 调试 Dashboard)"
echo "======================================================================"

# 1. 获取脚本所在的物理绝对路径
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/../../.." && pwd )"

echo "  • 工作区根目录: $PROJECT_ROOT"
echo "  • 项目目录: $SCRIPT_DIR"

# 2. 激活虚拟环境 (若存在)
if [ -d "$PROJECT_ROOT/.venv" ]; then
    echo "  • 激活 Python 虚拟环境: $PROJECT_ROOT/.venv"
    source "$PROJECT_ROOT/.venv/bin/activate"
fi

# 3. 执行 Python 基础依赖与环境校验
python3 -c "
import sys, os
project_root = '$PROJECT_ROOT'
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from weekly.w04_prompt_and_http.utils import load_env_file
load_env_file()

import redis, psycopg2
r = redis.Redis(host=os.getenv('REDIS_HOST', '127.0.0.1'), port=int(os.getenv('REDIS_PORT', 6379)), password=os.getenv('REDIS_PASSWORD', ''))
r.ping()
print('  ✅ Redis 物理连通性测试通过！')

pg_conn = psycopg2.connect(
    host=os.getenv('POSTGRES_HOST', '127.0.0.1'),
    port=int(os.getenv('POSTGRES_PORT', 5432)),
    user=os.getenv('POSTGRES_USER', 'postgres'),
    password=os.getenv('POSTGRES_PASSWORD', 'postgres'),
    dbname=os.getenv('POSTGRES_DB', 'postgres')
)
pg_conn.close()
print('  ✅ PostgreSQL 物理连通性测试通过！')
"

# 4. 自动物理初始化 PostgreSQL 沙箱数据库结构与 20 条种子数据
echo "  • 物理初始化 PostgreSQL 沙箱数据库..."
python3 "$SCRIPT_DIR/database/init_db.py"

echo "----------------------------------------------------------------------"
echo "🌐 物理拉起 FastAPI Web 服务看板..."
echo "👉 请在浏览器中打开 Web 调试 Dashboard 网址: http://127.0.0.1:8000"
echo "----------------------------------------------------------------------"

# 5. 使用 uvicorn 启动 Web 服务入口
cd "$SCRIPT_DIR"
exec uvicorn server:app --host 127.0.0.1 --port 8000 --reload
