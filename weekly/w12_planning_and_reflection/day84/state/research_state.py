"""
Day 84 综合实战: State 容器契约定义

【系统设计方案说明】
1. 设计意图 (Design Intent):
   定义生产级 Research Agent 的全局状态容器 (ResearchState)。
   支持 Plan-and-Execute、ReWOO 并行变量回填、Reflexion 反思记忆迭代以及 Anti-Hallucination 检验结果传递。
   使用 typing.Annotated 搭配 operator/reducer 明确处理状态追加与合并，防止并发竞争冲突。

2. 结构说明:
   - ResearchState: TypedDict 状态容器，维护 Task Plan、Observation 字典、ReWOO 变量表、草稿与各种审查报告。
"""

import operator
from typing import Dict, List, Any, Optional, TypedDict, Annotated
from pydantic import BaseModel, Field


class CriticResult(BaseModel):
    """Critic 审查结果契约"""
    status: str = Field(description="审查结论: PASS 或 REJECT")
    score: float = Field(default=0.0, description="评分 0-100")
    reason: str = Field(default="", description="拒绝原因或修改建议")
    missing_sections: List[str] = Field(default_factory=list, description="缺失的章节")


class VerificationResult(BaseModel):
    """防幻觉 NLI 校对结论契约"""
    overall_status: str = Field(description="校验结论: PASS 或 HALLUCINATION_DETECTED")
    unsupported_claims: List[str] = Field(default_factory=list, description="未得支持或存在矛盾的断言")
    correction_guidance: str = Field(default="", description="纠偏提示词与删除指导")


class ResearchState(TypedDict, total=False):
    """
    Research Agent 全局 LangGraph 状态容器
    """
    # 用户输入与原始需求
    user_query: str

    # Planner 生成的强类型 TaskStep 列表 (支持全量覆盖更新)
    plan: List[Dict[str, Any]]

    # 当前执行指针与控制参数
    current_step: int
    loop_counter: int
    planner_call_count: int

    # 观察结果字典: {step_id: result_data}
    observations: Annotated[Dict[str, Any], operator.or_]

    # ReWOO 变量回填字典: {var_name: resolved_value}
    variables: Annotated[Dict[str, Any], operator.or_]

    # 上下文 Prompt 缓存
    context_prompt: str

    # 报告草稿与最终生成物
    draft_report: str
    final_report: str

    # 质量控制与反思机制
    critic_result: Optional[CriticResult]
    reflections: Annotated[List[str], operator.add]
    verification_result: Optional[VerificationResult]

    # 运行期状态指标
    is_completed: bool
    error_message: Optional[str]
