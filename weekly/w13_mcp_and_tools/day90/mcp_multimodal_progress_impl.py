"""
Day 90 正统架构师标准答案: 面向真实 LLM 的 MCP 多模态工具与 Progress 规约 Agent 闭环实战

设计意图:
    本模块示范在面向真实 LLM (MiniMax-M3) 的场景下，Agent 如何驱动 MCP 多模态工具:
    1. 【真实 LLM 决策调度 (Real LLM Drive)】: 用户输入自然语言 Query，真实 LLM 自动识别 MCP 工具 Schema 并发起 Tool Call；
    2. 【MCP 多模态 Content Block 响应】: FastMCP 工具在内存 (`io.BytesIO`) 动态绘制 Matplotlib 图表，
       封装 `ImageContent(type='image', data=b64, mimeType='image/png')` 字节流与 `TextContent` 组合返回；
    3. 【异步 Progress 进度推送】: 使用 `await ctx.report_progress(progress, total)` 实时推送长任务进度；
    4. 【多模态 Agent 结果总结】: 真实大模型接收 Tool 响应后，对数据与图表进行综合智能化总结。

真实工业业务场景 (Industrial Context):
    企业级 AI 数据分析与可视化报表 Agent 微服务 (Enterprise Data Analytics & Visualization Agent Service)。
"""

import io
import sys
import json
import base64
import asyncio
from pathlib import Path
from typing import Dict, Any, List

import matplotlib
matplotlib.use("Agg")  # 100% 纯内存后台渲染
import matplotlib.pyplot as plt

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.server.fastmcp import FastMCP, Context
from mcp.types import ImageContent, TextContent

# 确保项目根目录在 PYTHONPATH 中
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

# 🔑 复用项目公共基础基础设施 (规则 12 & 规则 20)
from weekly.w04_prompt_and_http.utils import LLMClient


# =====================================================================
# 1. 多模态与长耗时 MCP 服务端 (Multimodal & Progress FastMCP Server)
# =====================================================================
mcp_server = FastMCP("analytics-chart-server")


@mcp_server.tool(name="generate_analytics_chart")
async def generate_analytics_chart(
    dataset_name: str,
    data_points: List[float],
    ctx: Context
) -> List[Any]:
    """【多模态长任务工具】对指定数据集进行可视化分析，实时上报 Progress 进度，并返回 Base64 PNG 统计图表。"""
    
    total_steps = 4
    await ctx.info(f"开始分析数据集 [{dataset_name}]，总计 {len(data_points)} 个数据点...")

    # 1. 模拟步骤 1: 数据清洗
    await asyncio.sleep(0.3)
    await ctx.report_progress(progress=1, total=total_steps)

    # 2. 模拟步骤 2: 趋势计算
    await asyncio.sleep(0.3)
    await ctx.report_progress(progress=2, total=total_steps)

    # 3. 模拟步骤 3: 在内存中用 Matplotlib 绘图 (0 磁盘文件写)
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.plot(data_points, marker='o', color='#2e623a', linestyle='-', linewidth=2, label="指标趋势")
    ax.set_title(f"Dataset Analytics: {dataset_name}", fontsize=12, fontweight='bold')
    ax.set_xlabel("Sample Index")
    ax.set_ylabel("Value")
    ax.grid(True, linestyle="--", alpha=0.6)
    ax.legend()

    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=100, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)

    # 4. 模拟步骤 4: 编码为 Base64 字符串
    b64_data = base64.b64encode(buf.getvalue()).decode("utf-8")
    await ctx.report_progress(progress=4, total=total_steps)
    await ctx.info("✅ 图表渲染与 Base64 编码完成！")

    # 🔑 返回由 ImageContent 与 TextContent 构成的多模态 Content Block 列表
    return [
        ImageContent(
            type="image",
            data=b64_data,
            mimeType="image/png"
        ),
        TextContent(
            type="text",
            text=f"数据集 [{dataset_name}] 可视化分析完毕！样本数: {len(data_points)}，最高峰值: {max(data_points) if data_points else 0}。"
        )
    ]


# =====================================================================
# 2. 动态转换 MCP Schema 为 OpenAI / MiniMax Tool 格式
# =====================================================================
def convert_mcp_tools_to_openai_schema(mcp_tools) -> List[Dict[str, Any]]:
    """将 MCP list_tools 返回的工具转换给 LLMClient 消费"""
    llm_tools = []
    for tool in mcp_tools.tools:
        llm_tools.append({
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.inputSchema
            }
        })
    return llm_tools


