"""
设计方案：
- 设计意图：构建测试套件的通用 Fixture 提供层（基于 Pytest Fixtures 模式），隔离测试环境与生产配置，减少测试用例中的重复初始化开销。
- 类与函数结构：
  - `test_settings` fixture: 返回针对测试环境优化的 `AppSettings`（短超时、低重试次数、禁用日志写文件）。
  - `test_registry` fixture: 返回预先通过反射机制注册好 calculator, weather, exchange 3 个真实工具类的 `ToolRegistry` 实例。
  - `test_runner` fixture: 返回装配好的 `AsyncToolRunner` 实例。
- 关键数据流向：
  - 启动测试 -> 依次执行 `test_settings` -> `test_registry` -> `test_runner` -> 作为依赖参数注入具体的单元测试函数中。
"""

import pytest
from weekly.w02_pydantic_and_async.project.config.settings import AppSettings
from weekly.w02_pydantic_and_async.project.core.registry import ToolRegistry
from weekly.w02_pydantic_and_async.project.core.runner import AsyncToolRunner

@pytest.fixture
def test_settings() -> AppSettings:
    """返回测试专用配置对象"""
    return AppSettings(
        http_timeout=2.0,
        max_retries=1,
        retry_base_delay=0.01,
        log_level="DEBUG",
        log_to_file=False,
        max_concurrent_tools=5
    )

@pytest.fixture
def test_registry(test_settings) -> ToolRegistry:
    """返回预注册了天气、汇率和计算器工具的注册表对象"""
    from weekly.w02_pydantic_and_async.project import tools
    registry = ToolRegistry(test_settings)
    registry.discover(tools)
    return registry

@pytest.fixture
def test_runner(test_settings, test_registry) -> AsyncToolRunner:
    """返回配置好的工具调度引擎"""
    return AsyncToolRunner(
        settings=test_settings,
        registry=test_registry,
        callback=None
    )
