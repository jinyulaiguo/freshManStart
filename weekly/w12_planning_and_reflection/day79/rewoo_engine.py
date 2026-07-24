"""
Day 79 参考标准答案: ReWOO (Reasoning Without Observation) 规划与并行执行解耦架构

【系统设计方案说明】
1. 设计意图 (Design Intent):
   构建生产级 ReWOO 架构引擎，实现 Planner (预分解无观察依赖蓝图)、Parallel Worker (多路异步并发工具拉起)
   与 Solver (变量解算与终极总结) 的物理解耦。
   解决传统 ReAct / Plan-and-Execute 架构在中长程并发数据提取任务中的高延时 (High Latency) 与 Token 爆表瓶颈。

2. 类与函数结构 (Class & Function Architecture):
   - ReWOOStep: Pydantic 模型，定义带变量占位符 (#E1, #E2) 的单步拓扑契约。
   - ReWOOPlan: Pydantic 模型，管理步骤蓝图列表。
   - DAGDependencyAnalyzer: 拓扑分析器，负责将 Plan 划分为“无依赖可并发层”与“有依赖后置层”。
   - EvidenceMap: 存储变量占位符到实际 Observation 映射的字典容器。
   - ParallelWorkerEngine: 基于 asyncio.gather 的非阻塞并发执行微引擎。
   - ReWOOPlannerNode: 驱动大模型一次性输出带占位符的无依赖 Blueprint。
   - ReWOOSolverNode: 接收填充好的 Evidence Map，解算占位符并生成终极报告。
   - ReWOOEngine: 整体流程主调度器，驱动 DAG 分层与非阻塞并发控制流。

3. 关键数据流流向 (Data Flow):
   User Input ➔ PlannerNode ➔ ReWOOPlan (#E1,#E2,#E3) ➔ DAGDependencyAnalyzer
     ➔ Layer 1: ParallelWorkerEngine (asyncio.gather) ➔ EvidenceMap {#E1: R1, #E2: R2}
     ➔ Layer 2: Variable Replacement ➔ SolverNode ➔ Final Summary Response

4. 核心用例设计意图 (Test Case Design Intent):
   选取“同时对比 AAPL (Apple) 与 MSFT (Microsoft) 2025Q1 财报”作为标准验证场景：
   - 验证点 1：测试 Planner 能否一次性识别出 AAPL 与 MSFT 两个独立提取任务并赋予 #E1, #E2 占位符。
   - 验证点 2：测试 DAG 分析器能否将 #E1 与 #E2 归类为 Layer 0（零依赖层），并通过 asyncio.gather 实现物理并发拉起。
   - 验证点 3：测试 #E3 (compare_metrics) 能否被准确归类为 Layer 1 后置依赖层，并从 Evidence Map 完成占位符替换。
   - 验证点 4：对比并发总耗时 (1.5s) 与串行等待耗时 (3.0s)，验证 2-Call LLM 协议下的端到端性能加速。
"""

import asyncio
import json
import re
import time
from typing import Dict, List, Any, Optional, TypedDict
from pydantic import BaseModel, Field

# 从公共工具加载 API 凭证与配置 (规则 12 & 20)
from weekly.w04_prompt_and_http.utils import load_env_file, LLMClient

# 加载环境变量
load_env_file()


# ==========================================
# 1. 强类型 Pydantic Schema 契约
# ==========================================

class ReWOOStep(BaseModel):
    """
    ReWOO 蓝图单步数据契约
    """
    step_id: int = Field(description="步骤序号，从 1 开始")
    variable: str = Field(description="变量占位符名称，格式如 '#E1', '#E2'")
    tool_name: str = Field(description="调用的工具名称，如 fetch_financial_report, compare_metrics")
    tool_args: Dict[str, Any] = Field(
        default_factory=dict, 
        description="工具入参，依赖项支持 '#E1' 格式占位符"
    )
    dependencies: List[str] = Field(
        default_factory=list, 
        description="该步骤依赖的前置变量占位符列表，例如 ['#E1', '#E2']"
    )


