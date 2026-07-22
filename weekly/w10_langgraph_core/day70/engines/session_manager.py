"""
切面引擎 2/3：全链路 Telemetry 审计追踪器 & 切面引擎 3/3：多租户会话管理器

===================================================================================
两个轻量级引擎合并在本文件，各自物理隔离、100% 自包含。
===================================================================================
"""

import uuid
from typing import Any, Optional
from langgraph.checkpoint.memory import MemorySaver
from cve_pipeline.state import CVETriageState


# =============================================================================
# 切面引擎 2/3：全链路 Telemetry 审计追踪器
# =============================================================================

class TelemetryRecorder:
    """全链路 Telemetry 审计追踪器。

    从 CVETriageState 的 node_latency_log 字段中提取各节点的执行延迟与 Token 消耗，
    生成结构化的 Telemetry 报告，供 Web Dashboard 仪表盘渲染使用。

    职责边界：
      - 仅读取 State 数据，不修改 State。
      - 不执行 LLM 调用，不产生网络 I/O。
    """

    @staticmethod
    def extract_summary(state: CVETriageState) -> dict:
        """从最终 State 快照中提取结构化 Telemetry 摘要。

        Args:
            state: 图执行完成后的最终 State 快照。

        Returns:
            包含以下字段的 Telemetry 摘要字典：
            - executed_nodes:      按执行顺序排列的节点执行记录列表
            - total_latency_ms:    所有节点执行延迟总和（毫秒）
            - total_tokens:        全链路 LLM Token 消耗累计
            - patch_iterations:    补丁生成迭代轮次
            - circuit_broken:      是否触发熔断
            - final_verdict:       最终验证结论
            - severity:            漏洞严重性
            - pipeline_outcome:    Pipeline 最终执行结果摘要
        """
        latency_log = state.get("node_latency_log", [])
        total_tokens = state.get("total_llm_tokens", 0)
        patch_retry_count = state.get("patch_retry_count", 0)
        is_circuit_broken = state.get("is_circuit_broken", False)
        validation_verdict = state.get("validation_verdict", "PENDING")
        severity = state.get("severity", "UNKNOWN")
        compliance_report = state.get("compliance_report", "")
        is_safe = state.get("is_input_safe", True)

        total_latency_ms = sum(entry.get("latency_ms", 0) for entry in latency_log)

        # 判断 Pipeline 最终执行结果
        if not is_safe:
            outcome = "BLOCKED_BY_SECURITY_POLICY"
        elif is_circuit_broken:
            degradation = state.get("degradation_payload", {})
            outcome = f"CIRCUIT_BROKEN: {degradation.get('trip_reason', 'UNKNOWN')}"
        elif compliance_report:
            outcome = "COMPLETED_WITH_REPORT"
        else:
            outcome = "UNKNOWN"

        return {
            "executed_nodes": latency_log,
            "total_latency_ms": round(total_latency_ms, 2),
            "total_tokens": total_tokens,
            "patch_iterations": patch_retry_count,
            "circuit_broken": is_circuit_broken,
            "degradation_payload": state.get("degradation_payload", {}),
            "final_verdict": validation_verdict,
            "severity": severity,
            "pipeline_outcome": outcome,
            "tenant_id": state.get("tenant_id", "UNKNOWN"),
            "request_trace_id": state.get("request_trace_id", "N/A"),
        }

    @staticmethod
    def format_node_timeline(state: CVETriageState) -> str:
        """将节点执行日志格式化为可读的时序文本（用于控制台输出）。

        Args:
            state: 图执行完成后的最终 State 快照。

        Returns:
            多行格式化的节点执行时序字符串。
        """
        latency_log = state.get("node_latency_log", [])
        if not latency_log:
            return "  (无节点执行记录)"

        lines = []
        cumulative_ms = 0.0
        for i, entry in enumerate(latency_log):
            node = entry.get("node", "unknown")
            latency = entry.get("latency_ms", 0)
            tokens = entry.get("tokens_used", 0)
            cumulative_ms += latency
            extra_info = ""
            if "verdict" in entry:
                extra_info = f" | 验证: {entry['verdict']}"
            if "severity" in entry:
                extra_info += f" | 严重性: {entry['severity']}"
            if "patch_fingerprint" in entry:
                extra_info += f" | 指纹: {entry['patch_fingerprint']}"
            lines.append(
                f"  [{i+1:02d}] {node:<35} {latency:>8.1f}ms  "
                f"tokens: {tokens:>5}{extra_info}"
            )

        lines.append(f"  {'─'*70}")
        lines.append(
            f"  {'TOTAL':<35} {cumulative_ms:>8.1f}ms  "
            f"tokens: {state.get('total_llm_tokens', 0):>5}"
        )
        return "\n".join(lines)


