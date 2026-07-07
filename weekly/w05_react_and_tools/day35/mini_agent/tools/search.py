"""
MiniAgent Framework v1.0 — Web 搜索模拟工具

设计说明：
模拟 Web 搜索 API，故意添加 2 秒延迟，用于验证 Parallel Executor 的并发效率：
串行执行 3 个搜索 = 6+ 秒，并行执行 3 个搜索 ≈ 2 秒。
"""
from __future__ import annotations

import asyncio
import random

from ..agent.registry import tool


# 模拟搜索结果知识库
_SEARCH_DB: dict[str, str] = {
    "python": "Python 是一种解释型、动态类型的高级编程语言，由 Guido van Rossum 于 1991 年首次发布。",
    "asyncio": "asyncio 是 Python 3.4+ 引入的标准库，提供单线程、事件驱动的异步 I/O 框架。",
    "react": "ReAct（Reasoning and Acting）是一种将 LLM 的推理能力与行动能力结合的 Agent 框架范式。",
    "langchain": "LangChain 是一个用于开发大语言模型应用的开源框架，提供链式调用和工具集成等功能。",
    "langgraph": "LangGraph 是 LangChain 团队推出的有向图执行框架，支持多 Agent 工作流编排。",
    "openai": "OpenAI 是一家 AI 研究公司，开发了 GPT 系列大语言模型和 DALL-E 图像生成模型。",
    "minimax": "MiniMax 是中国领先的 AI 公司，研发了 MiniMax-M3 等多模态大语言模型。",
    "天气": "全球天气预报服务由各国气象局提供，实时数据通过 API 向开发者开放。",
    "杭州": "杭州是浙江省省会，以西湖风景区著称，也是中国重要的互联网科技中心城市。",
    "北京": "北京是中华人民共和国首都，也是政治、文化和国际交流中心。",
    "上海": "上海是中国最大的城市，长三角经济圈的核心，也是重要的全球金融中心。",
}


@tool
async def web_search(query: str) -> str:
    """
    模拟搜索互联网获取相关信息（含 2 秒延迟，用于验证并行调度效率）。

    Args:
        query: 搜索关键词或问题描述，例如 "Python asyncio 原理" 或 "杭州景点"。
    """
    # 【核心设计意图】：故意添加 2 秒延迟
    # 当 3 个 web_search 并行执行时，总时间应约为 2 秒而非 6 秒
    # 这是验证 Parallel Executor 并发效率的关键测试点
    await asyncio.sleep(2.0)

    # 关键词匹配搜索
    query_lower = query.lower()
    results = []

    for keyword, content in _SEARCH_DB.items():
        if keyword in query_lower or keyword in query:
            results.append(content)

    if results:
        combined = " | ".join(results[:3])  # 最多返回 3 条匹配结果
        return f"搜索 '{query}' 的结果：{combined}"
    else:
        # 没有精确匹配时返回通用模拟结果
        return (
            f"搜索 '{query}' 的结果：找到约 {random.randint(1000, 9999)} 条相关结果。"
            f"主要内容涉及：{query} 的基本概念、应用案例和最新进展。"
            f"（模拟搜索结果，实际需要接入真实搜索 API）"
        )
