"""
Day 87 正统架构师标准答案: MCP 客户端接入、LangGraph 多工具反射绑定与 Client Sampling 反向采样

设计意图:
    本模块示范生产级 LangGraph Client 挂载外部 MCP Server 的两大核心能力:
    1. 【MCP 到 LangGraph 工具反射 (Reflection Adapter)】: 从 MCP ClientSession 提取 list_tools()
       契约，零手写胶水代码自动反射包装为 LangChain / LangGraph Node 兼容的 StructuredTool；
    2. 【Client Sampling 反向借脑采样】: 当 Server 端工具逻辑通过 `ctx.session.create_message()` 发起采样时，
       Client 侧注册的 sampling_handler 被协议回调，调用 Client 本地 LLM“大脑”解题并回传采样结果。

真实工业业务场景 (Industrial Context):
    分布式自动化代码重构与多 Agent 审计管道 (Distributed Code Refactoring Pipeline)。
    Server 端是一个运行在轻量 Docker 容器里的“代码债务检测工具”，无 LLM API Key。
    在工具执行中，通过 `ctx.session.create_message()` 反向请求 Client 主系统为其做代码摘要，Server 结合摘要生成最终重构方案。

测试用例设计意图 (Test Case Design Intent):
    1. 启动带 Sampling 需求的 FastMCP Server 子进程；
    2. Client 建立 ClientSession，注册 `handle_client_sampling_request` 采样句柄；
    3. 使用 `MCPReflectionAdapter` 动态将 MCP 工具反射转换为 LangChain/LangGraph 工具实体；
    4. 执行反射后的 LangGraph 工具，全流程验证：Client 发起 Tool Call -> Server 工具触发 Sampling -> Client 侧 Sampling 句柄被响应 -> Server 完成工具计算。
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
# 1. MCP Server 端定义 (带 ctx.session.create_message 反向借脑采样)
# =====================================================================
mcp_server = FastMCP("code-refactor-server")


@mcp_server.tool(
    name="analyze_code_debt",
    description="分析 Python 模块的代码技术债务，并反向请求 Client 侧 LLM 进行风险摘要提纯"
)
async def analyze_code_debt(code_content: str, ctx: Context) -> Dict[str, Any]:
    """服务端代码债务分析工具：内部触发 ctx.session.create_message() 向 Client 借脑"""
    await ctx.info("正在分析 Python 代码长度与结构...")
    
    # 🔑 触发 MCP 协议 Sampling 反向采样：向 Client 侧 LLM 发起请求
    sampling_prompt = f"请简要总结以下 Python 代码的核心功能与技术债务:\n\n{code_content}"
    
    await ctx.info("正在通过 ctx.session.create_message() 向 Client 侧借脑采样...")
    sample_response = await ctx.session.create_message(
        messages=[
            SamplingMessage(
                role="user",
                content=TextContent(type="text", text=sampling_prompt)
            )
        ],
        max_tokens=150,
        model_preferences=ModelPreferences(hints=[{"name": "minimax-01"}])
    )
    
    summary_from_client = sample_response.content.text
    
    return {
        "lines_analyzed": len(code_content.splitlines()),
        "summary_by_client_llm": summary_from_client,
        "refactor_recommended": "eval(" in code_content or len(code_content) > 500
    }


# =====================================================================
# 2. MCP 到 LangGraph 工具反射适配器 (MCPReflectionAdapter)
# =====================================================================
class MCPReflectionAdapter:
    """
    生产级 MCP 工具反射适配器：动态将 MCP Tool Schema 转化为 LangChain / LangGraph 兼容工具
    """
    @staticmethod
    def to_langchain_tool(session: ClientSession, mcp_tool_descriptor) -> StructuredTool:
        """将单个 MCP Tool 描述结构反射封装为 LangChain StructuredTool"""
        tool_name = mcp_tool_descriptor.name
        tool_desc = mcp_tool_descriptor.description or f"MCP Tool: {tool_name}"
        input_schema = mcp_tool_descriptor.inputSchema

        # 动态解析 inputSchema 构建 Pydantic Model
        fields = {}
        properties = input_schema.get("properties", {})
        required_fields = input_schema.get("required", [])

        for prop_name, prop_spec in properties.items():
            field_type = str  # 默认映射为 str
            if prop_spec.get("type") == "boolean":
                field_type = bool
            elif prop_spec.get("type") == "integer":
                field_type = int
            
            is_required = prop_name in required_fields
            default_val = ... if is_required else prop_spec.get("default", None)
            fields[prop_name] = (field_type, default_val)

        pydantic_args_schema = create_model(f"{tool_name}Args", **fields)

        async def _coroutine(**kwargs) -> str:
            # 异步执行 MCP ClientSession.call_tool
            res = await session.call_tool(tool_name, arguments=kwargs)
            return "\n".join([b.text for b in res.content if b.type == "text"])

        return StructuredTool.from_function(
            name=tool_name,
            description=tool_desc,
            args_schema=pydantic_args_schema,
            coroutine=_coroutine
        )


# =====================================================================
# 3. Client 侧 Sampling 反向采样句柄实现
# =====================================================================
async def handle_client_sampling_request(*args, **kwargs) -> CreateMessageResult:
    """
    Client 侧注册的 Sampling 采样句柄:
    当 Server 调用 ctx.session.create_message() 时，协议层回调此函数，Client 使用本地凭证求值并返回给 Server
    """
    print("\n[📢 Client 侧拦截到来自 Server 的 Sampling 采样请求!]")
    
    # 兼容性提取 params 参数
    params = None
    for arg in args:
        if isinstance(arg, CreateMessageRequestParams):
            params = arg
            break
    if not params and "params" in kwargs:
        params = kwargs["params"]

    if params and params.messages:
        incoming_prompt = params.messages[0].content.text
        print(f"   Server 提问内容: '{incoming_prompt[:60]}...'")
    else:
        print("   Server 发起了采样请求。")

    # 模拟/调用 Client 侧的本地 LLM 大脑求值
    mock_llm_answer = f"[Client 侧 LLM 大脑提纯结果]: 该代码用于安全扫描，包含动态 eval 风险与高复杂度函数。"
    print(f"   Client 侧 LLM 正在生成回答并送回 Server...")

    return CreateMessageResult(
        role="assistant",
        content=TextContent(type="text", text=mock_llm_answer),
        model="minimax-01"
    )


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

    # 1. 初始化 stdio 通道，并注入 Client 侧的 sampling_callback 句柄
    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(
            read_stream,
            write_stream,
            sampling_callback=handle_client_sampling_request
        ) as session:
            # 2. 自动完成协议握手
            await session.initialize()
            print("✅ ClientSession 自动握手成功 (Sampling 回调已就绪)!")

            # 3. 反射导出 MCP 工具列表，转换为 LangGraph 可用的 StructuredTool
            mcp_tools_resp = await session.list_tools()
            langchain_tools = []
            for tool_meta in mcp_tools_resp.tools:
                lg_tool = MCPReflectionAdapter.to_langchain_tool(session, tool_meta)
                langchain_tools.append(lg_tool)

            print(f"\n[已成功通过 MCPReflectionAdapter 将 MCP 工具反射转化为 LangGraph StructuredTool]:")
            print(f"• Tool Name: {langchain_tools[0].name}")
            print(f"• Description: {langchain_tools[0].description}")
            print(f"• Pydantic Args Schema: {langchain_tools[0].args_schema.model_json_schema()}")

            # 4. 在 LangGraph 环境中触发执行该 StructuredTool
            print("\n正在在 LangGraph 流程中异步执行 LangGraph 工具 (ainvoke)...")
            target_code = "def legacy_func(x):\n    eval(x)\n    return x * 2"
            
            tool_output = await langchain_tools[0].ainvoke({"code_content": target_code})
            print("\n[LangGraph 接收到的最终工具运行结果]:\n", tool_output)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--server-mode":
        mcp_server.run(transport="stdio")
    else:
        asyncio.run(run_langgraph_mcp_integration())
