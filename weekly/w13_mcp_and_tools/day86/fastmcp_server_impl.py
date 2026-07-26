"""
Day 86 正统架构师标准答案: 基于 Python FastMCP SDK 开发 Resources, Prompts 与 Tools 生产级微服务

设计意图:
    本模块示范生产级 FastMCP 中三大元实体 (Resources, Prompts, Tools) 的标准声明范式:
    1. 【RFC 6570 动态 URI 资源】: 利用 `@mcp.resource("audit://logs/{service_name}/{log_date}")` 演示路径参数自动解析；
    2. 【Context 依赖注入】: 在 Tool 处理函数中依赖注入 `ctx: Context`，体验 `await ctx.info(...)` 安全日志，杜绝 `print()` 损坏 Stdio 帧；
    3. 【Prompts 交互模板】: 利用 `@mcp.prompt()` 导出参数化的标准化提示词模板；
    4. 【Annotations 元数据】: 显式标注 `readOnlyHint=True` 提高客户端安全性。

真实工业业务场景 (Industrial Context):
    企业级云原生应用审计与运维监控微服务 (Cloud Native Audit & Operations Service)。

测试用例设计意图 (Test Case Design Intent):
    1. Client 侧初始化握手，验证三大元实体在 Server 端的集中暴露；
    2. 端到端测试读取静态与 RFC 6570 动态资源，验证 URI 模板参数自动提取；
    3. 检索 Prompt 模板与调用带 Context 日志的运维工具。
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


# --- 1a. 静态资源 (Static Resource) ---
@mcp.resource(
    "config://app/audit_config.json",
    annotations=Annotations(readOnlyHint=True, priority=1.0)
)
def get_audit_config() -> str:
    """暴露企业只读运维审计配置文件"""
    return json.dumps({
        "environment": "production-us-east",
        "retention_days": 90,
        "compliance_mode": "HIPAA_SOC2"
    }, ensure_ascii=False)


# --- 1b. 动态资源 (RFC 6570 Dynamic URI Template Resource) ---
@mcp.resource("audit://logs/{service_name}/{log_date}")
def get_service_audit_log(service_name: str, log_date: str) -> str:
    """根据 RFC 6570 动态 URI 模板，从 URI 自动提取 service_name 和 log_date 参数"""
    return json.dumps({
        "query_uri": f"audit://logs/{service_name}/{log_date}",
        "target_service": service_name,
        "date": log_date,
        "status": "HEALTHY",
        "log_entries": [
            f"[{log_date} 10:00:00] {service_name} 实例初始化完成 (replica=3)",
            f"[{log_date} 10:05:22] {service_name} 执行了零信任 Token 刷新"
        ]
    }, ensure_ascii=False)


# --- 2. 提示词模板 (Prompts) ---
@mcp.prompt(
    name="generate_security_summary_prompt",
    description="生成微服务安全审计报告的标准提示词模板"
)
def generate_security_summary_prompt(service_name: str, audit_depth: str = "DEEP") -> str:
    """导出带参数补全的标准化 Prompt 模板"""
    return f"""你是一位高级云原生安全专家。
请针对微服务 [{service_name}] 进行 [{audit_depth}] 级别的安全漏洞与监控数据总结。
要求:
1. 评估系统的整体健康度状态；
2. 提取潜在的异常入侵或高延时瓶颈；
3. 输出三条具体的架构优化建议。"""


# --- 3. 强契约工具 (Tools + Context 依赖注入) ---
@mcp.tool(
    name="get_system_metrics",
    description="获取指定微服务集群的系统 CPU、内存与磁盘 I/O 监控指标"
)
async def get_system_metrics(
    cluster_id: Annotated[
        str,
        Field(description="目标 Kubernetes 集群的物理 ID (如 cls-prod-01)", min_length=3)
    ],
    ctx: Context,
    include_network: Annotated[bool, Field(description="是否同时采集网络吞吐量指标")] = True
) -> Dict[str, Any]:
    """带有 Context 依赖注入的安全工具实现"""
    # 🔴 生产防护：使用 ctx.info 输出日志，绝不使用 print() 污染 stdout 管道
    await ctx.info(f"正在从物理集群 [{cluster_id}] 采集实时监控指标 (include_network={include_network})...")

    metrics = {
        "cluster_id": cluster_id,
        "cpu_usage_pct": 42.5,
        "memory_used_gb": 64.2,
        "memory_total_gb": 128.0,
        "disk_status": "NORMAL"
    }

    if include_network:
        metrics["network_rx_mbps"] = 120.5
        metrics["network_tx_mbps"] = 450.8

    await ctx.info(f"集群 [{cluster_id}] 指标采集完毕。")
    return metrics


# =====================================================================
# 2. MCP Client 端流程 (端到端测试全套三类元实体)
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
            # 1. 自动握手
            init_res = await session.initialize()
            print(f"✅ 握手成功! 微服务名称: '{init_res.serverInfo.name}'")

            # 2. 验证静态与 RFC 6570 动态资源读取
            print("\n[测试 1: 读取静态资源 config://app/audit_config.json]:")
            cfg_res = await session.read_resource("config://app/audit_config.json")
            print(cfg_res.contents[0].text)

            print("\n[测试 2: 读取 RFC 6570 动态资源 audit://logs/payment-service/2026-07-26]:")
            log_res = await session.read_resource("audit://logs/payment-service/2026-07-26")
            print(log_res.contents[0].text)

            # 3. 验证检索 Prompt 模板
            print("\n[测试 3: 检索 Prompt 模板 generate_security_summary_prompt]:")
            prompt_res = await session.get_prompt(
                "generate_security_summary_prompt",
                arguments={"service_name": "payment-service", "audit_depth": "DEEP"}
            )
            print("导出的 Prompt 内容:\n", prompt_res.messages[0].content.text)

            # 4. 验证调用带有 Context 安全日志的 Tool
            print("\n[测试 4: 调用带 Context 依赖注入的工具 get_system_metrics]:")
            tool_res = await session.call_tool(
                "get_system_metrics",
                arguments={"cluster_id": "cls-prod-01", "include_network": True}
            )
            print("工具响应结果:\n", tool_res.content[0].text)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--server-mode":
        mcp.run(transport="stdio")
    else:
        asyncio.run(run_mcp_client_test())
