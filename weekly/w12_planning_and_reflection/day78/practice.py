"""
Day 78 练习模版: Plan-and-Execute 强类型解耦与上下文变量映射架构

【系统设计方案说明】
1. 设计意图 (Design Intent):
   构建生产级 Plan-and-Execute 架构引擎，解耦 Planner (任务拆解) 与 Executor (单步执行)。
   引入 Pydantic 强类型 Plan 拓扑、上下文变量依赖映射 (Variable Directing) 与步数预算熔断机制 (Step Quota Guard)，
   根治传统 ReAct 范式中的 Goal Drift (目标漂移) 与死循环崩溃隐患。

2. 类与函数结构 (Class & Function Architecture):
   - TaskStep: Pydantic 模型，定义单个步骤的强类型契约 (step_id, title, tool_name, input_args, status)。
   - Plan: Pydantic 模型，管理 TaskStep 列表与拓扑结构。
   - VariableDirectingEngine: 上下文变量映射微引擎，负责解析 {step_X_output} 占位符并替换为历史 Observation。
   - PlanAndExecuteState: TypedDict 状态容器，维护输入目标、Plan 拓扑、completed_steps 历史映射与步数计数器。
   - PlannerNode: 调度 LLM 将用户目标解析拆解为强类型 Plan。
   - ExecutorNode: 读取下一个待执行 Step，解析变量并触发实际工具调用。
   - StepQuotaGuard: 步数预算熔断器，记录执行轮次与任务指纹，抛出熔断异常。

3. 关键数据流流向 (Data Flow):
   User Goal ➔ PlannerNode ➔ Pydantic Plan ➔ Router Loop ➔ VariableDirectingEngine ➔ ExecutorNode ➔ ObservationMap ➔ SummarizerNode
"""

import re
import hashlib
from typing import Dict, List, Any, Optional, Literal, TypedDict
from pydantic import BaseModel, Field

# 从公共工具加载 API 凭证与配置 (规则 12 & 20)
from weekly.w04_prompt_and_http.utils import load_env_file, LLMClient

# 加载环境变量
load_env_file()


# ==========================================
# 1. 强类型 Pydantic Schema 契约
# ==========================================

class TaskStep(BaseModel):
    """
    单步任务强类型数据契约
    """
    step_id: int = Field(description="步骤唯一数字标识，从 1 开始递增")
    title: str = Field(description="步骤简短摘要")
    tool_name: str = Field(description="调用的工具名称，如 scan_code, audit_ast, run_linter")
    input_args: Dict[str, Any] = Field(
        default_factory=dict, 
        description="工具入参字典，支持占位符如 {'code': '{step_1_output}'}"
    )
    status: Literal["PENDING", "COMPLETED", "FAILED"] = Field(
        default="PENDING", 
        description="当前步骤的物理执行状态"
    )


class Plan(BaseModel):
    """
    全局计划拓扑容器
    """
    steps: List[TaskStep] = Field(description="按逻辑依赖排序的步骤列表")


class PlanAndExecuteState(TypedDict):
    """
    LangGraph 状态图全局 TypedDict 状态容器
    """
    input_goal: str
    plan: Optional[Plan]
    completed_steps: Dict[int, str]  # step_id -> 原始 Observation 文本
    current_step_index: int
    execution_counter: int  # 累计执行步数 (用于熔断)
    fingerprint_history: List[str]  # 记录已发派任务的 SHA256 指纹


# ==========================================
# 2. 异常定义
# ==========================================

class StepQuotaExceededError(Exception):
    """当执行步数超过设定的最大预算额度时抛出"""
    pass


class PlanLoopDetectedError(Exception):
    """当识别到重复派发相同任务指纹的死循环时抛出"""
    pass


# ==========================================
# 3. 核心微引擎实现 (学员 TODO 练习区)
# ==========================================

class VariableDirectingEngine:
    """
    上下文变量依赖映射微引擎
    负责扫描入参字典中的 {step_X_output} 占位符，并用 completed_steps 中的真实 Observation 进行正则替换。
    """

    @staticmethod
    def resolve_variables(input_args: Dict[str, Any], completed_steps: Dict[int, str]) -> Dict[str, Any]:
        """
        解析并替换 input_args 字典中的变量占位符。

        :param input_args: 包含占位符的原始入参字典，如 {"file": "app.py", "content": "{step_1_output}"}
        :param completed_steps: 已完成步骤的 Observation 映射，如 {1: "def main(): pass"}
        :return: 变量替换后的崭新入参字典
        :raises KeyError: 如果引用的 step_X 在 completed_steps 中不存在
        """
        # TODO: 学员需实现占位符识别与替换逻辑
        # 提示: 使用 re.sub 扫描 r"\{step_(\d+)_output\}"
        raise NotImplementedError("TODO: 请实现 VariableDirectingEngine.resolve_variables 变量映射逻辑")


