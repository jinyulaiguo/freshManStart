"""
Week 4 Day 28 综合实战 — 微引擎 3：熔断器异步装饰器适配层 (Circuit Breaker Decorator)

设计方案：
1. 设计意图：
   将 Day 27 的熔断器状态机思想封装为通用的 @circuit_breaker 异步装饰器工厂函数。
   任何被修饰的异步函数在执行前会检查熔断状态，执行后会根据成功/失败更新状态计数器。
   当连续失败达到阈值时，熔断器进入 Open 状态，后续调用在本地 <1ms 内快速失败，
   保护下游的脆弱 API 服务免受雪崩冲击。

2. 类与函数结构：
   - CircuitBreakerOpenException(Exception): 熔断开启异常，调用者可捕获此异常执行降级逻辑。
   - CircuitBreakerState: 数据类，承载单个熔断器实例的状态（状态枚举、失败计数、最后失败时间戳）。
   - circuit_breaker(failure_threshold, cooldown_seconds): 装饰器工厂函数，返回闭包装饰器。
     - wrapper(*args, **kwargs): 闭包内维护独立的 CircuitBreakerState 实例，
       执行前置状态检查 → 原函数调用 → 成功/失败后置状态更新。

3. 关键数据流向：
   被修饰函数调用 ──→ wrapper 前置检查 ──(Open 且未过冷却)──→ 抛出 CircuitBreakerOpenException
                                        ──(Open 且已过冷却)──→ 切为 Half-Open 放行
                                        ──(Closed/Half-Open)──→ 执行原函数
                                           ──→ 成功: Half-Open→Closed, 重置计数
                                           ──→ 失败: 累加计数, 达阈值→Open
"""

import time
import asyncio
import functools
import logging

logger = logging.getLogger(__name__)


# =====================================================================
# 熔断器开启异常
# =====================================================================

class CircuitBreakerOpenException(Exception):
    """自定义异常：熔断器处于 Open 状态，请求被本地快速拦截"""
    pass


# =====================================================================
# 熔断器状态数据容器
# =====================================================================

class CircuitBreakerState:
    """承载单个熔断器实例的全部运行时状态"""

    def __init__(self, failure_threshold: int, cooldown_seconds: float):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.state: str = "CLOSED"  # CLOSED | OPEN | HALF-OPEN
        self.failures: int = 0
        self.last_failure_time: float = 0.0

    def check_state(self) -> None:
        """前置熔断状态判定与冷却期跃迁"""
        if self.state == "OPEN":
            elapsed = time.time() - self.last_failure_time
            if elapsed > self.cooldown_seconds:
                self.state = "HALF-OPEN"
                logger.info(
                    f"[熔断器] 冷却期已过 ({elapsed:.1f}s > {self.cooldown_seconds}s)，"
                    f"状态由 OPEN → HALF-OPEN，允许探路请求通过。"
                )
            else:
                remaining = self.cooldown_seconds - elapsed
                raise CircuitBreakerOpenException(
                    f"熔断器处于 OPEN 状态，距冷却完毕还剩 {remaining:.1f}s。"
                    f"请求在本地直接拦截快速失败。"
                )

    def record_success(self) -> None:
        """记录成功调用，执行状态自愈"""
        if self.state == "HALF-OPEN":
            logger.info("[熔断器] 探路请求成功！状态由 HALF-OPEN → CLOSED，失败计数器清零。")
            self.state = "CLOSED"
            self.failures = 0
        elif self.state == "CLOSED":
            self.failures = 0  # 正常成功，保持清零

    def record_failure(self) -> None:
        """记录失败调用，执行状态迁移"""
        self.failures += 1
        self.last_failure_time = time.time()
        logger.warning(
            f"[熔断器] 捕获到异常，当前连续失败次数: "
            f"{self.failures}/{self.failure_threshold}"
        )

        if self.failures >= self.failure_threshold:
            self.state = "OPEN"
            logger.error(
                f"[熔断器] 连续失败达阈值 {self.failure_threshold}！"
                f"状态切换为 OPEN，启动本地快速失败拦截。"
            )


# =====================================================================
# 熔断器异步装饰器工厂
# =====================================================================

def circuit_breaker(failure_threshold: int = 5, cooldown_seconds: float = 30.0):
    """
    熔断器异步装饰器工厂函数。

    用法：
        @circuit_breaker(failure_threshold=3, cooldown_seconds=10.0)
        async def risky_api_call(url: str) -> dict:
            ...

    参数:
        failure_threshold: 连续失败多少次后触发熔断 (Closed → Open)
        cooldown_seconds: 熔断后的冷却等待秒数 (Open 持续时长)
    """
    def decorator(func):
        # 每个被修饰的函数拥有独立的熔断器状态实例
        breaker_state = CircuitBreakerState(failure_threshold, cooldown_seconds)

        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # 1. 前置状态检查：Open 则快速失败，冷却期过则切 Half-Open
            breaker_state.check_state()

            # 2. 执行被修饰的原函数
            try:
                result = await func(*args, **kwargs)
                # 3. 成功：自愈状态更新
                breaker_state.record_success()
                return result
            except CircuitBreakerOpenException:
                # 熔断器自身抛出的异常，直接透传不计入失败
                raise
            except Exception as e:
                # 4. 失败：累加计数并执行状态迁移
                breaker_state.record_failure()
                raise

        # 暴露熔断器状态供外部监控和测试
        wrapper.breaker_state = breaker_state
        return wrapper

    return decorator


# =====================================================================
# 模块自测主入口
# =====================================================================

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )

    print("=" * 80)
    print("🚀 Day 28 微引擎 3：熔断器异步装饰器自测")
    print("=" * 80)

    # 定义一个可控制成功/失败的模拟异步函数（使用可变容器规避 nonlocal scope 限制）
    call_counter = [0]

    @circuit_breaker(failure_threshold=3, cooldown_seconds=2.0)
    async def mock_api_call(should_fail: bool = False) -> str:
        call_counter[0] += 1
        await asyncio.sleep(0.05)
        if should_fail:
            raise ConnectionError(f"模拟网络故障 (第 {call_counter[0]} 次调用)")
        return f"Success (第 {call_counter[0]} 次调用)"

    async def run_test():

        # 阶段 1: 正常调用
        print("\n[阶段 1] Closed 状态正常调用...")
        result = await mock_api_call(should_fail=False)
        print(f"  结果: {result}, 状态: {mock_api_call.breaker_state.state}")

        # 阶段 2: 连续失败触发熔断
        print("\n[阶段 2] 注入 3 次故障触发熔断...")
        for i in range(3):
            try:
                await mock_api_call(should_fail=True)
            except ConnectionError as e:
                print(f"  故障 {i+1}: {e}")
        print(f"  当前状态: {mock_api_call.breaker_state.state} (预期 OPEN)")

        # 阶段 3: Open 状态快速失败
        print("\n[阶段 3] 验证 Open 状态快速拦截...")
        try:
            start = time.time()
            await mock_api_call(should_fail=False)
        except CircuitBreakerOpenException as cbe:
            elapsed = time.time() - start
            print(f"  快速拦截成功！耗时: {elapsed*1000:.1f}ms, 报错: {cbe}")

        # 阶段 4: 等待冷却后自愈
        print("\n[阶段 4] 等待冷却 2.2s 后自愈...")
        await asyncio.sleep(2.2)
        result = await mock_api_call(should_fail=False)
        print(f"  自愈结果: {result}, 状态: {mock_api_call.breaker_state.state} (预期 CLOSED)")

    asyncio.run(run_test())
    print("\n" + "=" * 80)
