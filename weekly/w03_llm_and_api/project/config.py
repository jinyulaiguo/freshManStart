"""
OpsChat CLI - 全局配置中心 (config.py)

=========================================
设计方案说明
=========================================
1. 设计意图：
   提供集中式的参数配置中心。管理 API 密钥、API 地址、默认模型名称以及
   用于 Token 审计的每百万 Token 收费标准（美元费率）。

2. 变量/配置结构：
   - 载入环境变量。
   - LLM_PRICING: Dict[str, Dict[str, float]] 存储不同大模型每 1,000,000 Token 的输入/输出单价。
   - MINIMAX_API_KEY, MINIMAX_BASE_URL, MINIMAX_MODEL.
   - DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL.
=========================================
"""

import os
from dotenv import load_dotenv

# 载入环境变量 (从当前目录、上层目录或工作空间根目录加载)
load_dotenv()

# 大模型美元费率表 (每 1,000,000 Tokens)
LLM_PRICING = {
    "MiniMax-M3": {
        "input": 1.0,   # 1.0 USD per 1M tokens
        "output": 8.0   # 8.0 USD per 1M tokens
    },
    "MiniMax-M2.7": {
        "input": 0.8,
        "output": 6.0
    },
    "deepseek-chat": {
        "input": 0.14,  # 0.14 USD per 1M tokens
        "output": 0.28  # 0.28 USD per 1M tokens
    },
    "gpt-4o": {
        "input": 2.5,
        "output": 10.0
    },
    # 默认兜底费率
    "default": {
        "input": 1.0,
        "output": 5.0
    }
}

# CSV 审计日志默认保存路径
DEFAULT_AUDIT_LOG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "audit_log.csv"
)
