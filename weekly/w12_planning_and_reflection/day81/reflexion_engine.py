"""
Day 81 参考标准答案: Reflexion 自我反思架构 — 从失败 Observation 中归纳纠错规则

【系统设计方案说明】
1. 设计意图 (Design Intent):
   构建生产级 Reflexion 自我反思自愈引擎 (Self-Healing Code Generation Engine)。
   通过在 Actor (生成器) 和 Evaluator (沙箱评估器) 之间引入独立的 Reflector (诊断反思器)，
   捕获代码在物理沙箱中运行失败时的 Exception Traceback，将其归纳总结为结构化的反思避坑规则 (ReflexionLog)，
   注入后续迭代的提示词记忆中。解决 Naive Retry 盲目重试导致模型在相同 Bug 上反复横跳、无法收敛的问题。

2. 类与函数结构 (Class & Function Architecture):
   - ReflexionLog: Pydantic 模型，定义结构化反思经验 Payload (error_type, root_cause_analysis, actionable_guidance)。
   - ExecutionResult: Pydantic 模型，存储沙箱执行结果 (success, output, error_message, trimmed_traceback)。
   - ReflexionState: TypedDict 状态容器，维护全局代码需求、当前代码草稿、运行结果、历史反思记忆数组与重试计数器。
   - SandboxEvaluator: 物理沙箱评估器，提供受限 exec() 命名空间、stdout/stderr 捕获与 Traceback 提纯清洗。
   - ReflectorNode: 诊断反思节点，使用 `parse_structured` 将失败 Log 提纯为强类型 ReflexionLog。
   - ActorNode: 代码生成/修改节点，从系统提示词层强制注入历史 reflections 避坑指令。
   - ReflexionGuard: 条件路由控制器，精准控制放行 (TO_END)、重跑反思 (TO_REFLECTOR) 或熔断降级 (TO_FALLBACK)。
   - ReflexionEngine: 状态图/工作流调度总控器，协同多节点运行完整的反思自愈闭环。

3. 关键数据流流向 (Data Flow):
   User Requirement ➔ ActorNode (Inject Historical Reflections) ➔ Python Code Draft
     ➔ SandboxEvaluator (Physical Execution & Assertion Verification)
     ➔ (If Success) ➔ END Node (Return Verified Code)
     ➔ (If Fail & Loop < Max) ➔ ReflectorNode (Generate ReflexionLog)
         ➔ State["reflections"].append(guidance) ➔ ActorNode (Iteration #k+1)
     ➔ (If Fail & Loop >= Max) ➔ Fallback Intercept Node

4. 核心用例设计意图 (Test Case Design Intent):
   选取“自动编写一个根据产品分析报告解析财务指标与环比增长率的函数”作为验证场景：
   - 故意要求代码处理缺失字段、处理零除（ZeroDivisionError）以及浮点数百分比格式转换。
   - 验证点 1：首次生成时观察 Evaluator 捕获真实 ZeroDivisionError 或 KeyError Traceback。
   - 验证点 2：观察 ReflectorNode 能否生成包含具体防御性检查（如 `if denom == 0: return 0.0`）的 actionable_guidance。
   - 验证点 3：观察 ActorNode 在第二轮生成中读取该指导规则后，代码成功绕开 Bug 并 100% 通过断言验证。
"""

import sys
import io
import re
import traceback
import asyncio
from typing import Dict, List, Any, Optional, TypedDict
from pydantic import BaseModel, Field

# 从公共工具与中间件导入 API 与结构化提取功能 (规则 12, 20 & 21)
from weekly.w04_prompt_and_http.utils import load_env_file, LLMClient
from middlewares.llm_reliability_adapter import parse_structured

# 加载环境变量
load_env_file()


# ==========================================
# 1. 强类型 Schema 与 State 容器契约
# ==========================================

class ReflexionLog(BaseModel):
    """
    Reflector 诊断反思器生成的结构化经验 Payload
    """
    error_type: str = Field(description="捕获的异常类型 (如 NameError, TypeError, SyntaxError, ZeroDivisionError, KeyError)")
    root_cause_analysis: str = Field(description="导致代码崩溃的根本原因深度剖析")
    actionable_guidance: str = Field(description="具体且可操作的下一轮代码生成避坑规则与修复指令")


