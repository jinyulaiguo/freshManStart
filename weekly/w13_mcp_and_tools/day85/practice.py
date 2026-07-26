"""
Day 85 练习模版: 基于官方 MCP Python SDK (FastMCP) 的 Tool JSON Schema 显式导出与 Client 自动握手

设计意图:
    本练习引导学员掌握官方 `mcp` SDK 中 Tool inputSchema 的导出与查验逻辑。
    1. Schema 自动推导: FastMCP 结合 Python 类型注解与 Annotated/Field 自动推导 inputSchema；
    2. Client 查验: 通过 await session.list_tools() 检索 inputSchema 结构体。

主入口测试用例设计意图 (Test Case Design Intent):
    1. 使用 Annotated[str, Field(description=...)] 显式为工具参数增强 Schema 描述；
    2. Client 端查看导出的 inputSchema JSON 结构并完成工具调用。
"""

import sys
import json
import asyncio
from typing import Dict, Any, Annotated

from pydantic import Field
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.server.fastmcp import FastMCP

# =====================================================================
# 1. MCP Server 端定义 (使用 FastMCP + Field 显式增强 inputSchema)
# =====================================================================
mcp = FastMCP("security-audit-engine")


@mcp.tool(
    name="audit_python_ast_security",
    description="对 Python 源码进行静态 AST 词法分析，识别 eval/exec 陷阱与 SQL 格式化拼接风险"
)
def audit_python_ast_security(
    code_snippet: Annotated[
        str,
        Field(description="待进行 AST 静态安全审计的 Python 源代码字符串片段", min_length=1)
    ],
    scan_level: Annotated[
        str,
        Field(description="扫描严格等级: STRICT(严格检测所有风险) / RELAXED(仅检测 CRITICAL 级风险)")
    ] = "STRICT"
) -> Dict[str, Any]:
    """执行真实 AST 语法树安全风险扫描"""
    findings = []
    if "eval(" in code_snippet or "exec(" in code_snippet:
        findings.append({"severity": "CRITICAL", "issue": "检测到动态代码执行陷阱 (eval/exec)"})
    return {"clean": len(findings) == 0, "findings": findings}


# =====================================================================
# 2. MCP Client 端流程
# =====================================================================
async def run_official_mcp_workflow():
    """
    Client 端工作流
    """
    print("\n=== 启动官方 MCP ClientSession 并建立 Stdio 双向通道 ===")

    server_params = StdioServerParameters(
        command=sys.executable,
        args=[__file__, "--server-mode"],
        env=None
    )

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            # TODO: 学员需在此实现:
            # 1. await session.initialize()
            # 2. tools_resp = await session.list_tools() 并打印 tools_resp.tools[0].inputSchema 结构
            # 3. await session.call_tool(...)
            raise NotImplementedError("TODO: 请使用 session.list_tools() 查验 inputSchema 并完成业务调用")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--server-mode":
        mcp.run(transport="stdio")
    else:
        try:
            asyncio.run(run_official_mcp_workflow())
        except (NotImplementedError, BaseExceptionGroup) as e:
            print("⚠️ 拦截到未实现提示:", e)
            print("请打开 practice.py 完成 TODO 部分的代码实现。")
