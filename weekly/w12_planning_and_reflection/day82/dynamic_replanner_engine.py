"""
Day 82 参考标准答案: 动态计划重构 (Dynamic Re-planning) 分支控制

【系统设计方案说明】
1. 设计意图 (Design Intent):
   构建生产级动态计划重构 (Dynamic Re-planning) 引擎。解决传统的 Plan-and-Execute 架构在遇到外部 API 离线
   (API_OFFLINE) 或运行期非预期 Observation 时死守静态计划撞墙崩溃的问题。
   通过在状态图中引入 `ReplannerGuard` 观察路由边与 `ReplannerNode` 动态重规划节点，
   能够在运行期捕获环境偏差，废弃已知失败步骤并重新生成带降级方案 (如读取本地 Mock 缓存) 的剩余计划拓扑。

2. 类与函数结构 (Class & Function Architecture):
   - TaskStep: Pydantic 模型，定义强类型任务步骤契约 (step_id, tool_name, description, status, arguments)。
   - ObservationPayload: Pydantic 模型，定义工具执行观察结果契约 (status, result_data, raw_error)。
   - ReplannedPlanPayload: Pydantic 模型，定义重规划输出的降级剩余步骤 Payload (rationale, remaining_steps)。
   - DynamicReplanState: TypedDict 状态容器，维护全局需求、已执行步骤、待执行剩余步骤队列、最新 Observation 与计数器。
   - MockToolExecutor: 模拟工具执行器，模拟主 API 离线 (API_OFFLINE) 错误与本地 Mock 缓存读取降级。
   - PlannerNode: 初始计划生成节点，分解多阶段任务拓扑。
   - ReplannerNode: 动态重规划节点，结合已执行历史与离线报错上下文，重新生成降级剩余计划。
   - ReplannerGuard: 条件路由控制器，精准控制继续执行 (TO_EXECUTOR)、跳转重规划 (TO_REPLANNER)、结束 (TO_END) 或熔断拦截 (TO_FALLBACK)。
   - DynamicReplannerEngine: 主调度引擎，协同各节点驱动带动态分支重构的控制流循环。

3. 关键数据流流向 (Data Flow):
   User Requirement ➔ PlannerNode ➔ Initial Plan: [Step 1 (QueryCompanyBasicInfo), Step 2 (QueryPrimaryAPI), Step 3 (SummarizeReport)]
     ➔ Executor ➔ Step 1 (SUCCESS) ➔ Executor ➔ Step 2 (QueryPrimaryAPI returns API_OFFLINE)
     ➔ ReplannerGuard ➔ (Detect API_OFFLINE) ➔ ReplannerNode (Analyze executed + error context)
     ➔ Generated Fallback Plan: [Step 2_fallback (ReadLocalMockCache), Step 3 (SummarizeReport)]
     ➔ Update State["remaining_steps"] ➔ Executor ➔ Step 2_fallback (SUCCESS) ➔ Step 3 (SUCCESS)
     ➔ ReplannerGuard ➔ END Node (Return Valid Report)

4. 核心用例设计意图 (Test Case Design Intent):
   选取“分布式多源政企数据与实时行情查询报告生成”作为验证场景：
   - 验证点 1：测试初始 Planner 分解出包含 `QueryPrimaryAPI` 的静态三步计划拓扑。
   - 验证点 2：测试 MockToolExecutor 在执行 `QueryPrimaryAPI` 时故意返回 `API_OFFLINE` 状态。
   - 验证点 3：测试 ReplannerGuard 能否精准捕捉 `API_OFFLINE` 并将控制流路由给 ReplannerNode。
   - 验证点 4：测试 ReplannerNode 能否生成包含 `ReadLocalMockCache` 的降级新计划，替换 `remaining_steps` 并最终成功通关。
"""

import json
import asyncio
from typing import Dict, List, Any, Optional, Literal, TypedDict
from pydantic import BaseModel, Field

# 从公共工具与中间件导入 API 与结构化提取功能 (规则 12, 20 & 21)
from weekly.w04_prompt_and_http.utils import load_env_file, LLMClient
from middlewares.llm_reliability_adapter import parse_structured

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
    tool_name: str = Field(description="拟调用的工具名称，如 QueryPrimaryAPI, ReadLocalMockCache, SummarizeReport")
    description: str = Field(description="步骤的具体执行说明")
    status: Literal["PENDING", "COMPLETED", "FAILED", "REPLANNED"] = Field(default="PENDING", description="步骤当前状态")
    arguments: Dict[str, Any] = Field(default_factory=dict, description="步骤入参或变量占位符")


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
# 2. 核心微引擎实现
# ==========================================

