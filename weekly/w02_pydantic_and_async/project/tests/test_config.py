"""
设计方案：
- 设计意图：验证项目配置加载模块与 Pydantic 字段验证器的正确性，拦截不合规的日志级别或越界配置参数。
- 类与函数结构：
  - `test_config_validation` 函数：验证合法配置的构造与非法日志级别的拦截。
  - `test_dotenv_loading` 函数：验证手动加载环境配置的功能。
- 关键数据流向：
  - 构造字典参数 -> AppSettings 实例化 -> 触发校验拦截器 -> 抛出 ValidationError 或输出合规配置。
"""

import pytest
from pydantic import ValidationError
from weekly.w02_pydantic_and_async.project.config.settings import AppSettings, load_config

def test_config_validation():
    # 正常默认构造
    cfg = AppSettings()
    assert cfg.http_timeout == 5.0
    assert cfg.log_level == "INFO"

    # 非法日志级别校验拦截
    with pytest.raises(ValidationError) as exc:
        AppSettings(log_level="TRACE")
    assert "日志级别必须是" in str(exc.value)

    # 边界约束校验拦截（http_timeout 必须大于 0）
    with pytest.raises(ValidationError):
        AppSettings(http_timeout=-1.0)

def test_dotenv_loading():
    # 验证 load_config 方法能无阻碍实例化
    cfg = load_config()
    assert isinstance(cfg, AppSettings)
    assert cfg.max_concurrent_tools > 0