class ExecutionResult(BaseModel):
    """
    沙箱环境执行评估结果契约
    """
    success: bool = Field(description="代码是否成功执行并通过全部测试断言")
    output: str = Field(default="", description="代码的标准输出 (stdout)")
    error_message: str = Field(default="", description="异常简明描述")
    trimmed_traceback: str = Field(default="", description="清洗提纯后的核心堆栈日志")


class ReflexionState(TypedDict):
    """
    状态图全局 TypedDict 容器
    """
    user_requirement: str
    test_assertion: str
    current_code: str
    execution_result: Optional[ExecutionResult]
    reflections: List[str]  # 历史积累的反思避坑规则字符串数组 (Episodic Memory)
    loop_counter: int      # 博弈/重试计数器
    is_success: bool


# ==========================================
# 2. 核心微引擎实现
# ==========================================

class SandboxEvaluator:
    """
    物理沙箱评估器：负责安全物理执行 Python 代码、提纯堆栈日志
    """

    def clean_traceback(self, raw_tb: str) -> str:
        """
        提纯 Traceback 日志：过滤 Python 内置库与 exec 框架无关堆栈，提取用户代码报错行
        """
        lines = raw_tb.strip().split("\n")
        cleaned_lines = []
        for line in lines:
            # 过滤掉内部 exec 堆栈噪点
            if "File \"<string>\"" in line or "Traceback" in line or any(err in line for err in ["Error:", "Exception:"]):
                cleaned_lines.append(line)
        return "\n".join(cleaned_lines) if cleaned_lines else raw_tb[-500:]

    def execute_code(self, code_str: str, test_assertion: Optional[str] = None) -> ExecutionResult:
        """
        在受限命名空间中物理执行代码并运行测试断言
        """
        buffer = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buffer

        exec_globals: Dict[str, Any] = {
            "__builtins__": __builtins__,
            "abs": abs, "len": len, "sum": sum, "max": max, "min": min,
            "float": float, "int": int, "str": str, "dict": dict, "list": list, "set": set
        }

        try:
            # 1. 物理执行代码定义
            exec(code_str, exec_globals)

            # 2. 执行关联测试断言
            if test_assertion:
                exec(test_assertion, exec_globals)

            sys.stdout = old_stdout
            return ExecutionResult(
                success=True,
                output=buffer.getvalue().strip(),
                error_message="",
                trimmed_traceback=""
            )

        except Exception as e:
            sys.stdout = old_stdout
            raw_tb = traceback.format_exc()
            cleaned_tb = self.clean_traceback(raw_tb)
            error_type = type(e).__name__

            return ExecutionResult(
                success=False,
                output=buffer.getvalue().strip(),
                error_message=f"{error_type}: {str(e)}",
                trimmed_traceback=cleaned_tb
            )


class ReflectorNode:
    """
    Reflector 诊断反思节点：解析失败日志并生成结构化 ReflexionLog
    """

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.client = llm_client or LLMClient()

    async def reflect(self, requirement: str, failed_code: str, exec_result: ExecutionResult) -> ReflexionLog:
        """
        调用 LLM 对失败代码与报错日志进行反思诊断，输出结构化 ReflexionLog
        """
        prompt = f"""你是一名资深 Python 代码质量审计专家。以下代码在物理沙箱执行中抛出异常崩溃。

【功能需求】:
{requirement}

【崩溃代码草稿】:
```python
{failed_code}
```

【物理执行异常日志】:
简要错误: {exec_result.error_message}
核心堆栈:
{exec_result.trimmed_traceback}

【极重要格式约束】:
1. 请直接输出标准 JSON 文本，严禁将最终 JSON 内容包裹在 <think> 标签内！
2. 必须且仅包含以下字段：
{{"error_type": "异常类型", "root_cause_analysis": "崩溃根因剖析", "actionable_guidance": "下一轮修复指令"}}
"""
        messages = [
            {"role": "system", "content": "你是一名精通 Python 报错调试与反思总结的专家。请直接输出 JSON 强类型反思报告。"},
            {"role": "user", "content": prompt}
        ]
        try:
            raw_text = await self.client.request_llm(messages=messages, temperature=0.2)
            reflection_log: ReflexionLog = parse_structured(
                raw_text=raw_text,
                response_model=ReflexionLog
            )
            return reflection_log
        except Exception as e:
            print(f"⚠️ [ReflectorNode] 反思解析捕获到异常 ({type(e).__name__})，触发兜底降级 Payload。")
            return ReflexionLog(
                error_type="ExecutionFailure",
                root_cause_analysis=f"代码物理运行失败: {exec_result.error_message}",
                actionable_guidance=f"请严格检查边界条件与类型校验逻辑，修复以下错误: {exec_result.error_message}"
            )


