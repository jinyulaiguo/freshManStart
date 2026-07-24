"""
Day 81 练习模版: Reflexion 自我反思架构 — 从失败 Observation 中归纳纠错规则

【系统设计方案说明】
1. 设计意图 (Design Intent):
   构建生产级 Reflexion 自我反思自愈引擎 (Self-Healing Code Generation Engine)。
   通过在传统 Actor (生成器) 和 Evaluator (沙箱评估器) 之间引入独立的 Reflector (诊断反思器)，
   捕获代码在物理沙箱中运行失败时的 Exception Traceback，将其归纳总结为结构化的反思避坑规则 (ReflexionLog)，
   注入后续迭代的提示词记忆中。解决 Naive Retry 盲目重试导致模型在相同 Bug 上反复横跳、无法收敛的问题。

2. 类与函数结构 (Class & Function Architecture):
   - ReflexionLog: Pydantic 模型，定义结构化反思记忆契约 (error_type, root_cause_analysis, actionable_guidance)。
   - ExecutionResult: Dataclass/Pydantic 模型，存储沙箱执行结果 (success, output, error_message, trimmed_traceback)。
   - ReflexionState: TypedDict 状态容器，维护代码需求、当前代码草稿、运行结果、历史反思记忆数组与重试计数器。
   - SandboxEvaluator: 物理沙箱评估器，清洗堆栈并捕获 Python 运行异常。
   - ReflectorNode: 诊断反思节点，调用 LLM 析出结构化 ReflexionLog 并回填记忆库。
   - ActorNode: 代码生成节点，结合用户需求与历史反思记忆生成/修补代码。
   - ReflexionGuard: 条件路由控制器，控制通过放行、跳转反思或触发熔断拦截。

3. 关键数据流流向 (Data Flow):
   User Requirement ➔ ActorNode (Read Memory) ➔ Code Draft ➔ SandboxEvaluator
     ➔ (If Success) ➔ END Node (Return Valid Code)
     ➔ (If Fail & Loop < Max) ➔ ReflectorNode ➔ Generate ReflexionLog ➔ Append to State["reflections"] ➔ ActorNode
     ➔ (If Fail & Loop >= Max) ➔ Fallback Node (Escalation)

4. 核心用例设计意图 (Test Case Design Intent):
   选取“自动生成带有复杂数据过滤与统计逻辑的 Python 数据处理函数”作为验证场景：
   - 验证点 1：测试 Actor 在首次生成时代码包含未导入模块 (NameError) 或类型不匹配 (TypeError)。
   - 验证点 2：测试 SandboxEvaluator 能否物理捕获崩溃日志并提纯提取出核心 Traceback 信息。
   - 验证点 3：测试 ReflectorNode 能否将报错日志提纯归纳出清晰的 actionable_guidance 规则。
   - 验证点 4：测试 ActorNode 在第二轮生成中读取反思记忆后，能否精准绕开 Bug 并成功运行通过。
"""

import sys
import io
import traceback
import asyncio
from typing import Dict, List, Any, Optional, TypedDict
from pydantic import BaseModel, Field

# 从公共工具加载 API 凭证与配置 (规则 12 & 20)
from weekly.w04_prompt_and_http.utils import load_env_file, LLMClient

# 加载环境变量
load_env_file()


# ==========================================
# 1. 强类型 Schema 与 State 容器契约
# ==========================================

class ReflexionLog(BaseModel):
    """
    Reflector 诊断反思器生成的结构化经验 Payload
    """
    error_type: str = Field(description="捕获的异常类型 (如 NameError, TypeError, SyntaxError, AssertionError)")
    root_cause_analysis: str = Field(description="导致代码崩溃的根本原因深度剖析")
    actionable_guidance: str = Field(description="具体且可操作的下一轮代码生成避坑规则与修复指令")


class ExecutionResult(BaseModel):
    """
    沙箱环境执行评估结果
    """
    success: bool = Field(description="代码是否成功执行并通过断言")
    output: str = Field(default="", description="代码的标准输出 (stdout)")
    error_message: str = Field(default="", description="异常简明信息")
    trimmed_traceback: str = Field(default="", description="清洗提纯后的核心堆栈日志")


class ReflexionState(TypedDict):
    """
    LangGraph / 状态图全局 TypedDict 容器
    """
    user_requirement: str
    current_code: str
    execution_result: Optional[ExecutionResult]
    reflections: List[str]  # 历史积累的反思避坑规则字符串数组 (Episodic Memory)
    loop_counter: int      # 轮次计数器
    is_success: bool


