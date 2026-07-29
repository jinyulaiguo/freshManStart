"""
Week 14 Day 94 生产级项目代码: Enterprise Agent Runtime Cost Governance & AI FinOps 系统 (governance_impl.py)

===============================================================================
设计方案说明 (Architecture Design Specification)
===============================================================================

1. 设计意图 (Design Intent):
   弃用 MVP 阶段粗暴的单体 "Token > Limit => Kill Agent" 熔断阀。
   构建工业级 AI FinOps 与 Agent 运行时成本治理系统 (CostGovernanceEngine)。
   基于云厂商 (OpenAI Projects, Google Vertex AI) 与 LangGraph Interrupt 规范，实现 6 层护栏：
   - Layer 1: Pre-flight Cost Estimator (执行前预估)
   - Layer 2: Hierarchical Budget (Org -> Tenant -> User -> Task 多级预算继承)
   - Layer 3 & 5: Runtime Circuit Breaker (NORMAL -> WARNING -> DEGRADED -> STOP 4 态状态机)
   - Layer 4: Optimization Engine (优雅降级树: 压缩 Context -> 切小模型 -> 禁昂贵 Tool)
   - Layer 6: Human Approval Interrupt (高危险/高开销操作挂起与恢复)

2. 核心类与数据流拓扑 (Class & Data Flow Topology):
   - `GovernanceState` (Enum): 定义 4 态熔断状态。
   - `HierarchicalBudget`: 维护多级预算契约与已消耗美分/Token 计数。
   - `CostPredictor`: 基于预估步数与模型单价矩阵执行事前评估。
   - `OptimizationEngine`: 提供上下文增量压缩、模型降级 (如 GPT-4o -> GPT-4o-mini) 与 Tool 屏蔽。
   - `HumanApprovalController`: 模拟 LangGraph Interrupt 机制挂起生成审批 Token，支持 resume 恢复。
   - `CostGovernanceEngine`: 全局治理中间件，产生全链路审计文件 `cost_trace.json`。

3. 核心用例设计意图 (Test Case Design Intent):
   跑通 4 个真实生产场景：
   - Case 1: 正常任务 pre-flight 预测与无缝执行；
   - Case 2: 消耗达到 70%~90% 时触发 WARNING 与 DEGRADED，自动压缩 Context 配合切换 Mini 模型，优雅完成任务；
   - Case 3: 尝试调用高开销 API，触发 Human Approval Interrupt 挂起，模拟 Admin Approve 恢复执行；
   - Case 4: 预算彻底耗尽，触发状态机 STOP 终止保护。
===============================================================================
"""

import os
import sys
import enum
import time
import json
import asyncio
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field

# 导入 Day 92/93 的核心结构与 Week 4 工具客户端
current_dir = os.path.dirname(os.path.abspath(__file__))
day92_dir = os.path.abspath(os.path.join(current_dir, "../day92"))
w04_dir = os.path.abspath(os.path.join(current_dir, "../../w04_prompt_and_http"))

if day92_dir not in sys.path:
    sys.path.append(day92_dir)
if w04_dir not in sys.path:
    sys.path.append(w04_dir)

from utils import LLMClient


class GovernanceState(enum.Enum):
    """治理状态机 4 态定义"""
    NORMAL = "normal"          # 全功能正常运行 (旗舰模型 + 全量工具)
    WARNING = "warning"        # 触发预警 (记录日志，准备降级队列)
    DEGRADED = "degraded"      # 优雅降级模式 (上下文压缩 + 切小模型 + 禁高贵工具)
    STOP = "stop"              # 配额耗尽，终止断电 protection


@dataclass
class ModelPrice:
    """模型单价表 (每千 Token 美金单价)"""
    input_price_per_1k: float
    output_price_per_1k: float


MODEL_PRICING_TABLE: Dict[str, ModelPrice] = {
    "MiniMax-M3": ModelPrice(0.0015, 0.002),       # 旗舰模型
    "gpt-4o": ModelPrice(0.0025, 0.010),           # 旗舰模型
    "gpt-4o-mini": ModelPrice(0.00015, 0.0006),    # 降级小模型
    "qwen-flash": ModelPrice(0.0001, 0.0002)       # 极速轻量模型
}