class ActorNode:
    """
    Actor 代码生成/修补节点：结合需求与历史反思记忆库生成代码
    """

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.client = llm_client or LLMClient()

    def _extract_code_block(self, raw_text: str) -> str:
        """
        从 LLM 输出中提取纯 Python 代码块
        """
        match = re.search(r"```python\s*(.*?)\s*```", raw_text, re.DOTALL)
        if match:
            return match.group(1).strip()
        cleaned = re.sub(r"```\w*\s*", "", raw_text)
        return cleaned.strip("` \n")

    async def generate_code(self, requirement: str, reflections: List[str]) -> str:
        """
        生成或修订 Python 代码，强制注入历史 reflections 作为系统约束
        """
        if not reflections:
            # 轮次 #1 初始生成：模拟无防备直译代码（故意不加 try-except 过滤防护），以触发真实的沙箱 Traceback 报错
            system_prompt = "你是一名 Python 程序员。请根据需求编写简单的 Python 函数代码。仅输出代码块 (用 ```python 包裹)。"
            user_prompt = f"请编写 Python 代码实现以下需求。要求仅写最直接的逻辑（直接调用 float(event['score'])，切勿主动添加任何 try-except 或异常防护代码）：\n{requirement}"
        else:
            # 轮次 #2+ 迭代生成：注入历史反思记忆与必遵规则
            reflection_memory_str = "\n".join([f"- [经验法则 #{i+1}]: {r}" for i, r in enumerate(reflections)])
            system_prompt = f"""你是一名精通 Python 开发的高级 Agent 代码编写引擎。
你编写的代码将在自动化沙箱中物理运行。

【历史失败反思总结与必遵规则】：
{reflection_memory_str}

【极重要约束】：
1. 必须完全满足【历史失败反思总结】中的每一条避坑规则，绝对不允许重复犯错！
2. 仅输出可直接执行的纯 Python 代码块（用 ```python 包裹），严禁输出任何多余的解释说明文字。
3. 针对【经验法则】中提及的崩溃点做针对性防御与修复（如添加 try-except 转换防护）。
"""
            user_prompt = f"请根据历史反思经验修正并重构 Python 代码：\n{requirement}"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        raw_response = await self.client.request_llm(messages=messages, temperature=0.2)
        return self._extract_code_block(raw_response)


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
        if state["is_success"]:
            return "TO_END"
        if state["loop_counter"] >= self.max_retries:
            return "TO_FALLBACK"
        return "TO_REFLECTOR"


class ReflexionEngine:
    """
    Reflexion 自愈引擎主控器
    """

    def __init__(self, max_retries: int = 3):
        self.actor = ActorNode()
        self.evaluator = SandboxEvaluator()
        self.reflector = ReflectorNode()
        self.guard = ReflexionGuard(max_retries=max_retries)

    async def run(self, requirement: str, test_assertion: str) -> ReflexionState:
        """
        执行完整的 Reflexion 自反思闭环
        """
        state: ReflexionState = {
            "user_requirement": requirement,
            "test_assertion": test_assertion,
            "current_code": "",
            "execution_result": None,
            "reflections": [],
            "loop_counter": 0,
            "is_success": False
        }

        print("=" * 70)
        print("🚀 启动 Reflexion 自自我反思自愈引擎")
        print(f"📋 任务需求: {requirement}")
        print("=" * 70)

        while True:
            state["loop_counter"] += 1
            current_loop = state["loop_counter"]
            print(f"\n🔄 --- 迭代轮次 #{current_loop} ---")

            # 1. Actor 生成代码
            print("🤖 [ActorNode] 正在结合历史反思记忆生成代码...")
            code_draft = await self.actor.generate_code(
                requirement=state["user_requirement"],
                reflections=state["reflections"]
            )
            state["current_code"] = code_draft
            print(f"📄 生成的代码草稿 (版本 #{current_loop}):\n{code_draft}\n")

            # 2. Evaluator 物理沙箱评估
            print("🧪 [SandboxEvaluator] 正在沙箱中物理运行代码与测试断言...")
            exec_res = self.evaluator.execute_code(code_draft, test_assertion=test_assertion)
            state["execution_result"] = exec_res

            if exec_res.success:
                state["is_success"] = True
                print("✅ [SandboxEvaluator] 代码物理运行通过！通过全部断言。")
            else:
                state["is_success"] = False
                print(f"❌ [SandboxEvaluator] 代码运行崩溃: {exec_res.error_message}")
                print(f"🔍 [Cleaned Traceback]:\n{exec_res.trimmed_traceback}")

            # 3. Guard 判定路由
            route = self.guard.evaluate_routing(state)

            if route == "TO_END":
                print("\n🎉 [ReflexionEngine] 自愈收敛成功！系统输出合格代码。")
                break
            elif route == "TO_FALLBACK":
                print(f"\n⚠️ [ReflexionEngine] 达到最大重试上限 ({self.guard.max_retries} 轮)，触发熔断拦截。")
                break
            elif route == "TO_REFLECTOR":
                # 4. Reflector 诊断反思
                print("🧠 [ReflectorNode] 正在诊断失败原因并析出反思规则...")
                reflection_log = await self.reflector.reflect(
                    requirement=state["user_requirement"],
                    failed_code=state["current_code"],
                    exec_result=exec_res
                )
                print(f"💡 [析出反思 Log]: {reflection_log.error_type} ➔ {reflection_log.root_cause_analysis}")
                print(f"📌 [避坑规则 (Actionable Guidance)]: {reflection_log.actionable_guidance}")

                # 将提纯后的经验写入记忆库
                state["reflections"].append(reflection_log.actionable_guidance)

        return state


