#!/bin/bash

# 获取脚本所在的物理目录，并切换到项目工作区根目录以支持模块运行
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR/../../.."

# 防御性检测主工作区根目录的 .env 文件
if [ ! -f ".env" ]; then
    echo -e "\033[33m⚠️  [Warning] 未在项目根目录下找到 .env 配置文件，请确保系统已注入有效 API Credentials！\033[0m"
fi

show_help() {
    echo "========================================================"
    echo "   AI 研究助手 - 经典 Policy RAG 系统一键启动管理脚本"
    echo "========================================================"
    echo "使用方法: ./start_rag_bot.sh [OPTION]"
    echo "可选项 (Mutually Exclusive):"
    echo "  --web      启动可视化 Web 网页服务 (默认模式)"
    echo "  --cli      启动命令行终端交互式 CLI 模式"
    echo "  --test     运行端到端非交互自动化冒烟测试"
    echo "  --help     查看脚本帮助说明"
    echo "========================================================"
}

MODE="--web"

# 参数路由解析
if [ "$1" != "" ]; then
    case $1 in
        --web )
            MODE="--web"
            ;;
        --cli )
            MODE="--cli"
            ;;
        --test )
            MODE="--test"
            ;;
        --help )
            show_help
            exit 0
            ;;
        * )
            echo -e "\033[31m❌ 错误: 未知启动参数: $1\033[0m"
            show_help
            exit 1
            ;;
    esac
fi

echo -e "\033[32m🚀 正在启动 Policy RAG 问答系统 (启动参数: $MODE)...\033[0m"
python -m weekly.w07_classic_rag.day49.main $MODE