# =============================================================================
# 切面引擎 3/3：多租户会话管理器
# =============================================================================

class TenantSessionManager:
    """多租户会话持久化管理器。

    封装 LangGraph MemorySaver 与 thread_id 多租户隔离机制，提供：
    - thread_id 生成规则（tenant_id + UUID）
    - 最新状态快照查询
    - 全量 Checkpoint 历史回溯
    - 历史版本回退（Time-Travel）

    Attributes:
        app:         LangGraph CompiledGraph（需绑定 MemorySaver）。
    """

    def __init__(self, compiled_graph_with_checkpointer: Any) -> None:
        """初始化会话管理器。

        Args:
            compiled_graph_with_checkpointer: 绑定了 MemorySaver 的 CompiledGraph。
        """
        self.app = compiled_graph_with_checkpointer

    @staticmethod
    def generate_thread_id(tenant_id: str) -> str:
        """生成多租户隔离的 thread_id。

        命名规则: "{tenant_id}:{uuid4}"，确保不同租户的 thread_id 命名空间物理隔离。

        Args:
            tenant_id: 多租户标识符。

        Returns:
            唯一的 thread_id 字符串。
        """
        return f"{tenant_id}:{uuid.uuid4().hex[:12]}"

    def get_thread_config(self, thread_id: str) -> dict:
        """构建 LangGraph 标准 thread 配置字典。

        Args:
            thread_id: 会话 thread_id。

        Returns:
            {"configurable": {"thread_id": thread_id}} 格式字典。
        """
        return {"configurable": {"thread_id": thread_id}}

    def get_latest_snapshot(self, thread_id: str) -> Any:
        """查询指定 thread_id 的最新 State 快照（StateSnapshot 对象）。

        Args:
            thread_id: 目标会话的 thread_id。

        Returns:
            LangGraph StateSnapshot 对象，包含 .values / .next / .config 等属性。
        """
        config = self.get_thread_config(thread_id)
        return self.app.get_state(config)

    def get_checkpoint_history(self, thread_id: str) -> list:
        """查询指定 thread_id 的全量 Checkpoint 演进历史。

        返回的列表按时间逆序排列（最新快照在前），每个元素为 StateSnapshot 对象。

        Args:
            thread_id: 目标会话的 thread_id。

        Returns:
            StateSnapshot 对象列表。
        """
        config = self.get_thread_config(thread_id)
        return list(self.app.get_state_history(config))

    def rollback_to_checkpoint(self, thread_id: str, checkpoint_id: str) -> Optional[dict]:
        """回退到指定 Checkpoint 版本的 State 快照（Time-Travel）。

        遍历历史 Checkpoint，找到匹配 checkpoint_id 的版本并返回其 State 值。

        Args:
            thread_id:     目标会话的 thread_id。
            checkpoint_id: 目标 Checkpoint ID（从 StateSnapshot.config 中获取）。

        Returns:
            目标 Checkpoint 的 State 值字典，未找到时返回 None。
        """
        history = self.get_checkpoint_history(thread_id)
        for snapshot in history:
            snap_checkpoint_id = snapshot.config.get("configurable", {}).get("checkpoint_id", "")
            if snap_checkpoint_id == checkpoint_id:
                return snapshot.values
        return None

    def list_all_sessions_for_tenant(self, tenant_id: str, known_thread_ids: list[str]) -> list[dict]:
        """列出指定租户的所有已知会话的摘要信息。

        Args:
            tenant_id:         租户 ID（用于过滤属于该租户的 thread_id）。
            known_thread_ids:  已知的 thread_id 列表（由调用方维护）。

        Returns:
            每个会话的摘要字典列表，包含 thread_id、消息数、最新节点等。
        """
        summaries = []
        for thread_id in known_thread_ids:
            if not thread_id.startswith(f"{tenant_id}:"):
                continue
            try:
                snapshot = self.get_latest_snapshot(thread_id)
                if snapshot and snapshot.values:
                    messages = snapshot.values.get("messages", [])
                    summaries.append({
                        "thread_id": thread_id,
                        "message_count": len(messages),
                        "severity": snapshot.values.get("severity", "UNKNOWN"),
                        "last_verdict": snapshot.values.get("validation_verdict", "N/A"),
                        "is_circuit_broken": snapshot.values.get("is_circuit_broken", False),
                        "next_nodes": list(snapshot.next) if snapshot.next else [],
                    })
            except Exception:
                continue
        return summaries
