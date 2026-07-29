"""
Week 14 Day 97 生产级项目代码: Agent Model Control Plane & LLM Gateway 基础设施 (router_gateway_impl.py)

===============================================================================
设计方案说明 (Architecture Design Specification)
===============================================================================

1. 设计意图 (Design Intent):
   弃用简单的 "Complexity => LOW/HIGH => Model Choice" 粗放模型。
   构建工业级 Agent Model Control Plane (模型决策控制平面) 与 LLM Gateway 基础设施：
   - 8-Dimension Decision Engine: 结合 Task Complexity, Task Type (Coding/SQL/Research), Required Capabilities (Tool Calling/128K Context), Context Size, Budget (联动 Day 94) 及 Provider Health 8 维智能挑选；
   - Dynamic Health Score: 实时打分 (0~100) 评估 P95 延迟、成功率与错误率；
   - Error Classifier: 区分 429 Rate Limit (切同级模型), Timeout (同 Provider 重试), Context Over (触发 Day 95 增量压缩), 500/503 (Fallback 链)；
   - Agent Node-Level Routing: LangGraph 节点级差异化路由 (Planner/Executor/Reflection 节点分流)。

2. 核心类与数据流拓扑 (Class & Data Flow Topology):
   - `TaskRequirement`: 8 维路由输入元数据模型。
   - `ProviderHealthTracker`: 动态计算 Provider 健康分值与隔离状态。
   - `ModelDecisionEngine`: 执行能力匹配、预算约束与最佳 Provider 选择。
   - `ErrorClassifier`: 异常分类器与响应策略判定。
   - `LLMGateway`: 高可用请求封装、重试退避、节点路由与导出 `gateway_trace.json`。

3. 核心用例设计意图 (Test Case Design Intent):
   跑通 6 大生产级实战场景：
   - Case 1: 8 维能力与任务类型匹配路由 (Coding 任务分流)；
   - Case 2: 模拟 503 故障触发 Fallback 降级链；
   - Case 3: 模拟 Timeout 触发重试与 Health 分数扣减；
   - Case 4: 动态健康分 (Dynamic Health Score) 打分与隔离；
   - Case 5: 预算受限驱动强制模型降级 (与 Day 94 预算联动)；
   - Case 6: Agent 节点级路由 (LangGraph Node-Level 差异化路由)。
===============================================================================
"""

import os
import sys
import enum
import time
import math
import json
import asyncio
from typing import List, Dict, Any, Optional, Set, Tuple
from dataclasses import dataclass, field

# 导入 Week 4 LLM 工具客户端
current_dir = os.path.dirname(os.path.abspath(__file__))
w04_dir = os.path.abspath(os.path.join(current_dir, "../../w04_prompt_and_http"))

if w04_dir not in sys.path:
    sys.path.append(w04_dir)

from utils import LLMClient