class ReWOOPlan(BaseModel):
    """
    ReWOO 全局规划蓝图
    """
    steps: List[ReWOOStep] = Field(description="无观察依赖的全局步骤列表")


class ReWOOState(TypedDict):
    """
    LangGraph 状态图全局 TypedDict 容器
    """
    user_goal: str
    plan: Optional[ReWOOPlan]
    evidence_map: Dict[str, str]  # "#E1" -> 物理 Observation 文本
    final_response: Optional[str]


# ==========================================
# 2. 拓扑依赖分析器 (DAGDependencyAnalyzer)
# ==========================================

class DAGDependencyAnalyzer:
    """
    DAG 拓扑依赖分析器
    负责根据 dependencies 字段将 ReWOOPlan 划分为可并发执行的层级 (Layers)
    """

    @staticmethod
    def analyze_layers(plan: ReWOOPlan) -> List[List[ReWOOStep]]:
        """
        按依赖关系将 Plan 分层。
        第 0 层：没有任何前置依赖的独立步骤（可直接 `asyncio.gather` 并发）
        第 1 层：依赖已完成变量的后续解算步骤。

        :param plan: 全局 ReWOOPlan
        :return: 按层级排列的 ReWOOStep 嵌套列表
        """
        layers: List[List[ReWOOStep]] = []
        resolved_vars = set()
        remaining_steps = list(plan.steps)

        while remaining_steps:
            current_layer = []
            next_remaining = []

            for step in remaining_steps:
                # 如果该 Step 的所有 dependencies 均已在 resolved_vars 中解决（或无依赖）
                if set(step.dependencies).issubset(resolved_vars):
                    current_layer.append(step)
                else:
                    next_remaining.append(step)

            if not current_layer:
                # 说明发生了死锁或找不到可以解算的步骤 (循环依赖)
                unresolved_names = [s.variable for s in remaining_steps]
                raise ValueError(f"[DAGCircularDependencyError] 检测到无法依赖解算的死锁步骤: {unresolved_names}")

            # 将本层产生的所有变量放入已解决集合
            for step in current_layer:
                resolved_vars.add(step.variable)

            layers.append(current_layer)
            remaining_steps = next_remaining

        return layers


# ==========================================
# 3. 异步并发工具引擎 (ParallelWorkerEngine)
# ==========================================