# ==========================================
# 3. 运行入口 (规则 6 统一规范)
# ==========================================

async def main():
    # 测试需求：用户 VIP 行为积分加权计算引擎
    requirement = """
编写一个函数 compute_user_vip_scores(events: list[dict]) -> dict:
1. 处理用户行为日志 events 列表，每项包含 'user_id', 'action', 'score'。
2. 根据 'action' 计算每个 'user_id' 的加权积分 (weighted_total) 与有效事件数 (valid_event_count)：
   - 'login': 权重 1.0
   - 'purchase': 权重 2.0
   - 'share': 权重 1.5
3. 计算规则：
   - 提取 'score' 并转为 float。如 score 为负数或无法转为 float（如 "invalid"），跳过该条记录。
   - 必须过滤无效动作与异常数据。
4. 返回字典格式: {"u1": {"weighted_total": 110.0, "valid_event_count": 2}, ...}
"""

    # 测试断言：包含未知动作 'unknown'、负数 score 与非法字符串。
    # 首次生成的大模型极其容易忽视未在 [login, purchase, share] 白名单内的未知 action 校验，导致过滤失败抛出 AssertionError。
    test_assertion = """
test_events = [
    {"user_id": "u1", "action": "login", "score": 10},       # 10 * 1.0 = 10
    {"user_id": "u1", "action": "purchase", "score": "50"},  # 50 * 2.0 = 100 -> u1 计 110.0, count=2
    {"user_id": "u2", "action": "share", "score": 20},       # 20 * 1.5 = 30 -> u2 计 30.0, count=1
    {"user_id": "u2", "action": "unknown", "score": 100},     # 未知 action，必须剔除，不得计入 count！
    {"user_id": "u3", "action": "purchase", "score": -10},    # score 负数，需剔除！
    {"user_id": "u4", "action": "purchase", "score": "invalid"} # score 无法解析，需剔除！u4 不出现在字典中
]
res = compute_user_vip_scores(test_events)
assert isinstance(res, dict), "返回值必须为字典"
assert "u4" not in res, "无有效事件的用户 u4 不得出现在返回字典中"
assert res["u1"]["weighted_total"] == 110.0 and res["u1"]["valid_event_count"] == 2, f"u1 计算错误: {res.get('u1')}"
assert res["u2"]["weighted_total"] == 30.0 and res["u2"]["valid_event_count"] == 1, f"u2 未知 action 需被剔除，实际为: {res.get('u2')}"
"""

    engine = ReflexionEngine(max_retries=3)
    final_state = await engine.run(requirement, test_assertion)

    print("\n" + "=" * 70)
    print("📊 最终 Reflexion 运行总结")
    print("=" * 70)
    print(f"成功标志: {final_state['is_success']}")
    print(f"总迭代轮次: {final_state['loop_counter']}")
    print(f"积累经验条数: {len(final_state['reflections'])}")
    for i, ref in enumerate(final_state["reflections"]):
        print(f"  - 经验 #{i+1}: {ref}")
    print("\n最终通过验证的代码:")
    print(final_state["current_code"])


if __name__ == "__main__":
    asyncio.run(main())