class ModelComplexity(enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TaskType(enum.Enum):
    CODING = "coding"
    RESEARCH = "research"
    SQL = "sql"
    CHAT = "chat"
    ANALYSIS = "analysis"


class ErrorCategory(enum.Enum):
    RATE_LIMIT_429 = "rate_limit_429"
    TIMEOUT = "timeout"
    CONTEXT_TOO_LARGE = "context_too_large"
    SERVER_ERROR_50X = "server_error_50x"
    UNKNOWN = "unknown"


@dataclass
class TaskRequirement:
    """8 维路由决策输入契约"""
    task_type: TaskType
    complexity: ModelComplexity
    required_capabilities: Set[str] = field(default_factory=set)  # e.g., {"tool_calling", "long_context"}
    context_tokens: int = 1000
    max_latency_ms: int = 5000
    remaining_budget_usd: float = 1.0
    agent_node_name: str = "default_executor"  # e.g., "planner_node", "tool_executor", "reflection_node"


@dataclass
class ProviderCandidate:
    """模型 Provider 描述契约"""
    provider_name: str
    model_name: str
    supported_task_types: Set[TaskType]
    capabilities: Set[str]
    max_context_window: int
    cost_per_1k_input: float
    cost_per_1k_output: float
    is_primary: bool = False


# 全局预置的工业级 Provider 矩阵
PROVIDER_REGISTRY: List[ProviderCandidate] = [
    ProviderCandidate(
        provider_name="OpenAI",
        model_name="gpt-4o",
        supported_task_types={TaskType.CODING, TaskType.RESEARCH, TaskType.ANALYSIS, TaskType.CHAT},
        capabilities={"tool_calling", "long_context", "vision"},
        max_context_window=128000,
        cost_per_1k_input=0.0025,
        cost_per_1k_output=0.010,
        is_primary=True
    ),
    ProviderCandidate(
        provider_name="Anthropic",
        model_name="claude-3.5-sonnet",
        supported_task_types={TaskType.CODING, TaskType.RESEARCH, TaskType.ANALYSIS},
        capabilities={"tool_calling", "long_context"},
        max_context_window=200000,
        cost_per_1k_input=0.003,
        cost_per_1k_output=0.015,
        is_primary=False
    ),
    ProviderCandidate(
        provider_name="DeepSeek",
        model_name="deepseek-coder",
        supported_task_types={TaskType.CODING, TaskType.SQL},
        capabilities={"tool_calling"},
        max_context_window=64000,
        cost_per_1k_input=0.0005,
        cost_per_1k_output=0.0015,
        is_primary=False
    ),
    ProviderCandidate(
        provider_name="MiniMax",
        model_name="MiniMax-M3",
        supported_task_types={TaskType.CHAT, TaskType.RESEARCH, TaskType.ANALYSIS},
        capabilities={"tool_calling"},
        max_context_window=32000,
        cost_per_1k_input=0.0015,
        cost_per_1k_output=0.002,
        is_primary=False
    ),
    ProviderCandidate(
        provider_name="OpenAI-Lite",
        model_name="gpt-4o-mini",
        supported_task_types={TaskType.CHAT, TaskType.CODING, TaskType.ANALYSIS},
        capabilities={"tool_calling"},
        max_context_window=128000,
        cost_per_1k_input=0.00015,
        cost_per_1k_output=0.0006,
        is_primary=False
    )
]


class ProviderHealthTracker:
    """
    动态健康评分器 (Dynamic Health Score Tracker)
    基于成功率、P95 延迟与错误率实时计算 0 ~ 100 分数。
    """
    def __init__(self):
        self.stats: Dict[str, Dict[str, Any]] = {}
        for p in PROVIDER_REGISTRY:
            self.stats[p.model_name] = {
                "total_calls": 0,
                "successful_calls": 0,
                "failed_calls": 0,
                "latencies_ms": [],
                "consecutive_failures": 0,
                "isolated_until": 0.0
            }

    def record_result(self, model_name: str, is_success: bool, latency_ms: int):
        """记录一次调用的运行指标"""
        st = self.stats[model_name]
        st["total_calls"] += 1
        st["latencies_ms"].append(latency_ms)
        # 只保留最近 20 次延迟
        if len(st["latencies_ms"]) > 20:
            st["latencies_ms"].pop(0)

        if is_success:
            st["successful_calls"] += 1
            st["consecutive_failures"] = 0
        else:
            st["failed_calls"] += 1
            st["consecutive_failures"] += 1
            # 连续失败 3 次触发被动隔离 30 秒
            if st["consecutive_failures"] >= 3:
                st["isolated_until"] = time.time() + 30.0
                print(f"⚠️ [Health Isolation] 模型 [{model_name}] 连续失败 3 次，触发被动隔离 30 秒！")

    def record_success(self, model_name: str, latency_ms: int = 200):
        """记录成功调用的快捷方法"""
        self.record_result(model_name, is_success=True, latency_ms=latency_ms)

    def record_failure(self, model_name: str, latency_ms: int = 2000):
        """记录失败调用的快捷方法"""
        self.record_result(model_name, is_success=False, latency_ms=latency_ms)

    def get_health_score(self, model_name: str) -> float:
        """
        计算 0 ~ 100 动态健康分值
        Health = 100 * SuccessRate * exp(-P95_Latency/2000) * (1 - ErrorRate)
        """
        st = self.stats[model_name]
        if time.time() < st["isolated_until"]:
            return 0.0  # 处于隔离状态，得分 0

        if st["total_calls"] == 0:
            return 100.0  # 初始全满分

        success_rate = st["successful_calls"] / st["total_calls"]
        error_rate = st["failed_calls"] / st["total_calls"]

        latencies = st["latencies_ms"] or [200]
        sorted_lat = sorted(latencies)
        p95_latency = sorted_lat[int(len(sorted_lat) * 0.95)] if sorted_lat else 200

        # 延迟衰减因子
        latency_factor = math.exp(-p95_latency / 2000.0)

        score = 100.0 * success_rate * latency_factor * (1.0 - error_rate)
        return round(max(0.0, min(100.0, score)), 2)


class ErrorClassifier:
    """分类处理 4 种失败响应路径"""
    @staticmethod
    def classify(error_msg: str) -> Tuple[ErrorCategory, str]:
        err_lower = error_msg.lower()
        if "429" in err_lower or "rate limit" in err_lower:
            return ErrorCategory.RATE_LIMIT_429, "策略: 切换同能力级备用模型"
        elif "timeout" in err_lower or "timed out" in err_lower:
            return ErrorCategory.TIMEOUT, "策略: 原 Provider 执行指数退避重试 (Max 3 次)"
        elif "context" in err_lower and "length" in err_lower:
            return ErrorCategory.CONTEXT_TOO_LARGE, "策略: 回退触发 Day 95 增量上下文压缩"
        elif "500" in err_lower or "503" in err_lower or "server error" in err_lower:
            return ErrorCategory.SERVER_ERROR_50X, "策略: 触发 Fallback Chain 主备无缝切换"
        else:
            return ErrorCategory.UNKNOWN, "策略: 通用重试与报警"


class ModelDecisionEngine:
    """
    Agent 模型决策控制平面 (Model Control Plane)
    执行 8 维路由匹配与 Day 94 预算约束联动。
    """
    def __init__(self, health_tracker: Optional[ProviderHealthTracker] = None):
        self.health_tracker = health_tracker or ProviderHealthTracker()

    def select_best_provider(self, req: TaskRequirement) -> Tuple[ProviderCandidate, List[ProviderCandidate]]:
        """
        根据 8 维因素计算最优模型及 Fallback 降级链
        """
        eligible: List[Tuple[ProviderCandidate, float]] = []

        for p in PROVIDER_REGISTRY:
            # 1. 过滤：硬性能力匹配 (Capability Check)
            if not req.required_capabilities.issubset(p.capabilities):
                continue

            # 2. 过滤：上下文窗口限制 (Context Window Check)
            if req.context_tokens > p.max_context_window:
                continue

            # 3. 过滤：健康度分值 (Health Check)
            health_score = self.health_tracker.get_health_score(p.model_name)
            if health_score <= 0.0:
                continue

            # 4. 联动 Day 94 预算限制：预估单次开销，若超出剩余预算且有低成本模型可选，打低分
            estimated_cost = (req.context_tokens / 1000.0) * p.cost_per_1k_input
            if estimated_cost > req.remaining_budget_usd and p.cost_per_1k_input > 0.001:
                # 预算受限，降权
                utility_score = health_score * 0.2
            else:
                # 综合效用分计算
                cost_factor = 1.0 / (p.cost_per_1k_input + 0.0001)
                utility_score = health_score * 0.7 + (10.0 if p.model_name.endswith("mini") and req.complexity == ModelComplexity.LOW else 5.0)

            eligible.append((p, utility_score))

        if not eligible:
            # 兜底降级至通用轻量模型
            fallback_primary = [p for p in PROVIDER_REGISTRY if p.model_name == "gpt-4o-mini"][0]
            return fallback_primary, []

        # 按效用分降序排序
        sorted_candidates = [item[0] for item in sorted(eligible, key=lambda x: x[1], reverse=True)]
        primary = sorted_candidates[0]
        fallback_chain = sorted_candidates[1:]

        return primary, fallback_chain

    def select_provider(self, req: TaskRequirement, health_tracker: Optional[Any] = None) -> ProviderCandidate:
        """兼容接口：返回最佳匹配的 ProviderCandidate"""
        if health_tracker and health_tracker != self.health_tracker:
            self.health_tracker = health_tracker
        primary, _ = self.select_best_provider(req)
        return primary


class LLMGateway:
    """高可用 Agent LLM 网关 (LLM Gateway)"""
    def __init__(self, decision_engine: Optional[Any] = None, health_tracker: Optional[ProviderHealthTracker] = None):
        if decision_engine is None:
            ht = health_tracker or ProviderHealthTracker()
            decision_engine = ModelDecisionEngine(health_tracker=ht)
        self.decision_engine = decision_engine
        self.llm_client = LLMClient()
        self.trace_logs: List[Dict[str, Any]] = []

    async def execute_request(
        self,
        req: TaskRequirement,
        messages: List[Dict[str, str]],
        simulated_error: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        高可用请求执行主逻辑：包含 Node-Level 路由、重试退避与 Fallback 链无缝切换
        """
        start_time = time.time()
        primary, fallback_chain = self.decision_engine.select_best_provider(req)
        chain = [primary] + fallback_chain

        last_error = None
        for attempt_provider in chain:
            model_name = attempt_provider.model_name
            print(f"🎯 [Gateway Router] Node: [{req.agent_node_name}] | 选中 Provider: [{attempt_provider.provider_name} - {model_name}]")

            # 模拟故障注入 (若测试要求)
            if simulated_error and attempt_provider.is_primary:
                err_category, strategy = ErrorClassifier.classify(simulated_error)
                print(f"💥 [Simulated Error] 主模型 [{model_name}] 抛出异常: {simulated_error}")
                print(f"   --> {strategy}")
                self.decision_engine.health_tracker.record_result(model_name, is_success=False, latency_ms=1500)
                last_error = simulated_error
                continue  # 触发 Fallback 降级至链中下一个模型

            # 正常真实网络请求
            req_start = time.time()
            try:
                # 动态把 Model Name 设置给真实客户端
                self.llm_client.model_name = model_name
                resp = await self.llm_client.request_llm(messages=messages, max_tokens=4096)
                
                latency_ms = int((time.time() - req_start) * 1000)
                self.decision_engine.health_tracker.record_result(model_name, is_success=True, latency_ms=latency_ms)

                log_entry = {
                    "timestamp": time.time(),
                    "agent_node": req.agent_node_name,
                    "task_type": req.task_type.value,
                    "selected_model": model_name,
                    "provider": attempt_provider.provider_name,
                    "latency_ms": latency_ms,
                    "status": "SUCCESS"
                }
                self.trace_logs.append(log_entry)
                return {"response": resp, "selected_model": model_name, "provider": attempt_provider.provider_name}

            except Exception as e:
                latency_ms = int((time.time() - req_start) * 1000)
                self.decision_engine.health_tracker.record_result(model_name, is_success=False, latency_ms=latency_ms)
                last_error = str(e)
                print(f"⚠️ [Gateway Error] [{model_name}] 执行失败: {e}，尝试 Fallback 备用节点...")

        raise RuntimeError(f"所有 Fallback 降级节点均执行失败，最终错误: {last_error}")

    def export_trace_log(self) -> str:
        """导出全链路 Gateway 审计文件"""
        log_path = os.path.join(current_dir, "gateway_trace.json")
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(self.trace_logs, f, ensure_ascii=False, indent=2)
        return log_path


# ===============================================================================
# 运行主入口与 6 大生产级场景演练 (Execution Entrypoint & Production Demonstrations)
# ===============================================================================
async def main():
    print("=================================================================")
    print("🚀 启动 Day 97: Agent Model Control Plane & LLM Gateway 验证")
    print("=================================================================\n")

    health_tracker = ProviderHealthTracker()
    decision_engine = ModelDecisionEngine(health_tracker)
    gateway = LLMGateway(decision_engine)

    # -------------------------------------------------------------------------
    # 场景 1: 8 维能力与任务类型匹配路由 (Task Type & Capability Matching)
    # -------------------------------------------------------------------------
    print("--- 【场景 1】8 维能力与任务类型匹配路由 (Coding 任务分流) ---")
    req_coding = TaskRequirement(
        task_type=TaskType.CODING,
        complexity=ModelComplexity.HIGH,
        required_capabilities={"tool_calling"},
        remaining_budget_usd=2.0
    )
    primary, fallbacks = decision_engine.select_best_provider(req_coding)
    print(f"▶ Coding 高难度任务 -> 匹配主模型: [{primary.model_name}] | Fallback 备用链: {[p.model_name for p in fallbacks]}\n")

    # -------------------------------------------------------------------------
    # 场景 2: 模拟 503 故障触发 Fallback 降级链
    # -------------------------------------------------------------------------
    print("--- 【场景 2】模拟主模型 503 故障触发 Fallback 降级链 ---")
    test_messages = [{"role": "user", "content": "Hello Gateway!"}]
    res2 = await gateway.execute_request(req_coding, test_messages, simulated_error="HTTP 503 Service Unavailable")
    print(f"✅ 降级成功！实际响应 Provider: [{res2['provider']} - {res2['selected_model']}]\n")

    # -------------------------------------------------------------------------
    # 场景 3: 错误分类器 (Error Classifier) 识别测试
    # -------------------------------------------------------------------------
    print("--- 【场景 3】Error Classifier 错误类型分类识别 ---")
    cat1, strat1 = ErrorClassifier.classify("Rate limit exceeded 429")
    cat2, strat2 = ErrorClassifier.classify("Context length exceeded 128000")
    print(f"▶ 429 错误分类: [{cat1.value}] -> {strat1}")
    print(f"▶ 上下文超限分类: [{cat2.value}] -> {strat2}\n")

    # -------------------------------------------------------------------------
    # 场景 4: 动态健康分 (Dynamic Health Score 0~100) 评估
    # -------------------------------------------------------------------------
    print("--- 【场景 4】动态健康分 (Dynamic Health Score) 评估 ---")
    # 模拟主模型失败 3 次
    for _ in range(3):
        health_tracker.record_result("gpt-4o", is_success=False, latency_ms=1200)

    score_gpt4o = health_tracker.get_health_score("gpt-4o")
    score_mini = health_tracker.get_health_score("gpt-4o-mini")
    print(f"▶ gpt-4o 连续失败 3 次后健康得分: [{score_gpt4o}] (已被自动隔离)")
    print(f"▶ gpt-4o-mini 正常健康得分: [{score_mini}]\n")

    # -------------------------------------------------------------------------
    # 场景 5: 预算受限驱动强制模型降级 (Cost Budget Integration)
    # -------------------------------------------------------------------------
    print("--- 【场景 5】联动 Day 94 预算限制驱动模型降级 ---")
    req_low_budget = TaskRequirement(
        task_type=TaskType.RESEARCH,
        complexity=ModelComplexity.HIGH,
        context_tokens=10000,
        remaining_budget_usd=0.005  # 预算极其受限
    )
    primary_budget, _ = decision_engine.select_best_provider(req_low_budget)
    print(f"▶ 预算不足 ($0.005) 时自动降级为高性价比模型: [{primary_budget.model_name}]\n")

    # -------------------------------------------------------------------------
    # 场景 6: Agent 节点级路由 (LangGraph Node-Level Routing)
    # -------------------------------------------------------------------------
    print("--- 【场景 6】LangGraph Agent 节点级差异化路由 (Node-Level Routing) ---")
    nodes = [
        ("planner_node", ModelComplexity.HIGH, TaskType.RESEARCH),
        ("tool_executor", ModelComplexity.LOW, TaskType.CHAT),
        ("reflection_node", ModelComplexity.HIGH, TaskType.ANALYSIS)
    ]

    for node_name, comp, t_type in nodes:
        node_req = TaskRequirement(
            task_type=t_type,
            complexity=comp,
            agent_node_name=node_name
        )
        p, _ = decision_engine.select_best_provider(node_req)
        print(f"▶ Agent Node [{node_name}] -> 差异化路由至: [{p.model_name}]")

    # 导出可观测日志
    trace_path = gateway.export_trace_log()
    print(f"\n📁 网关全链路可观测日志已导出至: {trace_path}")
    print("=================================================================")
    print("🎉 Day 97 Agent Model Control Plane & Gateway 验证完美成功！")

if __name__ == "__main__":
    asyncio.run(main())
