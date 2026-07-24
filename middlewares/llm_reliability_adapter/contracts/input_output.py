"""
==============================================================================
LLM Reliability Adapter - 输入输出通用契约 (contracts/input_output.py)
==============================================================================

设计方案说明：
1. 设计意图 (Design Intent)：
   定义 Universal LLM Reliability Adapter 中间件的输入契约 (AdapterInput) 与输出契约 (AdapterOutput)。
   上层 Agent Runtime (如 Critic 审查、Plan 引擎、Tool Dispatcher) 统一通过 AdapterInput
   提交请求，并通过 AdapterOutput 接收类型安全、具备完整审计轨迹 (recovery_path) 的最终响应。
2. 类与函数结构 (Class Structure)：
   - `RecoveryPathStep`: 单步故障恢复审计轨迹记录对象。
   - `AdapterInput[T]`: 泛型输入契约，包含原始 Prompt、目标 Pydantic Schema、配置与上下文。
   - `AdapterOutput[T]`: 泛型输出契约，包含成功标志、解析提纯后的 Typed Object 数据、原始文本及追踪数据。
3. 关键数据流 (Data Flow)：
   Upper Runtime ➔ AdapterInput ➔ Driver/Pipeline/Recovery ➔ AdapterOutput ➔ Upper Runtime
4. 核心用例考量 (Test Case Intent)：
   - 验证泛型 T 的类型绑定与反序列化安全性，确保任何传入的 Pydantic 模型均能得到 100% 类型安全的输出。
==============================================================================
"""

import time
from typing import Any, Dict, Generic, List, Optional, Type, TypeVar
from pydantic import BaseModel, Field

from ..config import ReliabilityConfig

# 泛型变量：表示期望大模型提取并通过校验的目标 Pydantic 模型
T = TypeVar("T", bound=BaseModel)


class RecoveryPathStep(BaseModel):
    """
    故障恢复链路上的单步审计节点
    记录在处理 LLM 输出过程中经历的 Pipeline 状态或恢复手段
    """
    timestamp: float = Field(default_factory=time.time, description="步骤触发时间戳")
    action: str = Field(..., description="恢复动作 (如 NORMAL, LOCAL_REPAIR_SUCCESS, REPROMPT_RETRY, DEGRADE_FALLBACK)")
    detail: str = Field(default="", description="详细说明或捕获的异常信息")


class AdapterInput(BaseModel, Generic[T]):
    """
    通用中间件输入契约
    """
    prompt: str = Field(
        ...,
        description="提交给 LLM 的主提示词 (User Prompt / System Prompt)"
    )
    
    response_model: Type[T] = Field(
        ...,
        description="期望 LLM 返回并经过 Validator 强校验的目标 Pydantic 类型"
    )
    
    system_instruction: Optional[str] = Field(
        default=None,
        description="可选的系统级指令 (System Prompt)"
    )
    
    config: ReliabilityConfig = Field(
        default_factory=ReliabilityConfig,
        description="针对本次调用的策略配置参数"
    )
    
    context: Dict[str, Any] = Field(
        default_factory=dict,
        description="透传的运行时上下文 (如 task_id, session_id, user_id 等)"
    )
    
    fallback_factory: Optional[Any] = Field(
        default=None,
        description="可选的兜底工厂函数或默认对象，当 Level 3 熔断触发时调用"
    )


class AdapterOutput(BaseModel, Generic[T]):
    """
    通用中间件输出契约
    """
    success: bool = Field(
        ...,
        description="指示本次调用是否最终提取并校验成功"
    )
    
    data: Optional[T] = Field(
        default=None,
        description="提取提纯后的强类型目标数据对象 (仅在 success=True 时有效)"
    )
    
    raw_response: str = Field(
        default="",
        description="LLM 原始返回的纯文本字符串"
    )
    
    attempts: int = Field(
        default=0,
        ge=0,
        description="实际执行的请求/解析尝试总次数 (1 代表一次直接成功)"
    )
    
    recovery_path: List[RecoveryPathStep] = Field(
        default_factory=list,
        description="恢复链路审计轨迹列表 (记录经历的修补与重试步骤)"
    )
    
    error_message: Optional[str] = Field(
        default=None,
        description="若调用失败，包含具体的根因错误提示"
    )

    def add_trace_step(self, action: str, detail: str = "") -> None:
        """步骤块方法：向审计轨迹中追加一条节点记录"""
        self.recovery_path.append(RecoveryPathStep(action=action, detail=detail))