class StepQuotaGuard:
    """
    防死循环与步数预算熔断控制器
    """

    def __init__(self, max_budget: int = 10):
        """
        :param max_budget: 允许执行的最大超步上限
        """
        self.max_budget = max_budget

    def check_and_record(self, state: PlanAndExecuteState, current_step: TaskStep) -> str:
        """
        检查步数预算与任务指纹是否超限/死循环，并返回生成的任务指纹 SHA256。

        :param state: 全局 State 容器
        :param current_step: 即将执行的 TaskStep
        :return: 当前任务计算出的 SHA256 指纹
        :raises StepQuotaExceededError: 当 execution_counter >= max_budget 时
        :raises PlanLoopDetectedError: 当相同的任务指纹连续出现超过 2 次时
        """
        # TODO: 学员需实现步数检查与任务指纹哈希去重逻辑
        # 提示: 将 f"{current_step.tool_name}:{current_step.input_args}" 进行 hashlib.sha256 计算
        raise NotImplementedError("TODO: 请实现 StepQuotaGuard.check_and_record 熔断检查逻辑")


# ==========================================
# 3. 工具注册表 (Tool Registry & Schema)
# ==========================================

AVAILABLE_TOOLS_REGISTRY = [
    {
        "name": "read_code_file",
        "description": "读取指定路径的本地代码文件全文文本内容。",
        "parameters": {
            "file_path": "string (必填): 目标文件的物理路径，例如 'app.py'"
        }
    },
    {
        "name": "ast_scan_security",
        "description": "使用 Python 内置 AST 语法树解析源码，扫描 SQL 注入 (CWE-89) 等安全漏洞。",
        "parameters": {
            "code_content": "string (必填): 待扫描的代码文本，可填 '{step_X_output}'"
        }
    },
    {
        "name": "generate_fix_patch",
        "description": "调用高级 LLM 安全专家，根据 AST 漏洞诊断报告生成修复后的代码补丁。",
        "parameters": {
            "code_content": "string (必填): 包含漏洞的原始代码文本，可填 '{step_X_output}'",
            "audit_report": "string (必填): AST 安全扫描报告，可填 '{step_Y_output}'"
        }
    }
]


class PlannerNode:
    """
    宏观规划器节点 (Planner Node)
    驱动大模型解析复杂目标，生成强类型 Pydantic Plan
    """

    def __init__(self, tools_registry: Optional[List[Dict[str, Any]]] = None):
        self.client = LLMClient()
        self.tools_registry = tools_registry or AVAILABLE_TOOLS_REGISTRY

    def plan_task(self, goal: str) -> Plan:
        """
        调用 LLM 生成结构化 Plan 拓扑

        :param goal: 用户输入的复杂长任务描述
        :return: 解析后的 Pydantic Plan 对象
        """
        # TODO: 学员需实现构造 System Prompt 与结构化提取 Plan 的逻辑
        raise NotImplementedError("TODO: 请实现 PlannerNode.plan_task 大模型规划逻辑")


class ExecutorNode:
    """
    微观执行器节点 (Executor Node)
    模拟真实工具环境执行单步任务
    """

    @staticmethod
    def execute_step(step: TaskStep, resolved_args: Dict[str, Any]) -> str:
        """
        模拟触发具体工具调用并返回 Observation 结果

        :param step: 目标 TaskStep
        :param resolved_args: 已完成变量映射的物理入参
        :return: 工具执行输出字符串 (Observation)
        """
        # TODO: 学员需实现仿真工具路由与执行逻辑
        raise NotImplementedError("TODO: 请实现 ExecutorNode.execute_step 工具执行逻辑")


# ==========================================
# 4. 调试主入口 (规则 1 & 6)
# ==========================================

if __name__ == "__main__":
    print("=" * 70)
    print("Day 78 练习验证: Plan-and-Execute 强类型解耦与上下文变量映射引擎")
    print("=" * 70)

    # 1. 模拟输入测试目标
    sample_goal = "对 app.py 进行 AST 静态安全扫描，若发现 SQL 注入风险，生成修复方案。"

    print(f"\n[测试目标]: {sample_goal}\n")

    try:
        # 尝试实例化与运行 PlannerNode
        planner = PlannerNode()
        print("[1] 尝试拉起 PlannerNode 生成结构化 Plan...")
        plan = planner.plan_task(sample_goal)
        print(f"✅ 生成 Plan 成功! 包含 {len(plan.steps)} 个步骤:")
        for s in plan.steps:
            print(f"  - Step {s.step_id}: {s.title} (Tool: {s.tool_name})")

    except NotImplementedError as e:
        print(f"\n⚠️  [拦截到未实现 TODO]: {e}")
        print("👉 请打开 `practice.py` 补充核心逻辑，或参考同目录下的标准答案代码。")
    except Exception as e:
        print(f"\n❌ [运行发生异常]: {e}")