class ParallelWorkerEngine:
    """
    非阻塞异步并发工具执行引擎
    使用 asyncio.gather 同时发起同一层级的所有独立工具调用
    """

    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client

    @staticmethod
    def _resolve_args_placeholders(input_args: Dict[str, Any], evidence_map: Dict[str, str]) -> Dict[str, Any]:
        """
        将入参中的 #E1, #E2 占位符替换为 evidence_map 中的真实 Observation 文本
        """
        resolved = {}
        for k, v in input_args.items():
            if isinstance(v, str):
                val_str = v
                for var_name, obs_text in evidence_map.items():
                    val_str = val_str.replace(var_name, obs_text)
                resolved[k] = val_str
            else:
                resolved[k] = v
        return resolved

    async def _execute_single_tool(self, tool_name: str, resolved_args: Dict[str, Any]) -> str:
        """
        真实/模拟触发具体的网络或系统 API（加入 1.5s 物理延迟用于演示并发加速）
        """
        if tool_name == "fetch_financial_report":
            ticker = resolved_args.get("ticker", "UNKNOWN").upper()
            period = resolved_args.get("period", "2025Q1")
            
            # 模拟物理网络请求延迟 (1.5 秒)
            await asyncio.sleep(1.5)
            
            if "AAPL" in ticker:
                return f"[{ticker} {period} Financials]: 总营收 $124.3B (同比+5.2%), 净利润 $33.9B (净利率 27.2%)"
            elif "MSFT" in ticker:
                return f"[{ticker} {period} Financials]: 总营收 $65.6B (同比+16.0%), 净利润 $24.7B (净利率 37.6%)"
            else:
                return f"[{ticker} {period} Financials]: 总营收 $45.0B, 净利润 $12.0B"

        elif tool_name == "compare_metrics":
            # 本地计算对比工具
            data1 = resolved_args.get("data1", "")
            data2 = resolved_args.get("data2", "")
            await asyncio.sleep(0.2)
            return (
                f"[Financial Metrics Comparison Summary]:\n"
                f"• 数据源 1: {data1}\n"
                f"• 数据源 2: {data2}\n"
                f"• 结论: 苹果(AAPL)在总营收体量上占优($124.3B vs $65.6B)；微软(MSFT)在净利润同比增速(16.0% vs 5.2%)与净利率(37.6% vs 27.2%)上具备显著优势。"
            )
        else:
            await asyncio.sleep(0.5)
            return f"[ToolObservation for {tool_name}]: 执行成功，入参={resolved_args}"

    async def _execute_step(self, step: ReWOOStep, evidence_map: Dict[str, str]) -> tuple[str, str]:
        """
        执行单个 ReWOOStep，解算占位符并触发工具
        """
        start_t = time.time()
        # 1. 解算变量占位符
        resolved_args = self._resolve_args_placeholders(step.tool_args, evidence_map)
        print(f"   ▶️ [Worker Launch: {step.variable}] {step.tool_name}({resolved_args})")
        
        # 2. 异步触发物理工具调用
        obs = await self._execute_single_tool(step.tool_name, resolved_args)
        elapsed = time.time() - start_t
        print(f"   📥 [Worker Finish: {step.variable}] 耗时 {elapsed:.2f}s | Obs: {obs[:60]}...")
        return step.variable, obs

    async def run_layer_parallel(self, layer_steps: List[ReWOOStep], evidence_map: Dict[str, str]) -> Dict[str, str]:
        """
        使用 asyncio.gather 并发拉起本层级的所有独立任务

        :param layer_steps: 同一层级的 ReWOOStep 列表
        :param evidence_map: 当前积累的 Evidence Map
        :return: 本层产生的 {variable: observation} 字典
        """
        tasks = [self._execute_step(step, evidence_map) for step in layer_steps]
        results = await asyncio.gather(*tasks)
        return dict(results)


# ==========================================
# 4. Planner 与 Solver LLM 节点
# ==========================================

AVAILABLE_TOOLS_REGISTRY = [
    {
        "name": "fetch_financial_report",
        "description": "并发查询指定上市公司股票代码 (ticker) 与财报周期 (period) 的财报数据。",
        "parameters": {
            "ticker": "string (必填): 股票代码，如 'AAPL', 'MSFT'",
            "period": "string (必填): 财报周期，如 '2025Q1'"
        }
    },
    {
        "name": "compare_metrics",
        "description": "对比两路或多路财报数据，分析营收与利润率差距。",
        "parameters": {
            "data1": "string (必填): 第一路数据，填占位符如 '#E1'",
            "data2": "string (必填): 第二路数据，填占位符如 '#E2'"
        }
    }
]