@dataclass
class HierarchicalBudget:
    """Layer 2: 多级分层预算继承契约"""
    org_budget_usd: float = 100.0
    tenant_budget_usd: float = 20.0
    user_budget_usd: float = 5.0
    task_budget_usd: float = 0.5

    # 已消耗计算统计
    used_usd: float = 0.0
    used_tokens: int = 0


class CostPredictor:
    """Layer 1: Pre-flight 执行前成本预测器"""
    @staticmethod
    def predict_task_cost(
        task_type: str,
        estimated_steps: int,
        model_name: str,
        avg_tokens_per_step: int = 1500
    ) -> float:
        """
        基于任务类型与历史步数分布计算预期美分开销
        """
        price = MODEL_PRICING_TABLE.get(model_name, MODEL_PRICING_TABLE["MiniMax-M3"])
        # 预估 70% input, 30% output
        input_tokens = estimated_steps * avg_tokens_per_step * 0.7
        output_tokens = estimated_steps * avg_tokens_per_step * 0.3

        cost = (input_tokens / 1000.0 * price.input_price_per_1k) + (output_tokens / 1000.0 * price.output_price_per_1k)
        return round(cost, 6)


class HumanApprovalRequiredException(Exception):
    """Layer 6: 人工审批挂起异常 (模拟 LangGraph Interrupt)"""
    def __init__(self, approval_id: str, reason: str, requested_cost: float):
        self.approval_id = approval_id
        self.reason = reason
        self.requested_cost = requested_cost
        super().__init__(f"Interrupt Required! Approval ID: [{approval_id}] | Reason: {reason} | Requested Cost: ${requested_cost:.4f}")


class OptimizationEngine:
    """
    Layer 4: 优雅降级优化引擎 (Optimization Engine)
    当系统进入 DEGRADED 状态时，执行梯度式降级而不是直接 Kill Agent。
    """
    def __init__(self):
        self.current_model = "MiniMax-M3"
        self.banned_tools: List[str] = []
        self.compression_ratio = 1.0

    def apply_degradation(self, governance_state: GovernanceState) -> Dict[str, Any]:
        """根据治理状态执行降级动作"""
        actions_taken = []
        if governance_state == GovernanceState.DEGRADED:
            # 行内步骤 1：触发 Context 压缩比例调大
            self.compression_ratio = 0.4
            actions_taken.append("Context Compression Triggered (Target: 40% Token Ratio)")

            # 行内步骤 2：切换模型至低成本小模型
            if self.current_model != "gpt-4o-mini":
                self.current_model = "gpt-4o-mini"
                actions_taken.append("Model Downgraded: MiniMax-M3 -> gpt-4o-mini")

            # 行内步骤 3：禁用高花费外部 Tool
            if "expensive_sandbox_search" not in self.banned_tools:
                self.banned_tools.append("expensive_sandbox_search")
                actions_taken.append("Disabled Expensive Tool: 'expensive_sandbox_search'")

        return {
            "current_model": self.current_model,
            "compression_ratio": self.compression_ratio,
            "banned_tools": self.banned_tools,
            "actions": actions_taken
        }


