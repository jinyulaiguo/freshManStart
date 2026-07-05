"""
Week 4 Day 27 参考答案：工具安全护栏：熔断器与并发速率限制

设计方案：
1. 设计意图：
   手写一个融合了并发速率限制（asyncio.Semaphore）和熔断器状态机（Closed -> Open -> Half-Open）的安全护栏大模型客户端。
   当遭遇外部网络雪崩时，在本地 1ms 内熔断拦截，实施快速失败（Fail-Fast），拒绝重试流量；
   在冷却期过后，自动切为 Half-Open 发行少量探路流量，成功则自愈恢复为 Closed。

2. 类与函数结构：
   - 包含工程级 sys.path 自动寻址补丁逻辑。
   - `CircuitBreakerOpenException`: 熔断开启异常类。
   - `SafeLLMClient`: 安全护栏客户端。
     - `__init__()`: 初始化限制与状态机参数。
     - `_check_breaker()`: 请求前置判定与状态冷却流转（Open -> Half-Open）。
     - `call_api_safe()`: 信号量并发限制、捕获网络异常更新状态及自愈（Half-Open -> Closed）。

3. 关键数据流向：
   并发请求 ──> call_api_safe() ──> _check_breaker() 验证 ──(信号量并发限制)──> 
   网络请求 (模拟故障) ──> 捕获异常 ──> 失败计数 ──> 状态迁移 ──> 本地拦截/探路自愈。
"""

import sys
import os
import asyncio
import time

# =====================================================================
# 防御性 sys.path 补丁逻辑 (多策略寻址注入)
# =====================================================================
current_dir = os.path.dirname(os.path.realpath(__file__))
root_dir = os.path.abspath(os.path.join(current_dir, "../../.."))

if os.getcwd() not in sys.path:
    sys.path.insert(0, os.getcwd())
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)


class CircuitBreakerOpenException(Exception):
    """自定义异常：熔断器处于开启（断开）状态"""
    pass


class SafeLLMClient:
    """整合并发速率限制与熔断状态机的安全大模型客户端"""

    def __init__(self, max_concurrent: int = 3, failure_threshold: int = 3, cooldown_time: float = 3.0):
        # 1. 信号量控制并发速率，防 TPM/RPM 限流
        self.semaphore = asyncio.Semaphore(max_concurrent)
        
        # 2. 状态机基本参数
        self.failure_threshold = failure_threshold
        self.cooldown_time = cooldown_time
        
        self.state = "CLOSED"  # CLOSED, OPEN, HALF-OPEN
        self.failures = 0
        self.last_failure_time = 0.0

    def _check_breaker(self):
        """前置熔断控制与状态跃迁判定"""
        if self.state == "OPEN":
            current_time = time.time()
            # 检查冷却期是否到期
            if current_time - self.last_failure_time > self.cooldown_time:
                self.state = "HALF-OPEN"
                print(f"  [🔄 状态转移] 冷却期已过，熔断器由 OPEN 切换为 HALF-OPEN，允许尝试性探路。")
            else:
                # 冷却期未过，抛出异常以实施本地快速失败（Fail-Fast）
                remaining = self.cooldown_time - (current_time - self.last_failure_time)
                raise CircuitBreakerOpenException(
                    f"熔断器当前处于开启状态，距自愈冷却完毕还剩 {remaining:.2f} 秒。请求在本地直接拦截快速失败！"
                )

    async def call_api_safe(self, mock_should_fail: bool) -> str:
        """执行并发控制与熔断自愈的网络模拟请求"""
        # 1. 熔断前置判定，保护后端服务
        self._check_breaker()

        # 2. 信号量限流锁控制并发度
        async with self.semaphore:
            try:
                # 模拟网络调用延迟
                await asyncio.sleep(0.1)
                
                if mock_should_fail:
                    raise ConnectionError("大模型服务突发过载，物理连接超时 (Mocked)！")

                # 3. 成功时的处理逻辑
                if self.state == "HALF-OPEN":
                    self.state = "CLOSED"
                    self.failures = 0
                    print(f"  [🔄 状态自愈] 探路请求成功！熔断器由 HALF-OPEN 恢复为 CLOSED，重置清空失败计数器。")
                elif self.state == "CLOSED":
                    self.failures = 0  # 正常请求成功，维持清空
                
                return "Success (大模型正常响应数据)"

            except Exception as e:
                # 排除熔断器自身抛出的快速失败异常，只捕获真实网络异常
                if isinstance(e, CircuitBreakerOpenException):
                    raise e
                
                # 4. 失败时的状态转移逻辑
                self.failures += 1
                self.last_failure_time = time.time()
                print(f"  [⚠️ 异常捕获] 发生网络异常 ({type(e).__name__})，当前连续失败次数: {self.failures}/{self.failure_threshold}")
                
                # 如果处于 CLOSED 或 HALF-OPEN 状态且失败数达阈值，切为 OPEN 并警报
                if self.state in ("CLOSED", "HALF-OPEN") and self.failures >= self.failure_threshold:
                    self.state = "OPEN"
                    print(f"  [🚨 状态转移] 连续失败数达阈值，熔断器切换为 OPEN 状态！启动本地熔断拦截护栏。")
                
                raise e


