"""
设计方案：
- 设计意图：构建一个兼容同步（def）与异步（async def）函数的指数退避重试装饰器（基于 Day 3 闭包与装饰器设计）。它支持特定类型异常过滤捕获、自动延迟休眠和日志追踪记录，用于增强易受网络抖动影响的工具之鲁棒性。
- 类与函数结构：
  - `retry(times, base_delay, exceptions, logger)` 函数：带参装饰器，返回实际闭包包装器。
  - `async_wrapper` 与 `sync_wrapper` 内部函数：运行时根据被修饰对象的类型自动派发。
- 关键数据流向：
  - 调用被修饰函数 -> 发生捕获白名单异常 -> 计算指数退避延迟 $delay = base\_delay \times 2^{attempt}$ -> 触发 asyncio.sleep/time.sleep 阻塞重试 -> 超过重试阈值后抛出最终异常。
"""

import asyncio
import inspect
import time
from functools import wraps
from typing import Any, Callable, Optional, Tuple, Type, Union

def retry(
    times: int = 3,
    base_delay: float = 0.5,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    logger: Optional[Any] = None
) -> Callable[..., Any]:
    """
    指数退避重试装饰器。
    支持同时装饰同步函数与异步协程函数。
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        if inspect.iscoroutinefunction(func):
            @wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                last_exc = None
                for attempt in range(times + 1):
                    try:
                        return await func(*args, **kwargs)
                    except exceptions as e:
                        last_exc = e
                        if attempt >= times:
                            if logger:
                                logger.error(f"Async function '{func.__name__}' failed after {times} retries. Final error: {e}")
                            break
                        delay = base_delay * (2 ** attempt)
                        if logger:
                            logger.warning(
                                f"Async retry {attempt + 1}/{times} for '{func.__name__}' "
                                f"sleeping {delay:.2f}s due to exception: {type(e).__name__}: {e}"
                            )
                        await asyncio.sleep(delay)
                if last_exc:
                    raise last_exc
            return async_wrapper
        else:
            @wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                last_exc = None
                for attempt in range(times + 1):
                    try:
                        return func(*args, **kwargs)
                    except exceptions as e:
                        last_exc = e
                        if attempt >= times:
                            if logger:
                                logger.error(f"Sync function '{func.__name__}' failed after {times} retries. Final error: {e}")
                            break
                        delay = base_delay * (2 ** attempt)
                        if logger:
                            logger.warning(
                                f"Sync retry {attempt + 1}/{times} for '{func.__name__}' "
                                f"sleeping {delay:.2f}s due to exception: {type(e).__name__}: {e}"
                            )
                        time.sleep(delay)
                if last_exc:
                    raise last_exc
            return sync_wrapper
    return decorator