class CostGovernanceEngine:
    """
    企业级 Agent 运行时成本治理主框架 (Cost Governance System)
    解耦组合 6 层护栏，处理 4 态状态机演进与全链路追溯。
    """
    def __init__(self, budget: Optional[HierarchicalBudget] = None):
        self.budget = budget or HierarchicalBudget()
        self.state = GovernanceState.NORMAL
        self.optimizer = OptimizationEngine()
        self.pending_approvals: Dict[str, Dict[str, Any]] = {}
        self.trace_logs: List[Dict[str, Any]] = []

    def evaluate_preflight(self, task_type: str, estimated_steps: int) -> Dict[str, Any]:
        """Layer 1 & 2: 任务前预检与多级预算比对"""
        predicted_cost = CostPredictor.predict_task_cost(
            task_type=task_type,
            estimated_steps=estimated_steps,
            model_name=self.optimizer.current_model
        )

        is_allowed = (self.budget.used_usd + predicted_cost) <= self.budget.task_budget_usd
        log_entry = {
            "timestamp": time.time(),
            "phase": "PREFLIGHT",
            "task_type": task_type,
            "predicted_cost": predicted_cost,
            "available_task_budget": self.budget.task_budget_usd - self.budget.used_usd,
            "allowed": is_allowed
        }
        self.trace_logs.append(log_entry)
        return log_entry

    def update_usage_and_transition(self, added_tokens: int, estimated_call_cost: float) -> GovernanceState:
        """Layer 3 & 5: 更新使用量并驱动 4 态状态机转移"""
        self.budget.used_tokens += added_tokens
        self.budget.used_usd += estimated_call_cost

        usage_ratio = self.budget.used_usd / self.budget.task_budget_usd if self.budget.task_budget_usd > 0 else 1.0

        previous_state = self.state

        # 行内步骤：驱动状态机演进
        if usage_ratio >= 1.0:
            self.state = GovernanceState.STOP
        elif usage_ratio >= 0.85:
            self.state = GovernanceState.DEGRADED
        elif usage_ratio >= 0.65:
            self.state = GovernanceState.WARNING
        else:
            self.state = GovernanceState.NORMAL

        # 触发优化引擎的优雅降级动作
        degrade_info = self.optimizer.apply_degradation(self.state)

        log_entry = {
            "timestamp": time.time(),
            "phase": "RUNTIME_MONITOR",
            "usage_ratio": round(usage_ratio * 100, 2),
            "used_usd": round(self.budget.used_usd, 6),
            "task_budget_usd": self.budget.task_budget_usd,
            "previous_state": previous_state.value,
            "new_state": self.state.value,
            "degradation_actions": degrade_info["actions"]
        }
        self.trace_logs.append(log_entry)
        return self.state

    def check_tool_invocation(self, tool_name: str, estimated_tool_cost: float) -> bool:
        """Layer 6 & Tool 检查：评估高花费 Tool 并决定是否触发 Interrupt 人工审批"""
        # 行内校验 1：如果处于 DEGRADED 状态且该工具被禁，拒绝执行
        if tool_name in self.optimizer.banned_tools:
            print(f"🛑 [Governance Guard] 处于 DEGRADED 降级模式，拦截被禁用工具: '{tool_name}'")
            return False

        # 行内校验 2：如果单次 Tool 费用超过 $0.05 美金阈值，触发 Layer 6 Interrupt 挂起
        if estimated_tool_cost >= 0.05:
            approval_id = f"appr_{int(time.time()*1000)}"
            self.pending_approvals[approval_id] = {
                "tool_name": tool_name,
                "cost": estimated_tool_cost,
                "timestamp": time.time(),
                "approved": False
            }
            print(f"⏸️  [Interrupt Triggered] 工具 '{tool_name}' 单次费用高昂 (${estimated_tool_cost:.4f})，触发 Layer 6 挂起！")
            raise HumanApprovalRequiredException(approval_id, f"Tool {tool_name} High Cost", estimated_tool_cost)

        return True

    def resume_approval(self, approval_id: str) -> bool:
        """Layer 6 人工审批恢复 (Resume Checkpoint)"""
        if approval_id in self.pending_approvals:
            self.pending_approvals[approval_id]["approved"] = True
            print(f"▶️  [Approval Resumed] 管理员已批准 Approval ID: [{approval_id}]，恢复 Agent 运行流程！")
            
            # 追加任务额度以支持后续开销
            self.budget.task_budget_usd += self.pending_approvals[approval_id]["cost"] * 1.5
            log_entry = {
                "timestamp": time.time(),
                "phase": "HUMAN_APPROVAL_RESUME",
                "approval_id": approval_id,
                "new_task_budget": self.budget.task_budget_usd
            }
            self.trace_logs.append(log_entry)
            return True
        return False

    def export_trace_report(self) -> str:
        """导出全链路 AI FinOps 审计日志报告"""
        report_path = os.path.join(current_dir, "cost_trace.json")
        payload = {
            "summary": {
                "final_governance_state": self.state.value,
                "total_used_usd": round(self.budget.used_usd, 6),
                "task_budget_usd": self.budget.task_budget_usd,
                "total_tokens": self.budget.used_tokens,
                "trace_records_count": len(self.trace_logs)
            },
            "trace_details": self.trace_logs
        }
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return report_path