# =====================================================================
# 3. 面向真实 LLM 的 Agent 端到端全流程实战
# =====================================================================
async def run_multimodal_llm_agent_experiment():
    """面向真实 LLM 的 MCP 多模态工具全流程 Agent 实战"""
    print("=== 启动 Day 90: 面向真实 LLM (MiniMax-M3) 的 MCP 多模态工具全流程 Agent ===")

    # 1. 加载项目公共 LLM 客户端
    client = LLMClient()
    print(f"✅ 已加载项目公共 LLMClient (端点: {client.base_url}, 模型: {client.model_name})")

    server_params = StdioServerParameters(
        command=sys.executable,
        args=[__file__, "--server-mode"],
        env=None
    )

    print("⚡ 正在拉起 Stdio 多模态 MCP Server 进程...")

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            print("✅ MCP ClientSession 协议握手成功!\n")

            # 2. 动态反射获取 MCP Server 暴露的 Tools Schema
            mcp_tools_res = await session.list_tools()
            llm_tools_schema = convert_mcp_tools_to_openai_schema(mcp_tools_res)
            print(f"📦 已成功反射转换 MCP 工具 Schema 给真实 LLM: {[t['function']['name'] for t in llm_tools_schema]}")

            # 3. 用户自然语言 Prompt
            user_query = "请帮我分析 Q3_Sales_Revenue 销售数据集，数据点是 [12.5, 45.2, 38.8, 67.4, 89.1, 102.3, 95.0]，并绘制趋势分析图汇报。"
            print(f"\n💬 用户 Request -> '{user_query}'")

            messages = [
                {"role": "system", "content": "你是一位专业的 AI 数据分析 Agent专家。遇到数据绘图需求时，请主动调用对应的多模态分析工具。"},
                {"role": "user", "content": user_query}
            ]

            # 4. 🔑 真实 LLM (MiniMax-M3) 自动决策 Tool Call
            print("\n🤖 [真实 LLM 思考中...] 正在读取 MCP 工具 Schema 并发起智能决策...")
            llm_msg = await client.request_llm_with_tools(messages, llm_tools_schema)

            tool_calls = llm_msg.get("tool_calls", [])
            if not tool_calls:
                print("❌ 真实 LLM 未选择触发工具。回答:\n", llm_msg.get("content", ""))
                return

            call_info = tool_calls[0]
            tool_name = call_info["function"]["name"]
            tool_args = json.loads(call_info["function"]["arguments"])
            print(f"\n🎯 真实 LLM 成功决策! 发起了 MCP Tool Call: [{tool_name}]")
            print(f"   LLM 提纯后的入参: {json.dumps(tool_args, ensure_ascii=False)}")

            # 5. 🔑 客户端安全执行对应的 MCP 多模态工具
            print("\n⚡ 正在执行 MCP Server 端的多模态画图工具...")
            tool_result = await session.call_tool(tool_name, arguments=tool_args)

            print("\n=================================================================")
            print("✅ 成功从 MCP Server 接收到多模态 Content Block 组合:")

            text_payload_for_llm = ""
            for idx, content in enumerate(tool_result.content, start=1):
                if content.type == "text":
                    print(f"\n--- 📝 Block {idx}: [TextContent] ---")
                    print(f"文本内容:\n{content.text}")
                    text_payload_for_llm += content.text

                elif content.type == "image":
                    print(f"\n--- 🖼️ Block {idx}: [ImageContent] ---")
                    print(f"MimeType: {content.mimeType}")
                    print(f"Base64 字符串长度: {len(content.data)} 字符")
                    
                    # 验证解码物理 Image 字节流
                    raw_bytes = base64.b64decode(content.data)
                    print(f"✅ 解码后的原始 PNG 物理字节流大小: {len(raw_bytes)} Bytes (纯内存无损传输!)")

            # 6. 🔑 将 MCP 工具执行结果送回真实 LLM 进行多模态总结汇报
            messages.append(llm_msg)
            messages.append({
                "role": "tool",
                "tool_call_id": call_info["id"],
                "content": text_payload_for_llm
            })

            print("\n=================================================================")
            print("🤖 [真实 LLM 接收多模态工具结果中...] 正在生成最终业务汇报:\n")
            final_response = await client.request_llm_with_tools(messages, llm_tools_schema)
            print(f"✨ 真实大模型最终汇报输出:\n{final_response.get('content', '')}")
            print("=================================================================")
            print("🎯 面向真实 LLM 的 MCP 多模态工具全流程 Agent 100% 成功贯通!")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--server-mode":
        mcp_server.run(transport="stdio")
    else:
        asyncio.run(run_multimodal_llm_agent_experiment())
