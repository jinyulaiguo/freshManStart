"""
==============================================================================
LLM Reliability Adapter - 策略配置管理模块 (config.py)
==============================================================================

设计方案说明：
1. 设计意图 (Design Intent)：
   收拢控制 LLM 可靠性层运行参数的全局配置。包括最大重试次数、本地零延迟修补开关、
   超步超时预算、熔断机制门限以及重试间隔（指数退避配置）。
2. 类与函数结构 (Class Structure)：
   - `ReliabilityConfig`: 基于 Pydantic BaseModel 的数据契约配置类。
3. 关键数据流 (Data Flow)：
   - 在构造 UniversalAdapter 实例或调用 AdapterInput 时被注入，驱动 Pipeline 及 Recovery Engine。
4. 核心用例考量 (Test Case Intent)：
   - 支持开发者针对不同的业务敏感度调整重试策略（如对 Latency 敏感的场景关闭 Re-prompt，只保留 Local Fix）。
==============================================================================
"""

from typing import Optional
from pydantic import BaseModel, Field


class ReliabilityConfig(BaseModel):
    """
    LLM 可靠性适配器全局策略配置类
    """
    max_retries: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Level 2 LLM Re-prompt 重试的最大允许轮数"
    )
    
    enable_local_repair: bool = Field(
        default=True,
        description="是否开启 Level 1 本地零延迟确定性修补 (补全双引号/括号/移除尾部逗号)"
    )
    
    enable_circuit_breaker: bool = Field(
        default=True,
        description="当重试达到 max_retries 上限后，是否触发 Level 3 熔断降级兜底"
    )
    
    timeout_seconds: float = Field(
        default=30.0,
        gt=0,
        description="单次 LLM 请求的硬性超时上限 (秒)"
    )
    
    backoff_factor: float = Field(
        default=1.5,
        ge=1.0,
        description="Level 2 重试时的指数退避系数 (Backoff Multiplier)"
    )
    
    verbose_logging: bool = Field(
        default=False,
        description="是否打印详细的 Pipeline 审计追踪日志"
    )
