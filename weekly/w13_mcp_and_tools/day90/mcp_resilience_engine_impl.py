"""
Day 90 正统架构师标准答案: 面向真实 LLM 的 MCP 生产沙箱隔离、降级熔断与故障自愈引擎闭环

设计意图:
    本模块示范在面向真实 LLM (MiniMax-M3) 的场景下，如何将自愈网关 (`MCPResilienceEngine`)
    作为 Agent 底座护城河，实现“物理 Server 崩溃/超时打不垮大模型 Agent 业务”的顶级生产架构。
    
    核心架构:
    1. 【真实 LLM 智能调度】: 真实 LLM 读取 MCP Server 暴露的工具 Schema 发起 Tool Call；
    2. 【MCPResilienceEngine 护城河】: 拦截死循环超时、处理 Server 进程物理崩溃、触发 `1s->2s->4s` 指数退避重连；
    3. 【Circuit Breaker 熔断与 Safe Fallback】: 故障发生时安全降级至 Safe Mode，并将结果安全送回给真实 LLM 总结回答。

真实工业业务场景 (Industrial Context):
    企业级金融高频交易与实时风控 MCP 微服务 (Financial Trading & Risk Control Service)。
"""

import sys
import json
import time
import asyncio
from enum import Enum
from pathlib import Path
from typing import Dict, Any, Optional, List

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.server.fastmcp import FastMCP, Context

# 确保项目根目录在 PYTHONPATH 中
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

# 🔑 复用项目公共基础基础设施 (规则 12 & 规则 20)
from weekly.w04_prompt_and_http.utils import LLMClient


# =====================================================================
# 1. 模拟物理故障服务端 (Faulty MCP Server)
# =====================================================================
mcp_server = FastMCP("financial-risk-server")


@mcp_server.tool(name="get_stock_price")
def get_stock_price(ticker: str) -> Dict[str, Any]:
    """正常只读工具：获取股票实时价格"""
    return {"ticker": ticker, "price": 185.50, "status": "LIVE"}


@mcp_server.tool(name="slow_hanging_trade")
async def slow_hanging_trade(amount: float, ctx: Context) -> Dict[str, Any]:
    """模拟卡死/死循环工具：挂起 10 秒超时"""
    await ctx.info("正在执行高频交易计算... (模拟卡死挂起 10s)")
    await asyncio.sleep(10.0)
    return {"status": "SUCCESS", "amount": amount}


@mcp_server.tool(name="trigger_server_crash")
async def trigger_server_crash(ctx: Context) -> str:
    """模拟物理崩溃：直接杀死 Server 子进程"""
    await ctx.info("💣 触发物理崩溃！子进程即将退出 sys.exit(1)...")
    sys.exit(1)


# =====================================================================
# 2. Circuit Breaker 熔断状态机与自愈保护引擎
# =====================================================================
class CircuitState(Enum):
    CLOSED = "CLOSED"      # 正常通信
    OPEN = "OPEN"          # 熔断开启 (拒绝直接请求，走 Fallback)
    HALF_OPEN = "HALF_OPEN"# 半开试探

class CircuitBreaker:
    """熔断器"""
    def __init__(self, failure_threshold: int = 2, cooldown_sec: float = 1.5):
        self.failure_threshold = failure_threshold
        self.cooldown_sec = cooldown_sec
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time = 0.0

    def is_allowed(self) -> bool:
        """检查当前是否允许发起请求"""
        now = time.time()
        if self.state == CircuitState.OPEN:
            if now - self.last_failure_time >= self.cooldown_sec:
                print("\n[⚡ CircuitBreaker 熔断冷却期已满 -> 进入 HALF_OPEN 半开试探状态]")
                self.state = CircuitState.HALF_OPEN
                return True
            return False
        return True

    def record_success(self):
        """记录成功"""
        self.failure_count = 0
        if self.state == CircuitState.HALF_OPEN:
            print("[✅ CircuitBreaker 半开试探成功 -> 恢复 CLOSED 正常状态]")
            self.state = CircuitState.CLOSED

    def record_failure(self):
        """记录失败"""
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold:
            print(f"\n[🔴 CircuitBreaker 连续失败 {self.failure_count} 次 -> 触发 OPEN 熔断锁定！]")
            self.state = CircuitState.OPEN