# =====================================================================
# 多方案与多阶段隔离运行对比 (物理隔离与冗余设计)
# =====================================================================

if __name__ == "__main__":
    print("=" * 80)
    print("🚀 Week 4 Day 27 工具熔断器状态机与并发速率限制器验证")
    print("=" * 80)

    async def run_simulation():
        # 实例化安全护栏客户端：并发速率限为 2，失败阈值为 3，自愈冷却时间为 2.0 秒
        client = SafeLLMClient(max_concurrent=2, failure_threshold=3, cooldown_time=2.0)

        # -------------------------------------------------------------
        # 【阶段一】 Closed 状态下的并发限制验证
        # -------------------------------------------------------------
        print("\n" + "="*20 + " 阶段一：Closed 状态正常高并发请求验证 " + "="*20)
        print("并发发起 4 个正常请求，观察信号量（最大并发为 2）的分流限速表现...")
        
        start_time = time.time()
        tasks = [client.call_api_safe(mock_should_fail=False) for _ in range(4)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        end_time = time.time()
        
        print(f"并发请求执行完毕，总耗时: {end_time - start_time:.2f} 秒 (因限速 2，耗时应约为 0.2s - 0.3s)")
        print(f"请求结果汇总: {results}")

        # -------------------------------------------------------------
        # 【阶段二】 注入故障触发熔断器开启 (Closed -> Open)
        # -------------------------------------------------------------
        print("\n" + "="*20 + " 阶段二：连续 3 次失败注入触发熔断 (Closed -> Open) " + "="*20)
        print("注入 3 次故障请求，促使连续失败次数达到阈值 3：")
        for idx in range(3):
            try:
                await client.call_api_safe(mock_should_fail=True)
            except Exception as e:
                print(f"  请求 {idx+1} 触发网络报错: {type(e).__name__} -> {e}")
        
        print(f"当前熔断器状态：{client.state} (预期应为 OPEN)")

        # -------------------------------------------------------------
        # 【阶段三】 验证开启状态下的本地 Fail-Fast 拦截
        # -------------------------------------------------------------
        print("\n" + "="*20 + " 阶段三：验证 Open 状态下的本地快速失败拦截 " + "="*20)
        print("熔断器开启状态下，尝试发起 2 次请求，观察是否在本地瞬间被拦截抛出异常...")
        
        for idx in range(2):
            try:
                start = time.time()
                await client.call_api_safe(mock_should_fail=False)
            except CircuitBreakerOpenException as cbe:
                print(f"  请求 {idx+1} 拦截成功！耗时: {time.time() - start:.6f}s (快速失败)，报错: {cbe}")
            except Exception as e:
                print(f"  请求 {idx+1} 捕获到非预期异常: {e}")

        # -------------------------------------------------------------
        # 【阶段四】 冷却期到期后自愈探路与恢复 (Open -> Half-Open -> Closed)
        # -------------------------------------------------------------
        print("\n" + "="*20 + " 阶段四：验证冷却期到期自愈探路 (Open -> Half-Open -> Closed) " + "="*20)
        cooldown = 2.2
        print(f"开始等待冷却时间 {cooldown} 秒...")
        await asyncio.sleep(cooldown)
        
        print("\n发起 1 个自愈探路请求 (mock_should_fail=False)...")
        try:
            resp = await client.call_api_safe(mock_should_fail=False)
            print(f"  自愈探路请求成功，响应内容: {resp}")
        except Exception as e:
            print(f"  自愈探路失败: {e}")
            
        print(f"当前自愈后熔断器状态：{client.state} (预期应恢复为 CLOSED)")
        
        # 再次进行正常并发，验证功能已完全恢复
        print("\n重新发起并发测试，验证网络管道已完全恢复正常通畅...")
        tasks = [client.call_api_safe(mock_should_fail=False) for _ in range(2)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        print(f"恢复后并发请求结果: {results}")
        print("=" * 80)

    asyncio.run(run_simulation())
