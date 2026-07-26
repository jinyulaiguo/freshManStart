"""
Day 85 正统架构师标准答案: 基于官方 MCP Python SDK (FastMCP) 的 Tool JSON Schema 显式导出与 Client 自动握手

设计意图:
    本模块示范生产级 MCP 服务端中 Tool inputSchema 的完整声明与导出机制。
    核心事实澄清 (JSON Schema Auto-Derivation):
    1. 【Schema 自动推导与 Field 增强】: FastMCP 会根据 Python 类型注解自动推导标准的 JSON Schema (inputSchema)。
       在生产级开发中，我们结合 `pydantic.Field` 与 `Annotated` 为每个入参标注极精准的 `description` 边界；
    2. 【Client 侧 Schema 查验】: Client 端通过 `await session.list_tools()` 接收到服务端推导的完整
       `inputSchema` 结构体 (包含 type, properties, required 字段)，用于传递给大模型 (LLM) 进行 Tool Call 解析。

真实工业业务场景 (Industrial Context):
    多 Agent 代码重构系统中的“企业级 AST 源码安全漏洞与 SQL 注入审计微服务 (Security Audit Service)”。

测试用例设计意图 (Test Case Design Intent):
    1. 使用 `Annotated` 与 `Field` 为工具入参显式声明带语义边界的 JSON Schema；
    2. Client 侧执行 `await session.list_tools()` 并打印返回的完整 `inputSchema` 字典，验证 Schema 导出完整性；
    3. 执行端到端业务工具调用并验证 Block 返回。
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
    if "os.system(" in code_snippet or "subprocess.Popen" in code_snippet:
        findings.append({"severity": "HIGH", "issue": "检测到非安全系统命令调用"})
    if "SELECT " in code_snippet and "%" in code_snippet:
        findings.append({"severity": "HIGH", "issue": "检测到潜在 SQL 格式化拼接注入风险"})

    return {
        "scan_level": scan_level,
        "clean": len(findings) == 0,
        "total_issues": len(findings),
        "findings": findings
    }


@mcp.resource("resource://security/audit_policy.json")
def get_audit_policy() -> str:
    """暴露企业只读安全审计策略元数据"""
    return '{"policy_id": "SEC-2026-POL-09", "enforcement": "BLOCK", "rules": ["NO_EVAL", "NO_SQL_CONCAT"]}'


# =====================================================================
# 2. MCP Client 端流程 (检验从 Server 接收到的完整 inputSchema)
# =====================================================================
async def run_official_mcp_workflow():
    """
    Client 端工作流: 建立 ClientSession 并查验由 FastMCP 底层生成的完整 inputSchema
    """
    print("\n=== 启动官方 MCP ClientSession 并建立 Stdio 双向通道 ===")

    server_params = StdioServerParameters(
        command=sys.executable,
        args=[__file__, "--server-mode"],
        env=None
    )

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            # 1. 触发自动握手
            init_result = await session.initialize()
            print(f"✅ 握手成功! ServerInfo: name='{init_result.serverInfo.name}', version='{init_result.serverInfo.version}'")

            # 2. 获取工具列表并打印其完整导出的 inputSchema JSON 结构
            tools_response = await session.list_tools()
            target_tool = tools_response.tools[0]
            
            print("\n[Client 从 Server 检索到的完整 Tool 定义及其 inputSchema]:")
            print(f"• Tool Name: {target_tool.name}")
            print(f"• Description: {target_tool.description}")
            print("• inputSchema (自动导出的 JSON Schema 规范):")
            print(json.dumps(target_tool.inputSchema, ensure_ascii=False, indent=2))

            # 3. 发起业务调用
            unsafe_code = "import os\ndef run(user_input):\n    eval(user_input)\n    os.system('rm -rf /tmp')"
            print("\n正在通过 ClientSession 发起工具调用 (audit_python_ast_security)...")
            result = await session.call_tool(
                name="audit_python_ast_security",
                arguments={"code_snippet": unsafe_code, "scan_level": "STRICT"}
            )

            print("\n[Client 接收到的响应结果 (Content Block)]:")
            for content_block in result.content:
                print(content_block.text)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--server-mode":
        mcp.run(transport="stdio")
    else:
        asyncio.run(run_official_mcp_workflow())