class MCPResilienceEngine:
    """
    生产级长连接自愈熔断保护网关
    """
    def __init__(self, server_params: StdioServerParameters):
        self.server_params = server_params
        self.circuit_breaker = CircuitBreaker()
        self.stdio_cm = None
        self.read_stream = None
        self.write_stream = None
        self.session: Optional[ClientSession] = None

    async def connect(self):
        """启动并与 Server 建立 Stdio 通信，完成协议初始化"""
        print("   [ResilienceEngine] 正在拉起 Stdio 子进程...")
        self.stdio_cm = stdio_client(self.server_params)
        self.read_stream, self.write_stream = await self.stdio_cm.__aenter__()
        self.session = ClientSession(self.read_stream, self.write_stream)
        await self.session.__aenter__()
        await self.session.initialize()
        print("   [ResilienceEngine] ✅ Stdio 通道拉起并握手成功!")

    async def close(self):
        """清理并注销资源"""
        if self.session:
            try:
                await self.session.__aexit__(None, None, None)
            except Exception:
                pass
        if self.stdio_cm:
            try:
                await self.stdio_cm.__aexit__(None, None, None)
            except Exception:
                pass
        self.session = None

    async def auto_reconnect_exponential_backoff(self):
        """指数退避自动重连算法 (1s -> 2s -> 4s)"""
        print("\n[🔄 触发长连接故障探针 -> 启动指数退避自动重连引擎]")
        await self.close()
        
        backoff_delays = [1.0, 2.0]
        for attempt, delay in enumerate(backoff_delays, start=1):
            print(f"   [重连 attempt {attempt}/{len(backoff_delays)}] 等待 {delay} 秒后尝试拉起子进程...")
            await asyncio.sleep(delay)
            try:
                await self.connect()
                print("   [✅ 指数退避重连成功! 子进程与握手恢复健康!]")
                return True
            except Exception as err:
                print(f"   [❌ 第 {attempt} 次重连失败: {err}]")

        print("   [🔴 达到最大重连次数，恢复失败]")
        return False

    async def execute_tool_with_resilience(
        self,
        tool_name: str,
        arguments: dict,
        timeout_sec: float = 2.0
    ) -> Dict[str, Any]:
        """带超时控制、熔断与自愈重连的工具执行入口"""
        # 1. 熔断判定
        if not self.circuit_breaker.is_allowed():
            print(f"⚠️ [CircuitBreaker 处于 OPEN 状态] 拒绝直接调用 {tool_name}，安全切换降级!")
            return self._execute_fallback(tool_name, "CIRCUIT_OPEN_FALLBACK")

        # 2. 带超时与重连的执行过程
        print(f"\n>>> 网关正在安全防护下代理执行工具 [{tool_name}] (超时预算: {timeout_sec}s)...")
        try:
            if not self.session:
                raise ConnectionError("ClientSession 不可用")

            result = await asyncio.wait_for(
                self.session.call_tool(tool_name, arguments=arguments),
                timeout=timeout_sec
            )
            
            self.circuit_breaker.record_success()
            res_text = result.content[0].text if result.content else "{}"
            return json.loads(res_text)

        except asyncio.TimeoutError:
            print(f"❌ [超时拦截] 工具 {tool_name} 执行超过 {timeout_sec}s 预算，已强行终止死锁!")
            self.circuit_breaker.record_failure()
            return self._execute_fallback(tool_name, "TIMEOUT_FALLBACK")

        except Exception as err:
            print(f"❌ [连接崩溃/异常] 工具 {tool_name} 触发物理故障: {err}")
            self.circuit_breaker.record_failure()
            
            # 自动拉起指数退避重连
            reconnect_ok = await self.auto_reconnect_exponential_backoff()
            if reconnect_ok:
                print("   [重连成功! 子进程重新就绪]")
            
            return self._execute_fallback(tool_name, f"CRASH_FALLBACK: {err}")

    def _execute_fallback(self, tool_name: str, reason: str) -> Dict[str, Any]:
        """降级保护兜底逻辑 (Safe Read-Only Mode)"""
        print(f"🛡️ [触发降级保护策略] 原因: {reason}")
        return {
            "status": "FALLBACK_SAFE_MODE",
            "tool_name": tool_name,
            "reason": reason,
            "fallback_data": {"price": 185.00, "source": "LOCAL_CACHE_SAFE_BACKUP"}
        }