# ===============================================================================
# 运行主入口与 4 大生产级场景演示 (Execution Entrypoint & Production Demonstrations)
# ===============================================================================
async def main():
    print("=================================================================")
    print("🚀 启动 Day 94: Enterprise Cost Governance 系统生产场景验证")
    print("=================================================================\n")

    # 初始化配额与治理引擎 ($0.02 USD 额度测试优雅降级)
    budget = HierarchicalBudget(task_budget_usd=0.02)
    governance = CostGovernanceEngine(budget=budget)
    llm_client = LLMClient()

    # -------------------------------------------------------------------------
    # 场景 1: Layer 1 Pre-flight 预测验证
    # -------------------------------------------------------------------------
    print("--- 【场景 1】Layer 1 执行前成本预测 (Pre-flight Cost Prediction) ---")
    preflight_res = governance.evaluate_preflight(task_type="Research_Report", estimated_steps=5)
    print(f"预测单任务开销: ${preflight_res['predicted_cost']:.6f} | 可用预算: ${preflight_res['available_task_budget']:.6f} | 是否允许对接: {preflight_res['allowed']}\n")

    # -------------------------------------------------------------------------
    # 场景 2: 模拟 8 轮运行触发 WARNING 与 DEGRADED 优雅降级
    # -------------------------------------------------------------------------
    print("--- 【场景 2】模拟持续多轮运行与 4 态状态机优雅降级演进 ---")
    for step in range(1, 7):
        # 模拟步骤消耗
        step_tokens = 800
        step_cost = 0.0035  # 每轮开销 0.0035 美金
        
        # 驱动治理引擎
        new_state = governance.update_usage_and_transition(step_tokens, step_cost)
        print(f"▶ 步骤 {step}: 累加用量 ${governance.budget.used_usd:.4f} / ${governance.budget.task_budget_usd} | 当前治理状态: [{new_state.value.upper()}]")

        if new_state == GovernanceState.DEGRADED:
            print(f"   💡 [优雅降级生效]: 动态应用降级措施 -> {governance.optimizer.apply_degradation(new_state)['actions']}")

        if new_state == GovernanceState.STOP:
            print("   🛑 [STOP 熔断]: 预算彻底耗尽，安全断电！")
            break

        # 尝试发起一次基于当前模型配置的 LLM 调用
        messages = [
            {"role": "system", "content": f"You are running under Governance Model [{governance.optimizer.current_model}]. Be extremely concise."},
            {"role": "user", "content": f"Step {step}: Report current status in 1 sentence."}
        ]
        
        try:
            resp = await llm_client.request_llm(messages=messages, max_tokens=60)
            print(f"   LLM 响应 [{governance.optimizer.current_model}]: {resp.strip()}")
        except Exception as e:
            print(f"   LLM 请求跳过或异常: {e}")
        print()

    # -------------------------------------------------------------------------
    # 场景 3: Layer 6 Human Approval (高花费操作 Interrupt 挂起与 Resume 恢复)
    # -------------------------------------------------------------------------
    print("--- 【场景 3】Layer 6 人工审批 (Human Approval via Interrupt) ---")
    high_cost_tool = "expensive_enterprise_dataset_query"
    estimated_tool_fee = 0.08  # 单次查询高达 $0.08 美金
    
    try:
        governance.check_tool_invocation(high_cost_tool, estimated_tool_fee)
    except HumanApprovalRequiredException as interrupt:
        print(f"⚠️  捕获到中断异常: {interrupt}")
        print("📥 系统已挂起当前 Agent State 到 Checkpoint。发送审批通知给管理员...\n")
        
        # 模拟管理员审核并追加额度批准 Resume
        time.sleep(1)
        print("🧑‍💼 [Admin Dashboard] 管理员审核该请求，点击 'Approve & Resume'...")
        governance.resume_approval(interrupt.approval_id)

    # -------------------------------------------------------------------------
    # 导出 AI FinOps 全链路审计日志
    # -------------------------------------------------------------------------
    trace_path = governance.export_trace_report()
    print(f"\n📁 全链路 AI FinOps 追溯报告已导出至: {trace_path}")
    print("=================================================================")
    print("🎉 Day 94 Enterprise Agent Cost Governance 系统验证成功！")

if __name__ == "__main__":
    asyncio.run(main())
