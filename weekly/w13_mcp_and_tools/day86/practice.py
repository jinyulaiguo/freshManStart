"""
Day 86 练习模版: 基于 Python FastMCP SDK 开发 Resources, Prompts 与 Tools 生产级微服务

设计意图:
    本练习引导学员掌握生产级 FastMCP 中三大元实体的定义与 Client 端交互方法:
    1. 【RFC 6570 动态 URI 资源】: `@mcp.resource("audit://logs/{service_name}/{log_date}")` 路径参数解析；
    2. 【Context 依赖注入】: 在工具函数中注入 `ctx: Context` 并使用 `await ctx.info()` 安全输出日志；
    3. 【Prompts 交互模板】: `@mcp.prompt()` 导出参数化 Prompt 模板。

主入口测试用例设计意图 (Test Case Design Intent):
    引导学员使用 ClientSession 依次验证读取静态资源、RFC 6570 动态资源、获取 Prompt 模板与调用 Tool。
"""

import sys
import json
import asyncio
from typing import Dict, Any, Annotated

from pydantic import Field
from mcp.types import Annotations
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.server.fastmcp import FastMCP, Context

# =====================================================================
# 1. FastMCP 微服务服务端定义
# =====================================================================
mcp = FastMCP("cloud-audit-ops-server")


# --- 1a. 静态资源 ---
@mcp.resource(
    "config://app/audit_config.json",
    annotations=Annotations(readOnlyHint=True, priority=1.0)
)
def get_audit_config() -> str:
    """暴露企业只读运维审计配置文件"""
    return json.dumps({"environment": "production-us-east", "compliance_mode": "HIPAA_SOC2"}, ensure_ascii=False)


# --- 1b. 动态资源 (RFC 6570 Dynamic URI Template) ---
@mcp.resource("audit://logs/{service_name}/{log_date}")
def get_service_audit_log(service_name: str, log_date: str) -> str:
    """根据 RFC 6570 动态 URI 模板，从 URI 自动提取参数"""
    return json.dumps({
        "query_uri": f"audit://logs/{service_name}/{log_date}",
        "target_service": service_name,
        "date": log_date,
        "status": "HEALTHY"
    }, ensure_ascii=False)


# --- 2. 提示词模板 ---
@mcp.prompt(name="generate_security_summary_prompt")
def generate_security_summary_prompt(service_name: str, audit_depth: str = "DEEP") -> str:
    """导出带参数补全的标准化 Prompt 模板"""
    return f"请针对微服务 [{service_name}] 进行 [{audit_depth}] 级别的安全总结。"


# --- 3. 强契约工具 (Tools + Context 依赖注入) ---
@mcp.tool(name="get_system_metrics")
async def get_system_metrics(
    cluster_id: Annotated[str, Field(description="目标 Kubernetes 集群的物理 ID", min_length=3)],
    ctx: Context,
    include_network: Annotated[bool, Field(description="是否同时采集网络吞吐量指标")] = True
) -> Dict[str, Any]:
    """带有 Context 依赖注入的安全工具实现"""
    await ctx.info(f"正在从物理集群 [{cluster_id}] 采集实时监控指标...")
    return {"cluster_id": cluster_id, "cpu_usage_pct": 42.5, "disk_status": "NORMAL"}


# =====================================================================
# 2. MCP Client 端流程
# =====================================================================
async def run_mcp_client_test():
    """Client 端全套三类元实体验证流程"""
    print("\n=== 启动官方 MCP ClientSession 连接 Day 86 微服务 ===")

    server_params = StdioServerParameters(
        command=sys.executable,
        args=[__file__, "--server-mode"],
        env=None
    )

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            # TODO: 学员需在此实现:
            # 1. await session.initialize() 握手；
            # 2. await session.read_resource("config://app/audit_config.json") 读取静态资源；
            # 3. await session.read_resource("audit://logs/payment-service/2026-07-26") 测试 RFC 6570 动态资源；
            # 4. await session.get_prompt("generate_security_summary_prompt", ...) 获取 Prompt 模板；
            # 5. await session.call_tool("get_system_metrics", ...) 调用带 Context 的工具。
            raise NotImplementedError("TODO: 请在 run_mcp_client_test 中使用 ClientSession 验证全套三类元实体")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--server-mode":
        mcp.run(transport="stdio")
    else:
        try:
            asyncio.run(run_mcp_client_test())
        except (NotImplementedError, BaseExceptionGroup) as e:
            print("⚠️ 拦截到未实现提示:", e)
            print("请打开 practice.py 完成 TODO 部分的代码实现。")