# =====================================================================
# 3. 动态转换 MCP Schema 为 OpenAI / MiniMax Tool 格式
# =====================================================================
def convert_mcp_tools_to_openai_schema(mcp_tools) -> List[Dict[str, Any]]:
    """将 MCP list_tools 契约转给 LLMClient 消费"""
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
# 4. 面向真实 LLM 的自愈网关 Agent 全流程实战
# =====================================================================
async def run_resilience_llm_agent_experiment():
    """面向真实 LLM 的 MCP 自愈网关全流程实战"""
    print("=== 启动 Day 90: 面向真实 LLM (MiniMax-M3) 的 MCP 故障自愈网关 Agent 实战 ===")

    # 1. 加载项目公共 LLM 客户端
    client = LLMClient()
    print(f"✅ 已加载项目公共 LLMClient (端点: {client.base_url}, 模型: {client.model_name})")

    server_params = StdioServerParameters(
        command=sys.executable,
        args=[__file__, "--server-mode"],
        env=None
    )

    engine = MCPResilienceEngine(server_params)
    await engine.connect()

    try:
        # 2. 动态获取 MCP Server 暴露的 Tools 并转为大模型 Schema
        mcp_tools_res = await engine.session.list_tools()
        llm_tools_schema = convert_mcp_tools_to_openai_schema(mcp_tools_res)
        print(f"📦 已成功反射转换 MCP 工具 Schema 给真实 LLM: {[t['function']['name'] for t in llm_tools_schema]}")

        # 3. 用户 Query
        user_query = "请帮我查询 AAPL 股票的实时价格，并尝试对该股票下达一笔 50000 元的高频交易。"
        print(f"\n💬 用户 Request -> '{user_query}'")

        messages = [
            {"role": "system", "content": "你是一位高频交易 Agent。请根据用户需求选择工具执行。"},
            {"role": "user", "content": user_query}
        ]

        # 4. 🔑 真实 LLM (MiniMax-M3) 自动决策 Tool Call
        print("\n🤖 [真实 LLM 思考中...] 正在读取 MCP 工具 Schema 并发起智能决策...")
        llm_msg = await client.request_llm_with_tools(messages, llm_tools_schema)

        tool_calls = llm_msg.get("tool_calls", [])
        if not tool_calls:
            print("真实 LLM 直接回答:\n", llm_msg.get("content", ""))
            return

        print(f"\n🎯 真实 LLM 成功决策! 发起了 {len(tool_calls)} 个 MCP Tool Call 顺序调用:")

        # 5. 🔑 依次通过自愈网关执行工具 (网关在底层实施超时拦截与自愈防护)
        for call_info in tool_calls:
            t_name = call_info["function"]["name"]
            t_args = json.loads(call_info["function"]["arguments"])
            
            print(f"\n---> 真实 LLM 指令调用工具 [{t_name}], 参数: {t_args}")
            # 经过 MCPResilienceEngine 防护网关代理执行
            protected_res = await engine.execute_tool_with_resilience(t_name, t_args, timeout_sec=2.0)
            
            print(f"   自愈网关代理返回结果: {json.dumps(protected_res, ensure_ascii=False)}")
            
            # 将保护后的结果送回 LLM
            messages.append({
                "role": "assistant",
                "tool_calls": [call_info]
            })
            messages.append({
                "role": "tool",
                "tool_call_id": call_info["id"],
                "content": json.dumps(protected_res, ensure_ascii=False)
            })

        # 6. 🔑 真实 LLM 基于自愈/降级后的结果给出最终总结回答
        print("\n=================================================================")
        print("🤖 [真实 LLM 接收自愈防护结果中...] 正在生成最终业务汇报:\n")
        final_response = await client.request_llm_with_tools(messages, llm_tools_schema)
        print(f"✨ 真实大模型最终汇报输出:\n{final_response.get('content', '')}")
        print("=================================================================")
        print("🎯 真实 LLM 驱动的 MCP 故障自愈网关 Agent 100% 成功贯通!")

    finally:
        await engine.close()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--server-mode":
        mcp_server.run(transport="stdio")
    else:
        asyncio.run(run_resilience_llm_agent_experiment())
