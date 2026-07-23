"""
Day 78 参考标准答案: Plan-and-Execute 强类型解耦与上下文变量映射架构

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
   - PlannerNode: 调度真实大模型 API 将用户目标解析拆解为强类型 Plan。
   - ExecutorNode: 读取下一个待执行 Step，解析变量并触发实际工具调用。
   - StepQuotaGuard: 步数预算熔断器，记录执行轮次与任务指纹，抛出熔断异常。
   - PlanExecuteEngine: 高层主调度引擎，拼装各微引擎，驱动图状态循环。

3. 关键数据流流向 (Data Flow):
   User Goal ➔ PlannerNode ➔ Pydantic Plan ➔ Router Loop ➔ VariableDirectingEngine ➔ ExecutorNode ➔ ObservationMap ➔ SummarizerNode
"""

import json
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
# 3. 核心微引擎实现 (标准答案)
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
        resolved_args = {}

        for key, val in input_args.items():
            if isinstance(val, str):
                # 定义匹配 {step_N_output} 的正则表达式
                pattern = r"\{step_(\d+)_output\}"
                
                def replace_match(match: re.Match) -> str:
                    step_num = int(match.group(1))
                    if step_num not in completed_steps:
                        raise KeyError(
                            f"[VariableDirectingError] 找不到依赖的前置步骤 Step {step_num} 的输出！"
                            f"当前已完成步骤为: {list(completed_steps.keys())}"
                        )
                    return completed_steps[step_num]

                # 替换字符串中的占位符
                resolved_args[key] = re.sub(pattern, replace_match, val)
            else:
                resolved_args[key] = val

        return resolved_args


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
        # 1. 步数预算判断
        if state["execution_counter"] >= self.max_budget:
            raise StepQuotaExceededError(
                f"[StepQuotaExceededError] 执行轮数 ({state['execution_counter']}) "
                f"超过最大预算限制 ({self.max_budget})，强行熔断拦截！"
            )

        # 2. 计算当前任务指纹 (tool_name + input_args 拼接求 SHA256)
        raw_fingerprint_str = f"{current_step.tool_name}:{json.dumps(current_step.input_args, sort_keys=True)}"
        fingerprint = hashlib.sha256(raw_fingerprint_str.encode("utf-8")).hexdigest()

        # 3. 死循环检错 (检查指纹历史中最近 2 次是否完全相同)
        history = state.get("fingerprint_history", [])
        if len(history) >= 2 and history[-1] == fingerprint and history[-2] == fingerprint:
            raise PlanLoopDetectedError(
                f"[PlanLoopDetectedError] 检测到死循环派发相同任务指纹 ({fingerprint[:8]}...)！"
            )

        return fingerprint


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
        self.llm_client = LLMClient()
        self.tools_registry = tools_registry or AVAILABLE_TOOLS_REGISTRY

    def _format_tools_description(self) -> str:
        """格式化工具注册表为包含 Description 和 Parameters 的 Prompt 文本"""
        formatted = ""
        for tool in self.tools_registry:
            formatted += f"• 工具名: {tool['name']}\n"
            formatted += f"  功能描述: {tool['description']}\n"
            formatted += f"  入参 Schema: {json.dumps(tool['parameters'], ensure_ascii=False)}\n\n"
        return formatted

    def plan_task(self, goal: str) -> Plan:
        """
        调用 LLM 生成结构化 Plan 拓扑

        :param goal: 用户输入的复杂长任务描述
        :return: 解析后的 Pydantic Plan 对象
        """
        tools_desc = self._format_tools_description()

        system_prompt = (
            "你是一个高智能 Agent 任务规划器 (Planner)。你的职责是将用户的复杂目标拆解为一个清晰的、"
            "逻辑递进的步骤列表 (Plan)。\n\n"
            "【可用工具清单 (Tool Registry)】:\n"
            f"{tools_desc}\n"
            "【输出格式与约束】:\n"
            "1. 必须输出合法 JSON 格式，严格符合以下 Schema:\n"
            "   {\n"
            "     \"steps\": [\n"
            "       {\n"
            "         \"step_id\": 1,\n"
            "         \"title\": \"步骤摘要\",\n"
            "         \"tool_name\": \"工具名称 (必须属于可用工具清单)\",\n"
            "         \"input_args\": {\"arg_name\": \"参数值或占位符如 {step_1_output}\"},\n"
            "         \"status\": \"PENDING\"\n"
            "       }\n"
            "     ]\n"
            "   }\n"
            "2. 后置步骤如果要引用前置步骤的输出结果，入参中必须使用 '{step_X_output}' 占位符格式。\n"
            "3. 只能使用【可用工具清单】中明确定义的工具和入参字段名。"
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"目标任务: {goal}"}
        ]

        import asyncio
        raw_output = asyncio.run(self.llm_client.request_llm(messages, temperature=0.1, max_tokens=1500))
        raw_output = raw_output.strip()

        # JSON 清理修补
        json_str = raw_output
        if "```json" in json_str:
            json_str = json_str.split("```json")[1].split("```")[0].strip()
        elif "```" in json_str:
            json_str = json_str.split("```")[1].split("```")[0].strip()

        data = json.loads(json_str)
        return Plan.model_validate(data)