class MockToolExecutor:
    """
    模拟工具执行器：模拟物理 API 调用的反馈与离线降级场景
    """

    def execute_tool(self, step: TaskStep) -> ObservationPayload:
        """
        根据 TaskStep 的 tool_name 执行对应的模拟逻辑
        """
        print(f"🛠️ [MockToolExecutor] 正在执行工具 '{step.tool_name}' ({step.description})...")

        if step.tool_name == "QueryCompanyBasicInfo":
            return ObservationPayload(
                status="SUCCESS",
                result_data={"company_name": "Acme Industrial Corp", "registration_id": "REG-889012"},
                raw_error=""
            )
        elif step.tool_name == "QueryPrimaryAPI":
            # 故意模拟主行情/财务 API 离线服务挂掉场景
            return ObservationPayload(
                status="API_OFFLINE",
                result_data=None,
                raw_error="HTTP 503 Service Unavailable: Primary Financial Gateway endpoint is offline."
            )
        elif step.tool_name == "ReadLocalMockCache":
            # 降级备用本地数据库 / Mock 缓存
            return ObservationPayload(
                status="SUCCESS",
                result_data={"cached_revenue": "$12.5M", "data_source": "LocalFallbackMockDB", "timestamp": "2026-07-24"},
                raw_error=""
            )
        elif step.tool_name == "SummarizeReport":
            return ObservationPayload(
                status="SUCCESS",
                result_data="[分析报告生成完成]: 结合 Acme Industrial Corp 基础信息与 LocalFallbackMockDB 降级数据汇总完毕。",
                raw_error=""
            )
        else:
            return ObservationPayload(
                status="ERROR",
                result_data=None,
                raw_error=f"Unknown tool name: {step.tool_name}"
            )


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
        # 初始硬编码标准三步任务拓扑，模拟开局规划
        return [
            TaskStep(
                step_id="step_1",
                tool_name="QueryCompanyBasicInfo",
                description="查询企业基本工商注册信息"
            ),
            TaskStep(
                step_id="step_2",
                tool_name="QueryPrimaryAPI",
                description="请求线上主 API 获取企业实时财报与行情数据"
            ),
            TaskStep(
                step_id="step_3",
                tool_name="SummarizeReport",
                description="汇总各步骤观察数据并生成研报"
            )
        ]


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
        prompt = f"""你是一名高级 Agent 动态重规划引擎 (Dynamic Replanner)。
在执行 Plan-and-Execute 任务时，外部环境发生了非预期偏差（API 离线）。

【原始任务需求】:
{requirement}

【已成功执行的步骤】:
{json.dumps(executed_steps, ensure_ascii=False, indent=2)}

【刚刚执行失败崩溃的步骤】:
- 步骤 ID: {failed_step.step_id}
- 尝试工具: {failed_step.tool_name}
- 报错 Observation: {observation.raw_error} (状态: {observation.status})

【可用备用工具库】:
- ReadLocalMockCache: 读取本地离线 Mock 数据缓存以替代不可用的 Primary API。
- SummarizeReport: 汇总当前所有可用数据生成终版报告。

请评估受影响的未执行步骤，输出重构后的降级 `remaining_steps` 列表。
【极重要约束】:
1. 请直接输出符合 JSON 结构的文本，严禁包含 <think> 标签！
2. 必须包含字段 `rationale` 和 `remaining_steps`。
"""
        messages = [
            {"role": "system", "content": "你是一名精通动态计划重构与降级路由的专家。请输出 JSON 强类型重规划 Payload。"},
            {"role": "user", "content": prompt}
        ]

        try:
            raw_text = await self.client.request_llm(messages=messages, temperature=0.2)
            replanned: ReplannedPlanPayload = parse_structured(
                raw_text=raw_text,
                response_model=ReplannedPlanPayload
            )
            return replanned
        except Exception as e:
            print(f"⚠️ [ReplannerNode] 重规划解析异常 ({type(e).__name__})，触发保底降级逻辑。")
            # 静态降级保底 Plan
            return ReplannedPlanPayload(
                rationale=f"主 API 离线 ({observation.raw_error})，触发本地 Mock 缓存降级策略。",
                remaining_steps=[
                    TaskStep(
                        step_id="step_2_fallback",
                        tool_name="ReadLocalMockCache",
                        description="[降级方案] 读取本地 Mock 数据库获取缓存财报"
                    ),
                    TaskStep(
                        step_id="step_3",
                        tool_name="SummarizeReport",
                        description="基于降级数据生成最终总结"
                    )
                ]
            )


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
        # 1. 检查最新工具观察结果是否为 API 离线
        last_obs = state["latest_observation"]
        if last_obs and last_obs.status == "API_OFFLINE":
            if state["replan_counter"] >= self.max_replans:
                return "TO_FALLBACK"
            return "TO_REPLANNER"

        # 2. 检查是否仍有待执行的剩余步骤
        if not state["remaining_steps"]:
            return "TO_END"

        return "TO_EXECUTOR"


