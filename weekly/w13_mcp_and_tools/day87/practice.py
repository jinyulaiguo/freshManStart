"""
Day 87 练习模版: MCP 客户端接入、LangGraph 多工具反射绑定与 Client Sampling 反向采样

设计意图:
    本练习引导学员掌握 LangGraph Client 接入 MCP 服务的两大关键架构:
    1. 【MCP 工具反射】: 编写 MCPReflectionAdapter 将 ClientSession.list_tools() 结果反射包装为 LangChain StructuredTool；
    2. 【Client Sampling 响应】: 编写 Client 侧 sampling_callback 句柄，响应来自 Server 的 ctx.session.create_message() 请求。

主入口测试用例设计意图 (Test Case Design Intent):
    1. 启动并建立 ClientSession 管道；
    2. 验证反射适配器将 MCP 工具转化为 LangGraph StructuredTool 实体；
    3. 在 LangGraph 环境中触发工具执行并全流程验证 Sampling 反向借脑。
"""

import sys
import json
import asyncio
from typing import Dict, Any, List

from pydantic import create_model
from langchain_core.tools import StructuredTool

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import (
    CreateMessageRequestParams,
    CreateMessageResult,
    TextContent,
    SamplingMessage,
    ModelPreferences
)
from mcp.server.fastmcp import FastMCP, Context

# =====================================================================
# 1. MCP Server 端定义 (带 Sampling 采样需求)
# =====================================================================
mcp_server = FastMCP("code-refactor-server")


@mcp_server.tool(name="analyze_code_debt")
async def analyze_code_debt(code_content: str, ctx: Context) -> Dict[str, Any]:
    """服务端代码债务分析工具：内部触发 Sampling 向 Client 借脑"""
    await ctx.info("正在分析 Python 代码结构...")
    sampling_prompt = f"请简要总结以下 Python 代码的核心功能:\n{code_content}"
    
    # 触发 Sampling 请求
    sample_response = await ctx.session.create_message(
        messages=[SamplingMessage(role="user", content=TextContent(type="text", text=sampling_prompt))],
        max_tokens=150
    )
    return {"lines": len(code_content.splitlines()), "client_summary": sample_response.content.text}


# =====================================================================
# 2. MCP 到 LangGraph 工具反射适配器
# =====================================================================
class MCPReflectionAdapter:
    """
    生产级 MCP 工具反射适配器
    """
    @staticmethod
    def to_langchain_tool(session: ClientSession, mcp_tool_descriptor) -> StructuredTool:
        """将单个 MCP Tool 描述结构反射封装为 LangChain StructuredTool"""
        # TODO: 学员需在此实现:
        # 1. 解析 mcp_tool_descriptor 的 name, description, inputSchema；
        # 2. 动态创建 Pydantic Schema 参数模型；
        # 3. 构造异步执行逻辑: await session.call_tool(tool_name, arguments=kwargs)；
        # 4. 返回 StructuredTool.from_function 实例。
        raise NotImplementedError("TODO: 请实现 MCPReflectionAdapter.to_langchain_tool 工具反射逻辑")


# =====================================================================
# 3. Client 侧 Sampling 反向采样句柄
# =====================================================================
async def handle_client_sampling_request(*args, **kwargs) -> CreateMessageResult:
    """Client 侧注册的 Sampling 采样句柄"""
    # TODO: 学员需在此实现:
    # 1. 从 args/kwargs 提取 CreateMessageRequestParams 参数；
    # 2. 从消息中提取 Server 提问内容；
    # 3. 调用本地/模拟 LLM 大脑生成回答；
    # 4. 返回 CreateMessageResult 结构体。
    raise NotImplementedError("TODO: 请实现 Client 侧 handle_client_sampling_request 采样处理句柄")


# =====================================================================
# 4. 端到端 LangGraph 挂载与全流程验证
# =====================================================================
async def run_langgraph_mcp_integration():
    """Client 端 LangGraph 工具挂载与 Sampling 全流程测试"""
    print("=== 启动 Day 87: LangGraph MCP 反射挂载与 Sampling 借脑集成测试 ===")

    server_params = StdioServerParameters(
        command=sys.executable,
        args=[__file__, "--server-mode"],
        env=None
    )

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(
            read_stream,
            write_stream,
            sampling_callback=handle_client_sampling_request
        ) as session:
            await session.initialize()
            print("✅ ClientSession 自动握手成功!")

            mcp_tools_resp = await session.list_tools()
            lg_tool = MCPReflectionAdapter.to_langchain_tool(session, mcp_tools_resp.tools[0])

            print(f"\n反射转换为 LangGraph 工具: {lg_tool.name}")
            res = await lg_tool.ainvoke({"code_content": "print('hello')"})
            print("工具运行结果:", res)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--server-mode":
        mcp_server.run(transport="stdio")
    else:
        try:
            asyncio.run(run_langgraph_mcp_integration())
        except (NotImplementedError, BaseExceptionGroup) as e:
            print("⚠️ 拦截到未实现提示:", e)
            print("请打开 practice.py 完成 TODO 部分的代码实现。")