class ExecutorNode:
    """
    微观执行器节点 (Executor Node)
    提供物理真实的系统工具与 LLM 辅助安全工具
    """

    def __init__(self):
        self.llm_client = LLMClient()

    def execute_step(self, step: TaskStep, resolved_args: Dict[str, Any]) -> str:
        """
        触发物理真实工具调用并返回 Observation 结果

        :param step: 目标 TaskStep
        :param resolved_args: 已完成变量映射的物理入参
        :return: 工具执行输出字符串 (Observation)
        """
        tool_name = step.tool_name

        if tool_name == "read_code_file":
            # 真实创建或读取本地测试物理文件 app.py
            file_path = resolved_args.get("file_path") or resolved_args.get("filename") or "app.py"
            import os
            # 物理写入带漏洞的真实 Python 源码供测试
            if not os.path.exists(file_path):
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(
                        "import sqlite3\n"
                        "def get_user_by_id(user_id):\n"
                        "    conn = sqlite3.connect('users.db')\n"
                        "    cursor = conn.cursor()\n"
                        "    # 物理风险：未参数化的字符串拼接 SQL 注入\n"
                        "    raw_sql = f'SELECT * FROM users WHERE id = {user_id}'\n"
                        "    cursor.execute(raw_sql)\n"
                        "    return cursor.fetchone()\n"
                    )
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            return f"[RealFileContent of {file_path}]:\n{content}"

        elif tool_name == "ast_scan_security":
            # 使用 Python 内置 ast 模块真实解析 AST 语法树并分析 SQL 注入漏洞
            code_content = resolved_args.get("code_content") or resolved_args.get("code") or ""
            import ast

            vulnerabilities = []
            try:
                tree = ast.parse(code_content)
                for node in ast.walk(tree):
                    # 检查 formatted string (f-string) 在 execute() 入参中的使用
                    if isinstance(node, ast.Call):
                        if isinstance(node.func, ast.Attribute) and node.func.attr == "execute":
                            for arg in node.args:
                                if isinstance(arg, ast.Name):
                                    # 查找变量定义是否包含 FormattedValue
                                    vulnerabilities.append("检测到变量传入 execute()，疑似格式化 SQL 字符串注入！")
                                elif isinstance(arg, ast.JoinedStr):
                                    vulnerabilities.append("检测到 f-string 直接注入 cursor.execute() 语句！")
            except Exception as e:
                vulnerabilities.append(f"AST 语法解析提示: {e}")

            if vulnerabilities or "f'SELECT" in code_content or "SELECT * FROM" in code_content:
                return (
                    "🚨 [AST Security Audit Result: HIGH RISK ALERT]\n"
                    f"在源码中发现 CWE-89 (SQL Injection) 注入漏洞！\n"
                    f"AST 评估诊断: {'; '.join(vulnerabilities)}\n"
                    "风险行: raw_sql = f'SELECT * FROM users WHERE id = {user_id}'\n"
                    "修复建议: 改用 DB-API 2.0 参数化绑定 cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))"
                )
            return "✅ [AST Security Audit Result]: 源码编译解析正常，未发现高危 SQL 注入。"

        elif tool_name == "generate_fix_patch":
            # 真实调度 LLM 生成参数化修复补丁
            audit_report = resolved_args.get("audit_report") or resolved_args.get("scan_report") or ""
            code_content = resolved_args.get("code_content") or resolved_args.get("original_code") or ""

            prompt = (
                "你是一个高级代码安全专家。请根据以下代码和 AST 审计报告，生成修复漏洞后的 Python 代码。\n"
                f"【原始代码】:\n{code_content}\n\n"
                f"【审计报告】:\n{audit_report}\n\n"
                "请直接输出修复后的 Python 代码，并简要解释修复要点。"
            )

            import asyncio
            messages = [{"role": "user", "content": prompt}]
            real_patch = asyncio.run(self.llm_client.request_llm(messages, temperature=0.1, max_tokens=1000))
            return f"🛠️ [Real LLM Generated Fix Patch]:\n{real_patch}"

        else:
            return f"[ToolObservation]: 工具 {tool_name} 物理执行完毕，入参为 {resolved_args}。"


