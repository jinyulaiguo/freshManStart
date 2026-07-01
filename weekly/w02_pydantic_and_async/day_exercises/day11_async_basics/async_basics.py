"""
================================================================================
设计方案 (Design Specification)
================================================================================
设计意图:
    本模块模拟了大模型 Agent 架构中的“多 LLM 并发评估与防崩溃调度器”。
    当需要对同一 Prompt 发送给多个大模型（如 gpt-4o, claude-3-5, deepseek-r1）
    进行并发调用时，我们需要保证：
    1. 并发调度以降低整体响应延迟；
    2. 对单个大模型调用提供超时截断（防止网络无限期挂起）；
    3. 对单个大模型接口抛出的异常提供物理隔离，避免一个模型不可用导致所有结果全部丢失。

类与函数结构:
    1. mock_llm_request (coroutine function):
        模拟单个 LLM API 请求。接收模型名称、Prompt、响应延迟以及是否失败的标识。
        如果 fail=True，在延迟后抛出 RuntimeError("API rate limit exceeded")；
        否则在延迟后返回响应字符串。
        
    2. orchestrate_llm_calls (coroutine function):
        并发调度器。接收一个包含模型配置的字典列表、全局 Prompt 以及单个模型最大超时阈值。
        需要使用 `asyncio.wait_for` 处理超时，并使用 `asyncio.gather(..., return_exceptions=True)`
        并发运行所有请求，最终返回结果列表（包含正常返回字符串或捕获的异常对象/超时信息）。

关键数据流流向:
    - 输入：`models_config`（含 name, delay, fail） + `prompt` + `timeout`
    - 分发：为每个配置调用 `mock_llm_request` 生成协程
    - 超时封装：对每个协程使用 `asyncio.wait_for` 进行包裹并单独捕获 TimeoutError
    - 并发调度：将包裹后的协程列表放入 `asyncio.gather(..., return_exceptions=True)`
    - 输出：返回混合结果列表，包含模型成功返回的数据、RuntimeError 异常对象或 TimeoutError/自定义超时结果。
================================================================================
"""

import asyncio
from typing import List, Dict, Any, Union


async def mock_llm_request(model_name: str, prompt: str, delay: float, fail: bool = False) -> str:
    """
    模拟发送网络请求到 LLM API。
    
    参数:
        model_name: 模型的名字（如 'gpt-4o'）
        prompt: 发给模型的提示词
        delay: 模拟的网络延迟时间（秒）
        fail: 是否模拟调用失败抛出异常
        
    返回:
        模型返回的答复字符串
        
    异常:
        RuntimeError: 当 fail 为 True 时抛出，模拟接口限流或凭证失效。
    """
    # 非阻塞睡眠模拟网络延时
    await asyncio.sleep(delay)
    if fail:
        raise RuntimeError("API rate limit exceeded")
    return f"[{model_name}] Response to '{prompt}'"


async def orchestrate_llm_calls(
    models_config: List[Dict[str, Any]], 
    prompt: str, 
    timeout: float
) -> List[Union[str, Exception]]:
    """
    并发调度多个模型的请求，并做超时与异常容错拦截。
    
    参数:
        models_config: 模型配置列表，例如:
                       [
                           {"name": "gpt-4o", "delay": 0.2, "fail": False},
                           {"name": "claude-3-5", "delay": 1.5, "fail": False}
                       ]
        prompt: 提示词内容
        timeout: 每个模型请求的最大允许超时时间（秒）
        
    返回:
        按输入顺序排序的结果列表。如果某个模型超时，返回 TimeoutError 对象或特定标识；
        如果某个模型抛出异常，返回对应的 Exception 对象。
    """
    
    async def wrap_with_timeout(config: Dict[str, Any]) -> Union[str, Exception]:
        """
        局部辅助协程：为单个 LLM 请求配置超时并拦截超时异常。
        这样做可以避免单一协程超时导致外层 gather 全局抛出异常，
        也可以让超时像普通异常一样被 gather(return_exceptions=True) 统一收集。
        """
        coro = mock_llm_request(
            model_name=config["name"],
            prompt=prompt,
            delay=config["delay"],
            fail=config.get("fail", False)
        )
        try:
            # 限制单个协程执行的最大时长
            return await asyncio.wait_for(coro, timeout=timeout)
        except asyncio.TimeoutError as e:
            # 返回 TimeoutError 异常实例，使其能在结果列表中反映出来
            return e

    # 构造待并发运行的任务协程列表
    tasks = [wrap_with_timeout(cfg) for cfg in models_config]
    
    # 核心：使用 return_exceptions=True 保证某个协程报错时，其他协程能继续运行，并把异常收集到列表中返回
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return list(results)


async def main():
    # 模拟在实际多 LLM 路由时的模型配置
    models_config = [
        {"name": "gpt-4o", "delay": 0.1, "fail": False},
        {"name": "claude-3-5", "delay": 0.8, "fail": False},   # 延迟 0.8s，如果超时设定为 0.3s 则会超时
        {"name": "deepseek-r1", "delay": 0.2, "fail": True},   # 会因为限流抛出 RuntimeError 异常
    ]
    prompt = "Explain quantum computing in one sentence."
    timeout = 0.3
    
    print("\n=== [AI 调试] 开始并发调度大模型评估 ===")
    start_time = time.perf_counter()
    
    results = await orchestrate_llm_calls(models_config, prompt, timeout)
    
    elapsed = time.perf_counter() - start_time
    print(f"=== [AI 调试] 调度结束，总耗时: {elapsed:.4f}s ===\n")
    
    for config, res in zip(models_config, results):
        name = config["name"]
        if isinstance(res, asyncio.TimeoutError):
            print(f"❌ 模型 [{name}] 请求超时 (超过了设定的最大阀值 {timeout}s)")
        elif isinstance(res, Exception):
            print(f"❌ 模型 [{name}] 请求崩溃: {type(res).__name__} - {res}")
        else:
            print(f"✅ 模型 [{name}] 成功返回: {res}")
    print()


if __name__ == "__main__":
    import time
    asyncio.run(main())