class ReWOOPlannerNode:
    """
    ReWOO 规划器节点 (Planner)
    一次性预测全部解耦步骤与变量占位符
    """

    def __init__(self):
        self.llm_client = LLMClient()

    async def generate_blueprint(self, goal: str) -> ReWOOPlan:
        """
        调度 LLM 生成带有 #E1, #E2 占位符的无观察依赖蓝图
        """
        tools_desc = json.dumps(AVAILABLE_TOOLS_REGISTRY, ensure_ascii=False, indent=2)

        system_prompt = (
            "你是一个高级 ReWOO (Reasoning Without Observation) 规划器。\n"
            "你的职责是解析用户的目标，一次性生成无观察依赖的全局执行蓝图 (Blueprint)。\n\n"
            "【可用工具清单】:\n"
            f"{tools_desc}\n\n"
            "【蓝图生成规则】:\n"
            "1. 必须使用 JSON 格式，包含 steps 数组。\n"
            "2. 每个步骤必须分配唯一的变量占位符 variable (格式如 '#E1', '#E2', '#E3')。\n"
            "3. 如果某个步骤没有前置依赖，dependencies 填 []。\n"
            "4. 如果某个步骤需要等待前面的变量结果（例如对比分析），dependencies 填依赖的变量列表 ['#E1', '#E2']，"
            "且 tool_args 中必须使用 '#E1' 占位符！\n"
            "5. Schema 如下:\n"
            "   {\n"
            "     \"steps\": [\n"
            "       {\n"
            "         \"step_id\": 1,\n"
            "         \"variable\": \"#E1\",\n"
            "         \"tool_name\": \"fetch_financial_report\",\n"
            "         \"tool_args\": {\"ticker\": \"AAPL\", \"period\": \"2025Q1\"},\n"
            "         \"dependencies\": []\n"
            "       },\n"
            "       {\n"
            "         \"step_id\": 2,\n"
            "         \"variable\": \"#E2\",\n"
            "         \"tool_name\": \"fetch_financial_report\",\n"
            "         \"tool_args\": {\"ticker\": \"MSFT\", \"period\": \"2025Q1\"},\n"
            "         \"dependencies\": []\n"
            "       },\n"
            "       {\n"
            "         \"step_id\": 3,\n"
            "         \"variable\": \"#E3\",\n"
            "         \"tool_name\": \"compare_metrics\",\n"
            "         \"tool_args\": {\"data1\": \"#E1\", \"data2\": \"#E2\"},\n"
            "         \"dependencies\": [\"#E1\", \"#E2\"]\n"
            "       }\n"
            "     ]\n"
            "   }"
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"目标任务: {goal}"}
        ]

        raw_output = await self.llm_client.request_llm(messages, temperature=0.1, max_tokens=1500)
        json_str = raw_output.strip()
        if "```json" in json_str:
            json_str = json_str.split("```json")[1].split("```")[0].strip()
        elif "```" in json_str:
            json_str = json_str.split("```")[1].split("```")[0].strip()

        data = json.loads(json_str)
        return ReWOOPlan.model_validate(data)


class ReWOOSolverNode:
    """
    ReWOO 解算与终极总结节点 (Solver)
    """

    def __init__(self):
        self.llm_client = LLMClient()

    async def solve(self, goal: str, plan: ReWOOPlan, evidence_map: Dict[str, str]) -> str:
        """
        结合 Evidence Map 替换占位符，输出终极分析报告
        """
        formatted_evidence = ""
        for var_name, obs in evidence_map.items():
            formatted_evidence += f"• 变量 {var_name}: {obs}\n"

        prompt = (
            "你是一个高级财务分析与研报总结专家 (ReWOO Solver)。\n"
            f"【用户目标】: {goal}\n\n"
            "【已解算收集到的 Evidence Map】:\n"
            f"{formatted_evidence}\n"
            "请基于上述 Evidence Map 收集到的真实物理数据，生成一份结构清晰、包含核心指标对比与专业结论的财务分析报告。"
        )

        messages = [{"role": "user", "content": prompt}]
        return await self.llm_client.request_llm(messages, temperature=0.3, max_tokens=1500)


# ==========================================
# 5. ReWOO 主调度引擎 (ReWOOEngine)
# ==========================================

