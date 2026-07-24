"""
Day 82 练习模版: 动态计划重构 (Dynamic Re-planning) 分支控制

【系统设计方案说明】
1. 设计意图 (Design Intent):
   构建生产级动态计划重构 (Dynamic Re-planning) 引擎。解决传统的 Plan-and-Execute 架构在遇到外部 API 离线
   (API_OFFLINE) 或运行期非预期 Observation 时死守静态计划撞墙崩溃的问题。
   通过在状态图中引入 `ReplannerGuard` 观察路由边与 `ReplannerNode` 动态重规划节点，
   能够在运行期捕获环境偏差，废弃已知失败步骤并重新生成带降级方案 (如读取本地 Mock 缓存) 的剩余计划拓扑。

2. 类与函数结构 (Class & Function Architecture):
   - TaskStep: Pydantic 模型，定义强类型任务步骤契约 (step_id, tool_name, description, status, arguments)。
   - ObservationPayload: Pydantic 模型，定义工具执行观察结果契约 (status, result_data, raw_error)。
   - DynamicReplanState: TypedDict 状态容器，维护任务需求、已执行步骤、待执行剩余步骤、最新 Observation 与重规划计数器。
   - PlannerNode: 初始计划生成节点，对多阶段复杂任务进行步骤分解。
   - MockToolExecutor: 模拟工具执行器，模拟主 API 离线 (API_OFFLINE) 与降级缓存工具执行。
   - ReplannerNode: 动态重规划节点，结合已执行步骤与离线报错上下文，重新生成降级剩余计划。
   - ReplannerGuard: 条件路由控制器，精准判断放行继续执行 (TO_EXECUTOR)、跳转重规划 (TO_REPLANNER) 或熔断拦截 (TO_FALLBACK)。

3. 关键数据流流向 (Data Flow):
   User Requirement ➔ PlannerNode ➔ Initial Plan: [Step 1, Step 2 (QueryPrimaryAPI), Step 3]
     ➔ Executor ➔ Step 1 (SUCCESS) ➔ Executor ➔ Step 2 (Returns API_OFFLINE)
     ➔ ReplannerGuard ➔ (Detect API_OFFLINE) ➔ ReplannerNode (Input: Executed + Error)
     ➔ Regenerated Plan: [Step 2_Fallback (ReadLocalMockCache), Step 3]
     ➔ Executor ➔ Step 2_Fallback (SUCCESS) ➔ Step 3 (SUCCESS) ➔ ReplannerGuard ➔ END Node

4. 核心用例设计意图 (Test Case Design Intent):
   选取“分布式多源政企数据与实时行情查询报告生成”作为验证场景：
   - 验证点 1：测试初始 Planner 分解出包含 `QueryPrimaryAPI` 的静态三步计划拓扑。
   - 验证点 2：测试 MockToolExecutor 在执行 `QueryPrimaryAPI` 时故意返回 `API_OFFLINE` 状态。
   - 验证点 3：测试 ReplannerGuard 能否精准捕捉 `API_OFFLINE` 并将控制流路由给 ReplannerNode。
   - 验证点 4：测试 ReplannerNode 能否生成包含 `ReadLocalMockCache` 的降级新计划，替换 `remaining_steps` 并最终成功通关。
"""

import asyncio
from typing import Dict, List, Any, Optional, Literal, TypedDict
from pydantic import BaseModel, Field

# 从公共工具加载 API 凭证与配置 (规则 12 & 20)
from weekly.w04_prompt_and_http.utils import load_env_file, LLMClient

# 加载环境变量
load_env_file()


# ==========================================
# 1. 强类型 Schema 与 State 容器契约
# ==========================================

class TaskStep(BaseModel):
    """
    强类型任务步骤契约
    """
    step_id: str = Field(description="步骤唯一 ID，如 step_1, step_2_fallback")
    tool_name: str = Field(description="拟调用的工具名称")
    description: str = Field(description="步骤的具体描述")
    status: Literal["PENDING", "COMPLETED", "FAILED", "REPLANNED"] = Field(default="PENDING", description="步骤状态")
    arguments: Dict[str, Any] = Field(default_factory=dict, description="步骤入参或占位符")


class ObservationPayload(BaseModel):
    """
    工具执行观察结果契约
    """
    status: Literal["SUCCESS", "API_OFFLINE", "ERROR"] = Field(description="观察结果状态")
    result_data: Any = Field(default=None, description="工具返回的实际数据")
    raw_error: str = Field(default="", description="原始错误日志")


class ReplannedPlanPayload(BaseModel):
    """
    Replanner 重规划输出的降级剩余步骤 Payload
    """
    rationale: str = Field(description="计划重构的原因与降级策略分析")
    remaining_steps: List[TaskStep] = Field(description="更新后的降级剩余 TaskStep 列表")