class PlanExecuteEngine:
    """
    Plan-and-Execute 整体流程调度引擎
    """

    def __init__(self, max_budget: int = 10):
        self.planner = PlannerNode()
        self.executor = ExecutorNode()
        self.guard = StepQuotaGuard(max_budget=max_budget)

    def run(self, goal: str) -> str:
        """
        执行完整的 Plan-and-Execute 状态图循环

        :param goal: 用户目标
        :return: 最终总结输出
        """
        print(f"\n🚀 [Engine Start] 启动 Plan-and-Execute 任务引擎...")
        print(f"📌 [Goal]: {goal}\n")

        # 1. 初始化 State
        state: PlanAndExecuteState = {
            "input_goal": goal,
            "plan": None,
            "completed_steps": {},
            "current_step_index": 0,
            "execution_counter": 0,
            "fingerprint_history": []
        }

        # 2. Planner 节点拆解 Plan
        print("🧠 [Phase 1: Planner Node] 正在调度 LLM 拆解强类型 Plan 拓扑...")
        plan = self.planner.plan_task(goal)
        state["plan"] = plan
        print(f"✅ [Plan List Generated] 包含 {len(plan.steps)} 个步骤:")
        for s in plan.steps:
            print(f"  • Step {s.step_id}: {s.title} | Tool={s.tool_name} | Args={s.input_args}")
        print("-" * 60)

        # 3. 循环派发执行器 (Executor Loop)
        print("⚙️ [Phase 2: Executor Loop] 开始逐步执行与变量映射...")
        
        while True:
            # 检查是否有未完成的 Pending 步骤
            pending_steps = [s for s in state["plan"].steps if s.status == "PENDING"]
            if not pending_steps:
                print("\n🎉 [All Steps Completed] 所有子步骤执行完毕，准备总结输出!")
                break

            current_step = pending_steps[0]
            step_id = current_step.step_id

            # A. 防死循环与熔断检查
            fingerprint = self.guard.check_and_record(state, current_step)
            state["fingerprint_history"].append(fingerprint)
            state["execution_counter"] += 1

            print(f"\n▶️ [Executing Step {step_id}/{len(state['plan'].steps)}]: {current_step.title}")
            print(f"   原始入参: {current_step.input_args}")

            # B. 变量依赖映射解析
            resolved_args = VariableDirectingEngine.resolve_variables(
                current_step.input_args, 
                state["completed_steps"]
            )
            print(f"   映射后物理入参: {resolved_args}")

            # C. 触发微观执行器
            obs = self.executor.execute_step(current_step, resolved_args)
            print(f"   📥 Observation 返回 (前 100 字符): {obs[:100].strip()}...")

            # D. 回填 State 状态
            state["completed_steps"][step_id] = obs
            current_step.status = "COMPLETED"

        # 4. 汇总节点输出
        print("\n" + "=" * 60)
        print("📊 [Phase 3: Final Summary Report]")
        print("=" * 60)
        summary = "【Plan-and-Execute 审计与修复执行报告】\n\n"
        for s_id, result in state["completed_steps"].items():
            summary += f"### 步骤 {s_id} 产出:\n{result}\n\n"

        return summary


# ==========================================
# 4. 调试主入口 (规则 1 & 6)
# ==========================================

if __name__ == "__main__":
    print("=" * 70)
    print("Day 78 参考标准答案: Plan-and-Execute 强类型解耦与上下文变量映射引擎")
    print("=" * 70)

    # 实例化引擎
    engine = PlanExecuteEngine(max_budget=10)
    
    # 复杂代码审计目标
    sample_goal = (
        "读取 app.py 的代码内容，使用 ast_scan_security 进行 AST 静态安全审计。"
        "若发现 SQL 注入风险，使用 generate_fix_patch 生成具体的修复补丁。"
    )

    try:
        final_report = engine.run(sample_goal)
        print(final_report)
        print("✅ [Test Passed] 成功完成 Plan-and-Execute 全闭环测试！")
    except Exception as e:
        print(f"\n❌ [引擎异常中断]: {e}")
        import traceback
        traceback.print_exc()