# ==========================================
# 2. 核心微引擎架构 (学员 TODO 练习区)
# ==========================================

class SandboxEvaluator:
    """
    物理沙箱评估器：负责安全执行 Python 代码并提取提纯后的 Traceback
    """

    def clean_traceback(self, raw_tb: str) -> str:
        """
        提纯 Traceback 日志：过滤冗余系统堆栈，保留关键报错行与信息
        """
        # TODO: 学员需实现堆栈清洗逻辑
        raise NotImplementedError("TODO: 请实现 SandboxEvaluator.clean_traceback 堆栈清洗逻辑")

    def execute_code(self, code_str: str, test_assertion: Optional[str] = None) -> ExecutionResult:
        """
        在受限命名空间中物理执行代码并运行测试断言
        """
        # TODO: 学员需实现沙箱物理执行与 stdout/stderr/Traceback 捕获
        # 提示: 使用 io.StringIO 捕获 sys.stdout
        # 提示: 使用 exec(code_str, exec_globals) 执行
        raise NotImplementedError("TODO: 请实现 SandboxEvaluator.execute_code 沙箱执行逻辑")


class ReflectorNode:
    """
    Reflector 诊断反思节点：分析失败 Log 归纳生成 ReflexionLog
    """

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.client = llm_client or LLMClient()

    async def reflect(self, requirement: str, failed_code: str, exec_result: ExecutionResult) -> ReflexionLog:
        """
        调用 LLM 对失败代码与报错日志进行反思诊断，输出结构化 ReflexionLog
        """
        # TODO: 学员需实现调用 LLM 进行反思归纳的逻辑
        # 提示: 结合 requirement, failed_code, exec_result.trimmed_traceback 组装 Prompt
        raise NotImplementedError("TODO: 请实现 ReflectorNode.reflect 诊断反思逻辑")


class ActorNode:
    """
    Actor 代码生成/修补节点：结合需求与历史反思记忆库生成代码
    """

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.client = llm_client or LLMClient()

    async def generate_code(self, requirement: str, reflections: List[str]) -> str:
        """
        生成或修订 Python 代码，强制注入历史 reflections 作为系统约束
        """
        # TODO: 学员需实现结合 reflections 提示词记忆生成代码的逻辑
        raise NotImplementedError("TODO: 请实现 ActorNode.generate_code 代码生成逻辑")


class ReflexionGuard:
    """
    Reflexion 条件路由控制器
    """

    def __init__(self, max_retries: int = 3):
        self.max_retries = max_retries

    def evaluate_routing(self, state: ReflexionState) -> str:
        """
        判断下一步路由流向

        :return: "TO_END" | "TO_REFLECTOR" | "TO_FALLBACK"
        """
        # TODO: 学员需实现条件路由判定逻辑
        raise NotImplementedError("TODO: 请实现 ReflexionGuard.evaluate_routing 路由判定逻辑")


# ==========================================
# 3. 调试主入口 (规则 6 统一规范)
# ==========================================

async def main():
    print("=" * 60)
    print("🚀 Day 81 练习：Reflexion 自我反思自愈引擎调试")
    print("=" * 60)

    # 初始状态定义
    state: ReflexionState = {
        "user_requirement": "编写一个函数 compute_discounted_total(items)，计算字典列表中所有商品打折后的总价。",
        "current_code": "",
        "execution_result": None,
        "reflections": [],
        "loop_counter": 0,
        "is_success": False
    }

    evaluator = SandboxEvaluator()
    guard = ReflexionGuard(max_retries=3)

    try:
        # 步骤 1: 测试路由逻辑
        next_step = guard.evaluate_routing(state)
        print(f"路由判定结果: {next_step}")
    except NotImplementedError as e:
        print(f"\n[TODO 拦截提示] {e}")

    try:
        # 步骤 2: 测试沙箱代码物理执行
        test_code = "def compute_discounted_total(items):\n    return sum(item['price'] * item['discount'] for item in items)"
        res = evaluator.execute_code(test_code, "assert compute_discounted_total([{'price': 100, 'discount': 0.8}]) == 80.0")
        print(f"沙箱执行测试成功: {res.success}")
    except NotImplementedError as e:
        print(f"[TODO 拦截提示] {e}")

    print("\n💡 提示: 请在练习中参照 reflexion_engine.py 填空实现上述 TODO 模块。")


if __name__ == "__main__":
    asyncio.run(main())