class DynamicReplanState(TypedDict):
    """
    状态图全局 TypedDict 容器
    """
    user_requirement: str
    executed_steps: List[Dict[str, Any]]  # 已执行完成的步骤及 Observation 记录
    remaining_steps: List[TaskStep]        # 当前待执行的剩余步骤队列
    latest_observation: Optional[ObservationPayload]
    replan_counter: int                    # 动态重规划次数计数器
    is_success: bool


# ==========================================
# 2. 核心微引擎架构 (学员 TODO 练习区)
# ==========================================

class MockToolExecutor:
    """
    模拟工具执行器：模拟物理 API 调用的反馈与离线降级场景
    """

    def execute_tool(self, step: TaskStep) -> ObservationPayload:
        """
        根据 TaskStep 的 tool_name 执行对应的模拟逻辑
        """
        # TODO: 学员需实现模拟工具执行逻辑
        # 提示: 如果 tool_name == "QueryPrimaryAPI"，模拟返回 ObservationPayload(status="API_OFFLINE", ...)
        # 提示: 如果 tool_name == "ReadLocalMockCache"，返回 ObservationPayload(status="SUCCESS", ...)
        raise NotImplementedError("TODO: 请实现 MockToolExecutor.execute_tool 模拟工具执行逻辑")


class PlannerNode:
    """
    Planner 初始计划生成节点
    """

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.client = llm_client or LLMClient()

    async def generate_initial_plan(self, requirement: str) -> List[TaskStep]:
        """
        为原始需求生成初始的 TaskStep 列表
        """
        # TODO: 学员需实现初始计划分解逻辑
        raise NotImplementedError("TODO: 请实现 PlannerNode.generate_initial_plan 初始计划生成逻辑")


class ReplannerNode:
    """
    Replanner 动态重规划节点：结合失败上下文重构降级剩余计划
    """

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.client = llm_client or LLMClient()

    async def replan(
        self,
        requirement: str,
        executed_steps: List[Dict[str, Any]],
        failed_step: TaskStep,
        observation: ObservationPayload
    ) -> ReplannedPlanPayload:
        """
        调用 LLM 重新规划替代的降级剩余步骤列表
        """
        # TODO: 学员需实现动态重规划逻辑
        raise NotImplementedError("TODO: 请实现 ReplannerNode.replan 动态重规划逻辑")


class ReplannerGuard:
    """
    动态重规划路由控制器
    """

    def __init__(self, max_replans: int = 3):
        self.max_replans = max_replans

    def evaluate_routing(self, state: DynamicReplanState) -> str:
        """
        判断下一步路由流向

        :return: "TO_EXECUTOR" | "TO_REPLANNER" | "TO_END" | "TO_FALLBACK"
        """
        # TODO: 学员需实现条件路由判定逻辑
        # 提示: 检查 state["latest_observation"].status == "API_OFFLINE" -> TO_REPLANNER
        # 提示: 检查 state["replan_counter"] >= self.max_replans -> TO_FALLBACK
        raise NotImplementedError("TODO: 请实现 ReplannerGuard.evaluate_routing 路由判定逻辑")


# ==========================================
# 3. 调试主入口 (规则 6 统一规范)
# ==========================================

async def main():
    print("=" * 60)
    print("🚀 Day 82 练习：动态计划重构 (Dynamic Re-planning) 引擎调试")
    print("=" * 60)

    # 初始状态
    state: DynamicReplanState = {
        "user_requirement": "查询主 API 获取实时数据并生成财报总结，若 API 离线则降级读取 Mock 缓存。",
        "executed_steps": [],
        "remaining_steps": [],
        "latest_observation": None,
        "replan_counter": 0,
        "is_success": False
    }

    guard = ReplannerGuard(max_replans=3)
    executor = MockToolExecutor()

    try:
        # 步骤 1: 测试路由逻辑
        next_step = guard.evaluate_routing(state)
        print(f"初始路由判定: {next_step}")
    except NotImplementedError as e:
        print(f"\n[TODO 拦截提示] {e}")

    try:
        # 步骤 2: 测试模拟工具执行
        step = TaskStep(step_id="step_2", tool_name="QueryPrimaryAPI", description="请求主行情 API")
        obs = executor.execute_tool(step)
        print(f"模拟 API 执行观察结果: status={obs.status}")
    except NotImplementedError as e:
        print(f"[TODO 拦截提示] {e}")

    print("\n💡 提示: 请在练习中参照 dynamic_replanner_engine.py 填空实现上述 TODO 模块。")


if __name__ == "__main__":
    asyncio.run(main())
