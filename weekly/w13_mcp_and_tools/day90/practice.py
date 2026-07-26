"""
Day 90 练习模版: 面向真实 LLM 的 MCP 多模态工具与 Progress 规约 Agent 闭环实战

设计意图:
    本练习引导学员掌握在真实 LLM 驱动下 MCP 多模态 Content Block 与 Agent 的完整交互:
    1. 【Schema 动态转换】: 将 MCP `list_tools()` 契约转换为 LLM 能识别的 Tool Schema；
    2. 【真实 LLM 智能决策】: 真实 LLM 读取用户自然语言 Query 发起 Tool Call；
    3. 【多模态 ImageContent 传输】: MCP Server 内存生成 Matplotlib Base64 PNG 字节流返回；
    4. 【多模态结果总结】: 真实 LLM 汇总多模态工具响应并生成业务分析报告。

主入口测试用例设计意图 (Test Case Design Intent):
    引导学员补全 MCP 工具 Schema 到 LLM 的转换逻辑、真实 LLM 工具调用链路与多模态响应处理。
"""

import io
import sys
import json
import base64
import asyncio
from pathlib import Path
from typing import Dict, Any, List

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.server.fastmcp import FastMCP, Context
from mcp.types import ImageContent, TextContent

# 确保项目根目录在 PYTHONPATH 中
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

# 🔑 复用项目公共基础设施
from weekly.w04_prompt_and_http.utils import LLMClient


mcp_server = FastMCP("analytics-chart-server")


@mcp_server.tool(name="generate_analytics_chart")
async def generate_analytics_chart(
    dataset_name: str,
    data_points: List[float],
    ctx: Context
) -> List[Any]:
    """【多模态长任务工具】对指定数据集进行可视化分析"""
    # TODO: 学员在此实现 Matplotlib 内存画图并返回 ImageContent 与 TextContent 块
    raise NotImplementedError("TODO: 请实现 generate_analytics_chart 工具")


def convert_mcp_tools_to_openai_schema(mcp_tools) -> List[Dict[str, Any]]:
    """将 MCP list_tools 契约转换为 LLM 工具格式"""
    # TODO: 学员需在此完成 MCP Schema 到 LLM 工具格式的转化
    raise NotImplementedError("TODO: 请实现 convert_mcp_tools_to_openai_schema")


async def run_multimodal_llm_agent_experiment():
    """面向真实 LLM 的 MCP 多模态 Agent 练习主流程"""
    client = LLMClient()
    
    # TODO: 学员在此实现:
    # 1. 动态反射获取 MCP Server 暴露的 Tools 并转给 client (LLMClient)；
    # 2. 真实 LLM 读取 Query 决策 Tool Call；
    # 3. 客户端安全执行 MCP 多模态工具并解析 Base64 字节流；
    # 4. 将工具结果送回真实 LLM 进行业务汇报输出。
    raise NotImplementedError("TODO: 请完成 run_multimodal_llm_agent_experiment 测试")


if __name__ == "__main__":
    try:
        if len(sys.argv) > 1 and sys.argv[1] == "--server-mode":
            mcp_server.run(transport="stdio")
        else:
            asyncio.run(run_multimodal_llm_agent_experiment())
    except (NotImplementedError, BaseExceptionGroup) as e:
        print("⚠️ 拦截到未实现提示:", e)
        print("请打开 practice.py 完成 TODO 部分的代码实现。")
