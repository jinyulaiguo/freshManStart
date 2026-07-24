"""
Day 84 综合实战: 强类型 TaskStep 与 Plan Schema 契约

【设计说明】
定义 Planner 生成与 Executor 执行所依赖的强类型 Pydantic Schema。
包含 TaskStep、TaskPlanPayload 等模型，支持带依赖约束、变量占位符与执行状态追溯。
"""

from typing import List, Dict, Any, Optional, Literal
from pydantic import BaseModel, Field


class TaskStep(BaseModel):
    """
    强类型任务步骤模型
    """
    id: str = Field(description="步骤唯一标识，如 step1, step2")
    description: str = Field(description="具体的执行指令或搜索查询需求")
    task_type: Literal["search", "rag", "database", "analyze"] = Field(
        description="任务类型: search(网络搜索), rag(向量数据库检索), database(本地缓存/离线库), analyze(逻辑分析与整合)"
    )
    dependency: List[str] = Field(default_factory=list, description="依赖的前置 step id 列表，如 ['step1']")
    input_vars: List[str] = Field(default_factory=list, description="所需的变量占位符列表，如 ['#market_data']")
    output_var: str = Field(description="输出结果保存的变量名称，如 'market_data'")
    status: Literal["PENDING", "COMPLETED", "FAILED"] = Field(default="PENDING", description="执行状态")


class TaskPlanPayload(BaseModel):
    """
    Planner LLM 结构化输出契约
    """
    rationale: str = Field(default="", description="任务拆解逻辑与整体规划意图")
    steps: List[TaskStep] = Field(description="强类型任务步骤拓扑数组")
