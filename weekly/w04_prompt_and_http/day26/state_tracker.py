"""
Week 4 Day 26 参考答案：HTTPX 连接池优化与 HTTP 异常工程

设计方案：
1. 设计意图：
   在高并发 Agent 调用大模型时，通过长生命周期托管单一 HTTPX 异步连接池，
   消除频繁 TCP/TLS 握手导致的端口枯竭与性能开销。
   同时，构建带指数退避和 Jitter 随机抖动重试的强壮异常处理工程。

2. 类与函数结构：
   - 包含工程级 sys.path 自动寻址补丁逻辑。
   - `PooledLLMClient`: 连接池化大模型客户端。
     - `__init__()`: 初始化四维超时与池大小。
     - `close()`: 关闭异步连接池。
     - `request_with_retry()`: 指数退避与随机抖动重试控制逻辑。

3. 关键数据流向：
   并发请求 ──> PooledLLMClient.request_with_retry() ──> 
   向 client_pool 申请可用保活链接 ──> 网络请求 ──> 捕获 Timeout/429 异常 ──> 指数退避与随机抖动 ──> 重新请求 ──> 返回数据
"""

import sys
import os
import re
import asyncio
import random
import time
import httpx

# =====================================================================
# 防御性 sys.path 补丁逻辑 (多策略寻址注入)
# =====================================================================
current_dir = os.path.dirname(os.path.realpath(__file__))
root_dir = os.path.abspath(os.path.join(current_dir, "../../.."))

if os.getcwd() not in sys.path:
    sys.path.insert(0, os.getcwd())
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

# 导入公共工具基类中的环境变量加载
from weekly.w04_prompt_and_http.utils import load_env_file

# 加载配置
load_env_file()


# =====================================================================
# 核心架构与连接池请求引擎实现
# =====================================================================

class PooledLLMClient:
    """带连接池和指数退避重试的高性能 LLM 异步请求客户端"""

    def __init__(self, max_connections: int = 50, max_keepalive: int = 20, timeout_cfg: dict = None):
        self.api_key = os.getenv("MINIMAX_API_KEY")
        raw_base_url = os.getenv("MINIMAX_BASE_URL", "https://api.minimax.chat/v1")
        if not raw_base_url.endswith("/"):
            raw_base_url += "/"
        self.base_url = raw_base_url
        self.model = os.getenv("MINIMAX_MODEL", "abab6.5g-chat")
        
        if not self.api_key:
            raise ValueError("未在环境变量中检测到有效的 MINIMAX_API_KEY")

        # 默认超时配置
        default_timeouts = {
            "connect": 5.0,
            "read": 20.0,
            "write": 5.0,
            "pool": 10.0
        }
        timeouts = timeout_cfg or default_timeouts

        # 1. 实例化连接池大小限制 (Limits)
        limits = httpx.Limits(
            max_connections=max_connections,
            max_keepalive_connections=max_keepalive
        )
        
        # 2. 实例化四维超时矩阵 (Timeout)
        timeout = httpx.Timeout(
            connect=timeouts["connect"],
            read=timeouts["read"],
            write=timeouts["write"],
            pool=timeouts["pool"]
        )

        # 3. 实例化长生命周期的异步请求客户端 (长生命周期托管连接池)
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers,
            limits=limits,
            timeout=timeout
        )

    async def close(self):
        """关闭客户端连接池"""
        await self.client.aclose()

    async def request_with_retry(self, messages: list[dict], temperature: float = 0.7, max_retries: int = 3) -> str:
        """执行带指数退避和 Jitter 随机抖动重试的大模型请求"""
        # 必须为相对路径且不能以 / 开头，以便 httpx 拼接时保留 base_url 中的 /v1/ 路径
        url = "chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": max(0.01, temperature)
        }
        
        base_delay = 1.0  # 指数退避延迟基数（秒）

        for attempt in range(max_retries):
            try:
                response = await self.client.post(url, json=payload)
                # 抛出非 2xx 的状态码异常（如 429、500）
                response.raise_for_status()
                
                resp_json = response.json()
                return resp_json["choices"][0]["message"]["content"]
                
            except (httpx.TimeoutException, httpx.HTTPStatusError) as e:
                # 若达到最大重试次数，向外抛出最终异常
                if attempt == max_retries - 1:
                    print(f"[❌ ERROR] 请求最终失败，已重试 {max_retries} 次。抛出异常：{type(e).__name__}")
                    raise e
                
                # 计算带 Jitter 随机抖动的指数退避延迟
                # Delay = base_delay * 2^attempt + random(0, 0.2)
                delay = (base_delay * (2 ** attempt)) + random.uniform(0.0, 0.2)
                print(f"[⚠️ WARNING] 请求遭遇网络或限流异常: {type(e).__name__} -> {str(e)[:60]}... "
                      f"正在进行第 {attempt + 1} 次重试，退避等待 {delay:.2f} 秒...")
                
                await asyncio.sleep(delay)


# =====================================================================
# 多方案对比调试与运行主入口 (物理隔离与冗余设计)
# =====================================================================

# 单次实例化短周期客户端测试辅助函数 (对比方案一)
async def request_single_instance(api_key: str, base_url: str, model: str, messages: list) -> str:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    clean_base_url = base_url
    if not clean_base_url.endswith("/"):
        clean_base_url += "/"
    url = f"{clean_base_url}chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.7
    }
    # 每次请求均创建并销毁客户端 (无连接池复用，强制 TCP 重建)
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]