class DynamicReplannerEngine:
    """
    动态重规划引擎主控调度器
    """

    def __init__(self, max_replans: int = 3):
        self.planner = PlannerNode()
        self.replanner = ReplannerNode()
        self.executor = MockToolExecutor()
        self.guard = ReplannerGuard(max_replans=max_replans)

    async def run(self, requirement: str) -> DynamicReplanState:
        """
        执行带动态分支重构的控制流
        """
        state: DynamicReplanState = {
            "user_requirement": requirement,
            "executed_steps": [],
            "remaining_steps": [],
            "latest_observation": None,
            "replan_counter": 0,
            "is_success": False
        }

        print("=" * 70)
        print("🚀 启动动态计划重构 (Dynamic Re-planning) 引擎")
        print(f"📋 任务需求: {requirement}")
        print("=" * 70)

        # 步骤 1: Planner 生成初始计划
        initial_plan = await self.planner.generate_initial_plan(requirement)
        state["remaining_steps"] = initial_plan
        print("\n📅 [PlannerNode] 初始计划拓扑拆解完成:")
        for step in state["remaining_steps"]:
            print(f"  - [{step.step_id}] {step.tool_name}: {step.description}")

        # 步骤 2: 控制流主循环
        while True:
            route = self.guard.evaluate_routing(state)

            if route == "TO_END":
                state["is_success"] = True
                print("\n🎉 [DynamicReplannerEngine] 所有步骤执行完毕！任务收敛成功。")
                break

            elif route == "TO_FALLBACK":
                state["is_success"] = False
                print(f"\n⚠️ [DynamicReplannerEngine] 达到最大重规划上限 ({self.guard.max_replans} 次)，触发全局熔断拦截。")
                break

            elif route == "TO_REPLANNER":
                state["replan_counter"] += 1
                current_count = state["replan_counter"]
                print(f"\n⚡ [ReplannerGuard] 识别到 Observation 离线偏差 (API_OFFLINE)，强制路由跳转至 ReplannerNode！")
                print(f"🧠 [ReplannerNode] 正在根据最新离线报错进行动态重规划 (重构轮次 #{current_count})...")

                # 弹出刚刚失败的步骤
                failed_step = state["remaining_steps"].pop(0)

                # 调用 LLM 重新规划剩余步骤
                replanned_payload = await self.replanner.replan(
                    requirement=state["user_requirement"],
                    executed_steps=state["executed_steps"],
                    failed_step=failed_step,
                    observation=state["latest_observation"]
                )

                print(f"💡 [Replanner 策略说明]: {replanned_payload.rationale}")
                print(f"🔄 [更新后的剩余计划拓扑]:")
                for step in replanned_payload.remaining_steps:
                    print(f"  - [{step.step_id}] {step.tool_name}: {step.description}")

                # 用重构后的剩余步骤替换旧列表，并清除离线错误标记
                state["remaining_steps"] = replanned_payload.remaining_steps
                state["latest_observation"] = None

            elif route == "TO_EXECUTOR":
                # 从剩余队列弹出头节点步骤进行物理执行
                current_step = state["remaining_steps"].pop(0)
                print(f"\n▶️ [ExecutorNode] 开始执行步骤 [{current_step.step_id}] ({current_step.tool_name})...")

                obs = self.executor.execute_tool(current_step)
                state["latest_observation"] = obs

                if obs.status == "SUCCESS":
                    current_step.status = "COMPLETED"
                    state["executed_steps"].append({
                        "step_id": current_step.step_id,
                        "tool_name": current_step.tool_name,
                        "result_data": obs.result_data
                    })
                    print(f"✅ [ExecutorNode] 步骤 [{current_step.step_id}] 执行成功: {obs.result_data}")
                else:
                    current_step.status = "FAILED"
                    print(f"❌ [ExecutorNode] 步骤 [{current_step.step_id}] 物理执行失败: {obs.raw_error}")

        return state


# ==========================================
# 3. 运行入口 (规则 6 统一规范)
# ==========================================

async def main():
    requirement = "查询 Acme Industrial Corp 企业工商登记信息及实时财报行情，并生成最终研报。若实时财报 API 离线，请自适应重构计划并切换为本地 Mock 数据库。"

    engine = DynamicReplannerEngine(max_replans=3)
    final_state = await engine.run(requirement)

    print("\n" + "=" * 70)
    print("📊 动态计划重构引擎运行总结")
    print("=" * 70)
    print(f"任务成功标志: {final_state['is_success']}")
    print(f"动态重规划触发次数: {final_state['replan_counter']}")
    print(f"已成功执行步骤总数: {len(final_state['executed_steps'])}")
    print("\n已完成步骤明细:")
    for step in final_state["executed_steps"]:
        print(f"  - [{step['step_id']}] {step['tool_name']}: {step['result_data']}")


if __name__ == "__main__":
    asyncio.run(main())
