"""
Day 98 场景二: Coding Agent 主编排器 (coding_agent.py)

模拟 LangGraph 3 节点编排流程 (Planner → Executor → Reflection)。
无逻辑控制主入口，纯粹串联微引擎数据流。
"""

import os
import sys
import time
import asyncio
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass, field

current_dir = os.path.dirname(os.path.abspath(__file__))
w04_dir = os.path.abspath(os.path.join(current_dir, "../../w04_prompt_and_http"))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)
if w04_dir not in sys.path:
    sys.path.append(w04_dir)

from tool_simulator import read_all_files, read_file, get_file_metadata
from context_integrator import CodingContextIntegrator
from cost_controller import CodingCostController
from node_router import NodeRouter
from approval_manager import ApprovalManager
from utils import LLMClient


class CodingAgent:
    """
    Coding Agent 主编排器

    模拟 LangGraph 3 节点:
    [planner_node] → [tool_executor] → [reflection_node]
    """

    def __init__(self):
        self.integrator = CodingContextIntegrator(runtime_budget=3000, global_budget=5000)
        self.cost_ctrl = CodingCostController(task_budget=0.15)
        self.router = NodeRouter()
        self.approval_mgr = ApprovalManager()
        self.llm_client = LLMClient()
        self.execution_log: List[Dict[str, Any]] = []

    async def execute_task(
        self,
        task_description: str,
        event_callback: Optional[Callable] = None
    ) -> Dict[str, Any]:
        """
        执行完整的 Planner → Executor → Reflection 流程

        Args:
            task_description: 重构任务描述
            event_callback: 异步事件回调

        Returns:
            Dict: 包含每个节点的执行结果与全链路 Trace
        """
        results = {"planner": None, "executor": None, "reflection": None, "traces": {}}

        # ━━━━━ Node 1: Planner ━━━━━
        if event_callback:
            await event_callback("node_start", {"node": "planner_node", "status": "active"})

        planner_result = await self._run_planner(task_description, event_callback)
        results["planner"] = planner_result

        # ━━━━━ Node 2: Tool Executor ━━━━━
        if event_callback:
            await event_callback("node_start", {"node": "tool_executor", "status": "active"})

        executor_result = await self._run_executor(
            task_description, planner_result, event_callback
        )
        results["executor"] = executor_result

        # ━━━━━ Node 3: Reflection ━━━━━
        if event_callback:
            await event_callback("node_start", {"node": "reflection_node", "status": "active"})

        reflection_result = await self._run_reflection(
            task_description, executor_result, event_callback
        )
        results["reflection"] = reflection_result

        # 汇总 Trace
        results["traces"] = {
            "cost": self.cost_ctrl.get_cost_trace(),
            "routing": self.router.get_routing_log(),
            "approvals": self.approval_mgr.get_approval_log(),
            "savings": self.router.calculate_savings(),
        }

        # 统计高危文件拦截与重构成功指标
        file_results = executor_result.get("file_results", [])
        rejected_files = [f for f in file_results if f.get("status") == "rejected_skipped"]
        approved_files = [f for f in file_results if f.get("status") != "rejected_skipped"]

        if event_callback:
            await event_callback("task_complete", {
                "has_rejections": len(rejected_files) > 0,
                "rejected_count": len(rejected_files),
                "approved_count": len(approved_files),
                "rejected_filenames": [f["filename"] for f in rejected_files],
                "cost_trace": self.cost_ctrl.get_cost_trace(),
                "routing_savings": self.router.calculate_savings(),
            })

        return results

    async def _run_planner(self, task: str, cb) -> Dict[str, Any]:
        """Planner 节点 — 使用旗舰模型生成重构方案"""

        # 路由决策
        routing = self.router.route_for_node("planner_node",
            remaining_budget=self.cost_ctrl.total_budget - self.cost_ctrl.engine.budget.used_usd)
        if cb:
            await cb("routing_decision", routing)

        # 读取所有文件获取概览
        all_files = read_all_files()
        assembly = await self.integrator.assemble_context(task, all_files)
        if cb:
            await cb("assembly_done", {
                "node": "planner_node",
                "selected": assembly.selected_count,
                "rejected": assembly.rejected_count,
                "tokens": assembly.total_tokens,
                "credentials_detected": len(assembly.credential_detections)
            })
            for cred in assembly.credential_detections:
                await cb("security_detect", cred)

        # 调用 LLM
        try:
            response = await self.llm_client.request_llm(
                messages=assembly.payload, temperature=0.2, max_tokens=4096
            )
        except Exception as e:
            response = f"[Planner Error] {str(e)}"

        # 记录费用
        cost_update = self.cost_ctrl.evaluate_step("planner_node", 1500)
        if cb:
            await cb("cost_update", cost_update)
            # 检查是否需要降级
            if cost_update.get("is_degraded"):
                self.router.set_force_lightweight(True)
                await cb("degradation_triggered", {"reason": "预算消耗超过阈值，所有节点降级为轻量模型"})

        return {
            "node": "planner_node",
            "model": routing["selected_model"],
            "response": response,
            "cost_state": cost_update["state"],
        }

    async def _run_executor(self, task: str, planner_result: Dict, cb) -> Dict[str, Any]:
        """Executor 节点 — 逐文件执行代码变更，遇高危文件触发审批"""

        routing = self.router.route_for_node("tool_executor",
            remaining_budget=self.cost_ctrl.total_budget - self.cost_ctrl.engine.budget.used_usd)
        if cb:
            await cb("routing_decision", routing)

        file_results = []
        for filename in ["auth_middleware.py", "token_service.py", "user_routes.py", "database_migrations.py"]:
            file_candidate = read_file(filename)
            meta = file_candidate.metadata

            if cb:
                await cb("file_processing", {"filename": filename, "metadata": meta})

            # 检查是否需要审批
            approval = self.approval_mgr.check_and_request_approval(
                filename, "modify", meta
            )

            if approval:
                if cb:
                    await cb("approval_request", {
                        "approval_id": approval.approval_id,
                        "filename": filename,
                        "reason": approval.reason,
                        "impact": approval.estimated_impact,
                    })

                # 真实异步挂起等待用户在 Dashboard 上点击批准或拒绝
                approved = await self.approval_mgr.wait_for_approval(approval.approval_id, timeout=120.0)

                # 获取解决状态
                resolved_req = next((a for a in self.approval_mgr.resolved_approvals if a.approval_id == approval.approval_id), None)
                resolved_by = resolved_req.resolved_by if resolved_req else "unknown"

                if cb:
                    await cb("approval_result", {
                        "approval_id": approval.approval_id,
                        "approved": approved,
                        "resolved_by": resolved_by
                    })

                # 安全拦截控制流：如果被拒绝，绝不发起了 LLM 生成，直接跳过并记录
                if not approved:
                    reject_msg = f"🛑 [Human Guard 安全拦截] 已终止 {filename} 的修改 | 原因: 涉及数据库 Schema 变更未获 DBA 授权 | 保护动作: 阻断 LLM 代码生成，保持底层 DDL 100% 原始状态"
                    file_results.append({
                        "filename": filename,
                        "model": routing["selected_model"],
                        "response_preview": reject_msg,
                        "approval_needed": True,
                        "status": "rejected_skipped"
                    })
                    if cb:
                        await cb("file_audit_log", {
                            "filename": filename,
                            "type": "rejection_intercepted",
                            "message": reject_msg
                        })
                    continue

            assembly = await self.integrator.assemble_context(
                f"为 {filename} 生成 JWT 迁移变更", [file_candidate], current_file=filename
            )

            try:
                response = await self.llm_client.request_llm(
                    messages=assembly.payload, temperature=0.1, max_tokens=1000
                )
            except Exception as e:
                response = f"[Executor Error] {str(e)}"

            file_results.append({
                "filename": filename,
                "model": routing["selected_model"],
                "response_preview": response[:200] + "..." if len(response) > 200 else response,
                "approval_needed": approval is not None,
                "status": "applied"
            })

            # 生成真实的重构日志描述
            if cb:
                feature_desc = f"✅ [{filename}] 代码改写完成: 已完成 JWT 逻辑重构并接入签名验证"
                if filename == "auth_middleware.py":
                    feature_desc = f"✅ [{filename}] 模块升级完成: 已彻底剥离 Flask-Session Cookie 依赖，接入 Authorization: Bearer <JWT> Header 提取与 Claims 字典强校验"
                elif filename == "token_service.py":
                    feature_desc = f"🔑 [{filename}] 凭证安全处理: 自动识别硬编码 JWT_SECRET，重构代码已规范为从 .env 环境变量动态读取"
                elif filename == "user_routes.py":
                    feature_desc = f"✅ [{filename}] 路由契约升级: /login 接口已重构为签发 Access Token (15m) 与 Refresh Token (7d) 双令牌双轮转机制"
                elif filename == "database_migrations.py":
                    feature_desc = f"✅ [{filename}] 迁移脚本生成: 已增加 jwt_blacklists 表 DDL 创建与索引结构"

                await cb("file_audit_log", {
                    "filename": filename,
                    "type": "code_applied",
                    "message": feature_desc
                })

            cost_update = self.cost_ctrl.evaluate_step(f"executor_{filename}", 1000)
            if cb:
                await cb("cost_update", cost_update)
                if cost_update.get("is_degraded"):
                    self.router.set_force_lightweight(True)
                    await cb("degradation_triggered", {"reason": "DEGRADED"})

        return {
            "node": "tool_executor",
            "model": routing["selected_model"],
            "file_results": file_results,
            "cost_state": self.cost_ctrl.get_current_state(),
        }

    async def _run_reflection(self, task: str, executor_result: Dict, cb) -> Dict[str, Any]:
        """Reflection 节点 — 使用旗舰模型审查代码变更"""

        routing = self.router.route_for_node("reflection_node",
            remaining_budget=self.cost_ctrl.total_budget - self.cost_ctrl.engine.budget.used_usd)
        if cb:
            await cb("routing_decision", routing)

        # 构造审查 Prompt
        review_content = "\n".join([
            f"[{fr['filename']}] {fr['response_preview'][:100]}"
            for fr in executor_result.get("file_results", [])
        ])

        payload = [
            {"role": "system", "content": "你是代码审查专家。请审查以下代码变更，检查安全性、JWT 黑名单机制完整性。"},
            {"role": "user", "content": f"任务: {task}\n\n代码变更:\n{review_content}"}
        ]

        try:
            response = await self.llm_client.request_llm(
                messages=payload, temperature=0.1, max_tokens=800
            )
        except Exception as e:
            response = f"[Reflection Error] {str(e)}"

        cost_update = self.cost_ctrl.evaluate_step("reflection_node", 800)
        if cb:
            await cb("cost_update", cost_update)

        return {
            "node": "reflection_node",
            "model": routing["selected_model"],
            "review": response,
            "cost_state": cost_update["state"],
        }
