"""
Day 98 场景三: Audit Agent 主编排器 (audit_agent.py)

自主循环扫描 120 个文件的安全审计编排器。
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

from codebase_simulator import (
    iter_module, get_module_names, get_total_file_count, MODULE_SPECS
)
from compression_controller import CompressionController
from context_integrator import AuditContextIntegrator
from resilience_gateway import ResilienceGateway
from budget_watchdog import BudgetWatchdog


class AuditAgent:
    """
    安全审计 Agent 主编排器

    自主循环扫描 4 个子模块 120 个文件：
    1. 逐文件组装 Context → LLM 审计
    2. 每个子模块完成后触发增量压缩
    3. 遇到故障自动 Fallback
    4. 实时监控预算与 Token 增长
    """

    def __init__(self):
        self.compressor = CompressionController(compression_threshold=4000)
        self.integrator = AuditContextIntegrator(global_budget=5000)
        self.gateway = ResilienceGateway()
        self.watchdog = BudgetWatchdog(task_budget=0.50)

        self.vulnerabilities: List[Dict[str, Any]] = []
        self.scan_progress: Dict[str, Any] = {"current_module": "", "current_file": 0, "total": 0}
        self.is_running = False
        self.is_complete = False

    async def start_audit(self, event_callback: Optional[Callable] = None):
        """启动全面安全审计"""
        self.is_running = True
        self.is_complete = False
        total_files = get_total_file_count()
        self.scan_progress["total"] = total_files

        global_offset = 0

        for module_name in get_module_names():
            self.scan_progress["current_module"] = module_name
            spec = MODULE_SPECS[module_name]

            if event_callback:
                await event_callback("module_start", {
                    "module": module_name,
                    "files": spec["file_count"],
                    "description": spec["description"]
                })

            # 遍历模块中的每个文件
            for file_info in iter_module(module_name, global_offset):
                if not self.is_running:
                    return  # 被取消

                self.scan_progress["current_file"] = file_info.global_index

                if event_callback:
                    await event_callback("scan_progress", {
                        "module": module_name,
                        "filename": file_info.filename,
                        "file_index": file_info.file_index,
                        "global_index": file_info.global_index,
                        "total": total_files
                    })

                # 组装审计 Context
                snapshot_text = self.compressor.get_snapshot_text()
                ctx_result = self.integrator.assemble_audit_payload(
                    file_content=file_info.content,
                    file_info={"filename": file_info.filename, "module": module_name},
                    snapshot_text=snapshot_text,
                    scan_index=file_info.global_index
                )

                # 记录 Token 增长
                if event_callback:
                    await event_callback("token_growth", {
                        "scan_index": file_info.global_index,
                        "total_tokens": ctx_result["total_tokens"],
                        "prefix_hash": ctx_result["prefix_hash"][:12]
                    })

                # LLM 调用 (带容灾)
                llm_result = await self.gateway.call_with_resilience(
                    payload=ctx_result["payload"],
                    scan_index=file_info.global_index,
                    max_tokens=400
                )

                # 记录预算
                budget_update = self.watchdog.record_step(file_info.global_index)
                if event_callback:
                    await event_callback("cost_update", budget_update)

                # 检查故障事件
                if llm_result.get("was_fault"):
                    if event_callback:
                        await event_callback("provider_fault", {
                            "scan_index": file_info.global_index,
                            "model": "gpt-4o",
                            "error": "503 Simulated",
                            "fallback": llm_result.get("model_used"),
                            "health_snapshot": llm_result.get("health_snapshot")
                        })

                # 检查漏洞
                if file_info.has_vulnerability:
                    vuln_entry = {
                        "filename": file_info.filename,
                        "module": module_name,
                        "type": file_info.vulnerability_type,
                        "severity": file_info.vulnerability_detail["severity"],
                        "cve": file_info.vulnerability_detail["cve"],
                        "description": file_info.vulnerability_detail["description"],
                        "scan_index": file_info.global_index
                    }
                    self.vulnerabilities.append(vuln_entry)

                    if event_callback:
                        await event_callback("vulnerability_found", vuln_entry)

                # 累积审计结果到压缩器
                await self.compressor.add_audit_result(
                    file_info={"filename": file_info.filename, "module": module_name},
                    audit_response=llm_result["response_text"]
                )

                # 短暂 yield 让 WebSocket 有机会推送
                await asyncio.sleep(0.05)

            # ━━━ 子模块完成 → 强制增量压缩 ━━━
            compression_event = await self.compressor.force_compress(module_name)

            if event_callback:
                await event_callback("compression_event", {
                    "module": module_name,
                    "version": compression_event.version,
                    "before_tokens": compression_event.before_tokens,
                    "after_tokens": compression_event.after_tokens,
                    "compression_ratio": compression_event.compression_ratio,
                    "retention_rate": compression_event.retention_rate,
                    "repairs_count": len(compression_event.repairs)
                })

            global_offset += spec["file_count"]

        # ━━━ 全部完成 ━━━
        self.is_complete = True
        self.is_running = False

        # 漏洞统计
        vuln_stats = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
        for v in self.vulnerabilities:
            vuln_stats[v["severity"]] = vuln_stats.get(v["severity"], 0) + 1

        if event_callback:
            await event_callback("audit_complete", {
                "total_files": total_files,
                "total_vulns": len(self.vulnerabilities),
                "vuln_stats": vuln_stats,
                "compressions": len(self.compressor.compression_events),
                "faults": self.gateway.total_faults,
                "recoveries": self.gateway.total_recoveries,
                "budget_trace": self.watchdog.get_trace(),
                "prefix_stability": self.integrator.get_prefix_stability(),
            })

    def get_full_trace(self) -> Dict[str, Any]:
        """获取全链路审计数据"""
        vuln_stats = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0}
        for v in self.vulnerabilities:
            vuln_stats[v["severity"]] = vuln_stats.get(v["severity"], 0) + 1

        return {
            "vulnerabilities": self.vulnerabilities,
            "vuln_stats": vuln_stats,
            "compression_chain": self.compressor.get_evolution_chain(),
            "token_growth": self.integrator.token_growth_log,
            "fault_log": self.gateway.get_fault_log(),
            "health_log": self.gateway.get_health_log(),
            "budget_trace": self.watchdog.get_trace(),
            "prefix_stability": self.integrator.get_prefix_stability(),
        }