if __name__ == "__main__":
    print("=" * 80)
    print("🚀 Week 4 Day 26 HTTPX 连接池性能对比与异常重试工程实验")
    print("=" * 80)

    api_key = os.getenv("MINIMAX_API_KEY")
    base_url = os.getenv("MINIMAX_BASE_URL", "https://api.minimax.chat/v1")
    model = os.getenv("MINIMAX_MODEL", "abab6.5g-chat")
    
    messages = [{"role": "user", "content": "回答‘你好’。"}]
    concurrency_count = 5  # 并发请求次数

    # -----------------------------------------------------------------
    # 【方案一】 单次实例化短周期客户端测试 (测试 TCP/TLS 重建开销)
    # -----------------------------------------------------------------
    print(f"\n[方案一] 启动无连接池并发测试 ({concurrency_count}次并行请求)...")
    
    async def run_single_instances():
        start_time = time.time()
        tasks = [
            request_single_instance(api_key, base_url, model, messages) 
            for _ in range(concurrency_count)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        end_time = time.time()
        
        print(f"  方案一执行完毕，总耗时: {end_time - start_time:.2f} 秒")
        print(f"  首条响应结果: {results[0]}")
        return end_time - start_time

    time_unsafe = asyncio.run(run_single_instances())

    print("-" * 80)

    # -----------------------------------------------------------------
    # 【方案二】 使用长期托管连接池 PooledLLMClient 测试 (连接池复用)
    # -----------------------------------------------------------------
    print(f"\n[方案二] 启动连接池复用并发测试 ({concurrency_count}次并行请求)...")
    
    async def run_pooled_client():
        client = PooledLLMClient(max_connections=10, max_keepalive=5)
        
        # 1. 连接池前置热身 (Warm Up)
        # 首次请求是冷启动，池中尚无活跃套接字。前置热身能预先建立并保留 Keep-Alive 长连接链路。
        print("  [Warm Up] 正在进行前置热身以在池中建立 TCP/TLS 保活链路...")
        await client.request_with_retry(messages)
        
        # 2. 并发测试
        start_time = time.time()
        tasks = [
            client.request_with_retry(messages) 
            for _ in range(concurrency_count)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        end_time = time.time()
        
        print(f"  方案二执行完毕，总耗时: {end_time - start_time:.2f} 秒")
        print(f"  首条响应结果: {results[0]}")
        
        await client.close()
        return end_time - start_time

    time_safe = asyncio.run(run_pooled_client())

    # 计算复用带来的延迟缩减效益百分比
    improvement = ((time_unsafe - time_safe) / time_unsafe) * 100
    print(f"\n👉 性能对比结论：连接池复用比单次实例化重建 TCP 时延缩短了 {improvement:.1f}%！")
    print("\n💡 【系统设计与性能调优硬核原理分析】")
    print("1. 为什么在轻量级请求下，连接池的网络复用优势可能被模型推理耗时抖动所淹没？")
    print("   大模型服务单次请求的总时延中，大模型首字推理 (TTFT) 与 Token 生成时间占了 90% 以上 (如 0.5s~2s)，")
    print("   且云端 GPU 推理负载在多租户环境下波动剧烈。网络层 TCP/TLS 握手所节省的 100ms~200ms 开销，")
    print("   在总耗时中占比过低，因此单次运行的对比数据很容易受到模型端推理时延抖动的随机干扰。")
    print("2. 为什么首次连接池请求不明显？")
    print("   首次运行属于冷启动 (Cold Start)，池内没有活跃链路，它依然需要物理握手。加入前置 Warm Up 热身")
    print("   能预先建立物理保活套接字，供后续高并发协程在瞬间复用该管道。")
    print("3. 连接池的最核心价值是什么？")
    print("   相比于微弱的时延缩短，连接池的最关键价值是——【防止端口耗尽崩溃】。它将系统占用的套接字总数")
    print("   限制在 Limits 常数内并循环复用，彻底规避了高并发下产生数千个 TIME_WAIT 套接字进而抛出")
    print("   OSError: [Errno 99] 无法分配临时端口的灾难，保障 Agent 系统在大并发下稳定常备。")

    print("-" * 80)

    # -----------------------------------------------------------------
    # 【方案三】 异常工程重试测试 (人为配置极短超时)
    # -----------------------------------------------------------------
    print("\n[方案三] 启动异常重试测试：配置 0.01秒 的极短超时强行制造 ReadTimeout 并观察退避重试机制...")
    
    async def run_timeout_retry():
        # 人为强行制造极短 read 超时
        strict_timeout = {"connect": 5.0, "read": 0.01, "write": 5.0, "pool": 10.0}
        bad_client = PooledLLMClient(timeout_cfg=strict_timeout)
        
        try:
            bad_messages = [{"role": "user", "content": "写一篇关于连接池的千字文章。"}]
            await bad_client.request_with_retry(bad_messages, max_retries=3)
        except Exception as e:
            print(f"\n✅ 成功捕获并隔离最终抛出的异常: {type(e).__name__} -> {e}")
            print("异常重试与指数退避抖动机制验证完成。")
        finally:
            await bad_client.close()

    asyncio.run(run_timeout_retry())
    print("=" * 80)