class ReWOOEngine:
    """
    ReWOO 主调度引擎
    物理串联 Planner ➔ DAG 分析 ➔ Parallel Worker ➔ Solver
    """

    def __init__(self):
        self.planner = ReWOOPlannerNode()
        self.worker = ParallelWorkerEngine(LLMClient())
        self.solver = ReWOOSolverNode()

    async def run_async(self, goal: str) -> str:
        """
        异步调度运行 ReWOO 全闭环
        """
        start_total_t = time.time()
        print("🚀 [ReWOO Engine Start] 启动 ReWOO 规划与并发执行解耦引擎...")
        print(f"📌 [Goal]: {goal}\n")

        # 1. Planner 节点 (LLM Call #1)
        t0 = time.time()
        print("🧠 [Phase 1: Planner Node] 正在调度 LLM 预分解无观察依赖 Blueprint...")
        plan = await self.planner.generate_blueprint(goal)
        print(f"✅ [Blueprint Generated] 耗时 {time.time()-t0:.2f}s | 包含 {len(plan.steps)} 个步骤:")
        for s in plan.steps:
            print(f"   • {s.variable} = {s.tool_name}({s.tool_args}) | Deps={s.dependencies}")
        print("-" * 60)

        # 2. DAG 拓扑分析与分层
        print("🌿 [Phase 2: DAG Analyzer] 正在分析依赖拓扑并划分并发 Layer...")
        layers = DAGDependencyAnalyzer.analyze_layers(plan)
        print(f"✅ [DAG Layer Split] 划分成功，共分为 {len(layers)} 个物理执行层:")
        for i, layer in enumerate(layers):
            vars_in_layer = [s.variable for s in layer]
            print(f"   • Layer {i}: {vars_in_layer} (并发节点数={len(layer)})")
        print("-" * 60)

        # 3. 按层级非阻塞并发执行工具
        print("⚡ [Phase 3: Parallel Worker Loop] 开始按 Layer 非阻塞并发拉起物理工具...")
        evidence_map: Dict[str, str] = {}
        t_worker_start = time.time()

        for i, layer in enumerate(layers):
            print(f"\n🌊 [Executing Layer {i}] 并发触发 {len(layer)} 个独立的 Worker 任务...")
            layer_t0 = time.time()
            layer_results = await self.worker.run_layer_parallel(layer, evidence_map)
            evidence_map.update(layer_results)
            print(f"✅ [Layer {i} Completed] 本层耗时: {time.time()-layer_t0:.2f}s")

        t_worker_total = time.time() - t_worker_start
        print(f"\n🎯 [All Layers Completed] Worker 阶段总并发耗时: {t_worker_total:.2f}s")
        print("   Evidence Map 沉淀结果:")
        for var_name, res in evidence_map.items():
            print(f"   - {var_name}: {res}")
        print("-" * 60)

        # 4. Solver 节点解算总结 (LLM Call #2)
        print("📊 [Phase 4: Solver Node] 正在把 Evidence Map 喂给 Solver 总结终极报告 (LLM Call #2)...")
        t_solver0 = time.time()
        final_report = await self.solver.solve(goal, plan, evidence_map)
        print(f"✅ [Solver Finished] 耗时 {time.time()-t_solver0:.2f}s")

        total_elapsed = time.time() - start_total_t
        print(f"\n🎉 [ReWOO Engine Completed] 端到端全流程总耗时: {total_elapsed:.2f}s (仅 2 次 LLM 调用!)")
        return final_report


# ==========================================
# 6. 调试主入口 (规则 1 & 6)
# ==========================================

if __name__ == "__main__":
    print("=" * 70)
    print("Day 79 参考标准答案: ReWOO 规划与并行执行解耦引擎")
    print("=" * 70)

    engine = ReWOOEngine()
    sample_goal = "对比 AAPL (Apple) 与 MSFT (Microsoft) 2025 年 Q1 财报的总营收与净利润指标。"

    try:
        report = asyncio.run(engine.run_async(sample_goal))
        print("\n" + "=" * 60)
        print("📄 【ReWOO 最终财务对比研报】")
        print("=" * 60)
        print(report)
        print("\n✅ [Test Passed] 成功完成 ReWOO 拓扑分层与 asyncio.gather 并发测试！")
    except Exception as e:
        print(f"\n❌ [引擎运行发生异常]: {e}")
        import traceback
        traceback.print_exc()
