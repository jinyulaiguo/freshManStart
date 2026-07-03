"""
设计方案：
- 设计意图：实现类型安全的配置管理，利用 pydantic 对外部配置进行强制类型转换与缺省值注入，同时使用 python-dotenv 读取局部 .env 环境变量文件。
- 类与函数结构：
  - `AppSettings` 类：继承自 Pydantic `BaseModel`，包含对网络、API 终结点、日志级别以及并发数限制的属性定义。
  - `load_config(env_path: str = None)` 函数：加载 .env 并反序列化为 `AppSettings` 实例。
- 关键数据流向：
  - 磁盘上的 `.env` 文件 -> `dotenv.load_dotenv` 载入系统环境变量 -> `os.environ` 字典 -> `AppSettings` 实例化进行类型校验 -> 供各个引擎与工具模块读取。
"""

import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator

class AppSettings(BaseModel):
    """项目全局配置模型（Pydantic 强类型约束）"""
    http_timeout: float = Field(default=5.0, gt=0, description="HTTP 请求超时时间（秒）")
    max_retries: int = Field(default=3, ge=0, description="网络请求最大重试次数")
    retry_base_delay: float = Field(default=0.5, gt=0, description="指数退避重试基准时间间隔（秒）")
    
    weather_api_base: str = Field(default="https://wttr.in", description="天气 API 服务基地址")
    exchange_api_base: str = Field(default="https://api.frankfurter.dev/v2", description="汇率 API 服务基地址")
    
    log_level: str = Field(default="INFO", description="系统运行日志记录级别")
    log_to_file: bool = Field(default=True, description="是否同时向本地文件输出日志")
    log_file_path: str = Field(default="tool_runner.log", description="本地日志输出文件路径")
    
    max_concurrent_tools: int = Field(default=10, gt=0, description="批量并发调度时的最大并发上限限制")

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper_v = v.upper()
        if upper_v not in levels:
            raise ValueError(f"日志级别必须是 {levels} 之一，当前输入为: {v}")
        return upper_v

def load_config(env_path: Optional[str] = None) -> AppSettings:
    """
    加载环境变量并实例化 AppSettings。
    如果未指定 env_path，则默认寻找同级或上级目录中的 .env。
    """
    if env_path:
        load_dotenv(dotenv_path=env_path, override=True)
    else:
        # 默认寻找当前文件所在目录的父目录下的 .env
        default_env = Path(__file__).resolve().parent.parent / ".env"
        if default_env.exists():
            load_dotenv(dotenv_path=str(default_env), override=True)
        else:
            load_dotenv(override=True)

    kwargs = {}
    
    if os.getenv("HTTP_TIMEOUT") is not None:
        kwargs["http_timeout"] = float(os.getenv("HTTP_TIMEOUT"))
    if os.getenv("MAX_RETRIES") is not None:
        kwargs["max_retries"] = int(os.getenv("MAX_RETRIES"))
    if os.getenv("RETRY_BASE_DELAY") is not None:
        kwargs["retry_base_delay"] = float(os.getenv("RETRY_BASE_DELAY"))
    if os.getenv("WEATHER_API_BASE") is not None:
        kwargs["weather_api_base"] = os.getenv("WEATHER_API_BASE")
    if os.getenv("EXCHANGE_API_BASE") is not None:
        kwargs["exchange_api_base"] = os.getenv("EXCHANGE_API_BASE")
    if os.getenv("LOG_LEVEL") is not None:
        kwargs["log_level"] = os.getenv("LOG_LEVEL")
    if os.getenv("LOG_TO_FILE") is not None:
        kwargs["log_to_file"] = os.getenv("LOG_TO_FILE").lower() in ("true", "1", "yes")
    if os.getenv("LOG_FILE_PATH") is not None:
        kwargs["log_file_path"] = os.getenv("LOG_FILE_PATH")
    if os.getenv("MAX_CONCURRENT_TOOLS") is not None:
        kwargs["max_concurrent_tools"] = int(os.getenv("MAX_CONCURRENT_TOOLS"))

    return AppSettings(**kwargs)
