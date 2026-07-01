import asyncio
import time
import pytest
from weekly.w02_pydantic_and_async.day_exercises.day11_async_basics.async_basics import (
    mock_llm_request as ref_mock_llm,
    orchestrate_llm_calls as ref_orchestrate,
)

try:
    from weekly.w02_pydantic_and_async.day_exercises.day11_async_basics.practice import (
        mock_llm_request as prac_mock_llm,
        orchestrate_llm_calls as prac_orchestrate,
    )
except ImportError:
    prac_mock_llm = None
    prac_orchestrate = None


@pytest.mark.asyncio
async def test_reference_llm_orchestrator():
    """
    验证参考标准答案的多模型异步路由调度行为。
    """
    models_config = [
        {"name": "gpt-4o", "delay": 0.1, "fail": False},
        {"name": "claude-3-5", "delay": 0.2, "fail": False},
        {"name": "deepseek-r1", "delay": 0.5, "fail": False},  # 这个最慢
    ]
    prompt = "Hello AI"
    
    start_time = time.perf_counter()
    # 全局超时设置为 0.6s，应该全部正常返回
    results = await ref_orchestrate(models_config, prompt, timeout=0.6)
    elapsed = time.perf_counter() - start_time
    
    # 1. 验证结果顺序与内容
    assert len(results) == 3
    assert results[0] == "[gpt-4o] Response to 'Hello AI'"
    assert results[1] == "[claude-3-5] Response to 'Hello AI'"
    assert results[2] == "[deepseek-r1] Response to 'Hello AI'"
    
    # 2. 验证并发时效性：总用时应略大于 0.5s，显著小于串行的 0.8s
    assert elapsed >= 0.5, f"Elapsed time {elapsed}s is less than max delay"
    assert elapsed < 0.65, f"Elapsed time {elapsed}s indicates serialization"


@pytest.mark.asyncio
async def test_reference_llm_timeout_and_fault_tolerance():
    """
    验证参考标准答案在面对超时截断与服务崩溃时的容错特征。
    """
    models_config = [
        {"name": "gpt-4o", "delay": 0.1, "fail": False},      # 成功
        {"name": "claude-3-5", "delay": 0.8, "fail": False},   # 延迟 0.8s，触发 0.3s 的超时
        {"name": "deepseek-r1", "delay": 0.2, "fail": True},   # 报错 RuntimeError
    ]
    prompt = "Complex reasoning"
    
    results = await ref_orchestrate(models_config, prompt, timeout=0.3)
    
    assert len(results) == 3
    # 1. 第一个正常响应
    assert results[0] == "[gpt-4o] Response to 'Complex reasoning'"
    # 2. 第二个超时，应捕获到 TimeoutError
    assert isinstance(results[1], asyncio.TimeoutError)
    # 3. 第三个抛出 RuntimeError，因 return_exceptions=True 异常被捕获放入结果
    assert isinstance(results[2], RuntimeError)
    assert str(results[2]) == "API rate limit exceeded"


@pytest.mark.asyncio
async def test_practice_placeholder():
    """
    验证练习模版未完成时的 NotImplementedError 拦截，以及完成后的逻辑校验。
    """
    if prac_mock_llm is None or prac_orchestrate is None:
        pytest.skip("Practice template is not imported.")
        
    models_config = [{"name": "gpt-4o", "delay": 0.1, "fail": False}]
    
    try:
        await prac_orchestrate(models_config, "test", timeout=0.5)
    except NotImplementedError:
        # 说明尚未实现，通过
        return
        
    # 如果已实现，则通过同样的测试用例进行判定
    results = await prac_orchestrate(
        models_config=[
            {"name": "gpt-4o", "delay": 0.1, "fail": False},
            {"name": "claude-3-5", "delay": 0.4, "fail": False},
            {"name": "deepseek-r1", "delay": 0.1, "fail": True},
        ],
        prompt="Test practice",
        timeout=0.3
    )
    assert len(results) == 3
    assert results[0] == "[gpt-4o] Response to 'Test practice'"
    assert isinstance(results[1], asyncio.TimeoutError)
    assert isinstance(results[2], RuntimeError)
