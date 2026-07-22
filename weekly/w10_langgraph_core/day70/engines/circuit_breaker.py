"""
切面引擎 1/3：多维熔断控制器 (MultiDimensionalCircuitBreaker)

===================================================================================
模块设计方案 (Architectural Design)
===================================================================================
设计意图：
   本模块实现 AOP（面向切面编程）风格的熔断控制器，以代理模式包裹
   CompiledGraph.invoke() 调用。在图执行期间，从多个独立维度监控系统健康状态，
   任意维度触发阈值时立即中止并生成结构化降级快照。

四维熔断策略：
   1. 超步限额 (recursion_limit = 15)：
      - LangGraph 原生机制，在 config 中透传。
      - 捕获 GraphRecursionError，生成降级 Payload。

   2. Token 预算超限 (max_token_budget = 8000)：
      - 在每个节点执行后，读取 State 中的 total_llm_tokens 累计值。
      - 因 LangGraph 同步执行特性，仅在图完成后作后置检查。
      - 若超限，标记降级并截断后续处理。

   3. 状态指纹震荡检测 (Fingerprint Stagnation)：
      - 遍历 node_latency_log 中 code_patch_generator 的执行记录。
      - 若连续 N 轮 patch_fingerprint 相同（代码未发生任何改变），判定震荡熔断。
      - 防止 LLM 陷入生成完全相同代码的死循环。

   4. 总执行延迟预算 (max_latency_ms = 120000)：
      - 记录 invoke 开始时间，结束后计算总耗时。
      - 超出预算时标记 SLA 违规并降级。
===================================================================================
"""

import time
import hashlib
from typing import Any, Optional
from langgraph.errors import GraphRecursionError
from cve_pipeline.state import CVETriageState


# =============================================================================
# 熔断策略配置常量
# =============================================================================

DEFAULT_RECURSION_LIMIT: int = 15
DEFAULT_MAX_TOKEN_BUDGET: int = 8000
DEFAULT_MAX_LATENCY_MS: float = 120_000.0
DEFAULT_FINGERPRINT_STAGNATION_ROUNDS: int = 3  # 连续 N 轮指纹不变则熔断


class MultiDimensionalCircuitBreaker:
    """多维熔断控制器——AOP 切面代理组件。

    以装饰器/代理模式包裹 CompiledGraph.invoke()，实现四维熔断保护：
    超步限额 / Token 预算 / 状态指纹震荡 / 总延迟预算。

    Attributes:
        app:                        LangGraph CompiledGraph 实例。
        recursion_limit:            最大图执行超步数。
        max_token_budget:           全链路最大 LLM Token 消耗预算。
        max_latency_ms:             总执行延迟预算（毫秒）。
        fingerprint_stagnation_rounds: 触发震荡熔断的连续相同指纹轮数。
    """

    def __init__(
        self,
        compiled_graph: Any,
        recursion_limit: int = DEFAULT_RECURSION_LIMIT,
        max_token_budget: int = DEFAULT_MAX_TOKEN_BUDGET,
        max_latency_ms: float = DEFAULT_MAX_LATENCY_MS,
        fingerprint_stagnation_rounds: int = DEFAULT_FINGERPRINT_STAGNATION_ROUNDS,
    ) -> None:
        """初始化多维熔断控制器。

        Args:
            compiled_graph:              LangGraph 编译后的图对象。
            recursion_limit:             最大超步数，透传至 invoke config。
            max_token_budget:            最大 Token 消耗预算（tokens）。
            max_latency_ms:              最大执行延迟预算（毫秒）。
            fingerprint_stagnation_rounds: 补丁指纹连续相同多少轮触发震荡熔断。
        """
        self.app = compiled_graph
        self.recursion_limit = recursion_limit
        self.max_token_budget = max_token_budget
        self.max_latency_ms = max_latency_ms
        self.fingerprint_stagnation_rounds = fingerprint_stagnation_rounds

    async def aexecute_stream(
        self,
        initial_state: CVETriageState,
        thread_config: Optional[dict] = None,
    ):
        """流式下发每个节点执行成果的 AsyncGenerator，供 SSE 端点实现节点实时阶段高亮。

        Args:
            initial_state:  Pipeline 的初始化 State 快照。
            thread_config:  LangGraph thread 配置字典。

        Yields:
            节点更新字典与最终完成字典。
        """
        start_time = time.time()
        config = {"recursion_limit": self.recursion_limit}
        if thread_config:
            config.update(thread_config)

        accumulated_state = dict(initial_state)
        trip_reason: Optional[str] = None

        try:
            async for chunk in self.app.astream(initial_state, config=config, stream_mode="updates"):
                # chunk 格式为 {node_name: node_output_dict}
                for node_name, node_update in chunk.items():
                    # 增量更新到 accumulated_state
                    for k, v in node_update.items():
                        if k == "messages":
                            accumulated_state["messages"] = accumulated_state.get("messages", []) + v
                        elif k == "total_llm_tokens":
                            accumulated_state["total_llm_tokens"] = accumulated_state.get("total_llm_tokens", 0) + v
                        elif k == "node_latency_log":
                            accumulated_state["node_latency_log"] = accumulated_state.get("node_latency_log", []) + v
                        else:
                            accumulated_state[k] = v

                    # 取出当前节点的 latency_log 条目
                    node_logs = node_update.get("node_latency_log", [])
                    log_entry = node_logs[-1] if node_logs else {}

                    yield {
                        "type": "node_update",
                        "node": node_name,
                        "latency_ms": log_entry.get("latency_ms", 0),
                        "tokens_used": log_entry.get("tokens_used", 0),
                        "total_tokens": accumulated_state.get("total_llm_tokens", 0),
                        "severity": accumulated_state.get("severity", "UNKNOWN"),
                        "validation_verdict": accumulated_state.get("validation_verdict", "PENDING"),
                        "log_entry": log_entry,
                    }
        except GraphRecursionError as e:
            trip_reason = f"RECURSION_LIMIT_EXCEEDED (limit={self.recursion_limit}): {e}"

        elapsed_ms = (time.time() - start_time) * 1000

        # 后置多维熔断检查
        if trip_reason is None:
            total_tokens = accumulated_state.get("total_llm_tokens", 0)
            if total_tokens > self.max_token_budget:
                trip_reason = (
                    f"TOKEN_BUDGET_EXCEEDED (consumed={total_tokens} > budget={self.max_token_budget})"
                )

        if trip_reason is None:
            trip_reason = self._detect_fingerprint_stagnation(accumulated_state)

        if trip_reason is None and elapsed_ms > self.max_latency_ms:
            trip_reason = (
                f"LATENCY_BUDGET_EXCEEDED (elapsed={elapsed_ms:.0f}ms > budget={self.max_latency_ms:.0f}ms)"
            )

        if trip_reason:
            accumulated_state = self._build_degraded_state(accumulated_state, trip_reason, elapsed_ms)

        # 提取全量 Telemetry 摘要
        from engines.session_manager import TelemetryRecorder
        telemetry = TelemetryRecorder.extract_summary(accumulated_state)

        yield {
            "type": "done",
            "severity": accumulated_state.get("severity", "UNKNOWN"),
            "cve_id": accumulated_state.get("cve_id", "UNKNOWN"),
            "vulnerability_type": accumulated_state.get("vulnerability_type", "Unknown"),
            "validation_verdict": accumulated_state.get("validation_verdict", "PENDING"),
            "compliance_report": accumulated_state.get("compliance_report", ""),
            "risk_score": accumulated_state.get("risk_score", 0.0),
            "is_circuit_broken": accumulated_state.get("is_circuit_broken", False),
            "degradation_payload": accumulated_state.get("degradation_payload", {}),
            "telemetry": telemetry,
        }

    def execute(
        self,
        initial_state: CVETriageState,
        thread_config: Optional[dict] = None,
    ) -> CVETriageState:
        """带多维熔断保护的图执行主入口。

        Args:
            initial_state:  Pipeline 的初始化 State 快照。
            thread_config:  LangGraph thread 配置字典，包含 configurable.thread_id。

        Returns:
            最终 State 快照（正常完成或降级状态）。
        """
        start_time = time.time()

        # 合并 recursion_limit 到 config
        config = {"recursion_limit": self.recursion_limit}
        if thread_config:
            config.update(thread_config)

        final_state: Optional[CVETriageState] = None
        trip_reason: Optional[str] = None

        # ── 维度 1: 超步限额熔断（通过捕获 GraphRecursionError）──
        try:
            final_state = self.app.invoke(initial_state, config=config)
        except GraphRecursionError as e:
            trip_reason = f"RECURSION_LIMIT_EXCEEDED (limit={self.recursion_limit}): {e}"
            final_state = dict(initial_state)

        elapsed_ms = (time.time() - start_time) * 1000

        if final_state is None:
            final_state = dict(initial_state)

        # ── 维度 2: Token 预算超限检测 ──
        if trip_reason is None:
            total_tokens = final_state.get("total_llm_tokens", 0)
            if total_tokens > self.max_token_budget:
                trip_reason = (
                    f"TOKEN_BUDGET_EXCEEDED (consumed={total_tokens} > budget={self.max_token_budget})"
                )

        # ── 维度 3: 状态指纹震荡检测 ──
        if trip_reason is None:
            trip_reason = self._detect_fingerprint_stagnation(final_state)

        # ── 维度 4: 总延迟预算超限检测 ──
        if trip_reason is None and elapsed_ms > self.max_latency_ms:
            trip_reason = (
                f"LATENCY_BUDGET_EXCEEDED (elapsed={elapsed_ms:.0f}ms > budget={self.max_latency_ms:.0f}ms)"
            )

        # ── 构建降级 Payload（任意维度触发时）──
        if trip_reason:
            return self._build_degraded_state(final_state, trip_reason, elapsed_ms)

        return final_state

    def _detect_fingerprint_stagnation(self, state: CVETriageState) -> Optional[str]:
        """检测补丁生成器的状态指纹震荡。

        从 node_latency_log 中提取所有 code_patch_generator 的执行记录，
        检查最近 N 轮是否产生了相同的 patch_fingerprint（代码未发生有效改变）。

        Args:
            state: 图执行完成后的最终 State 快照。

        Returns:
            震荡熔断原因字符串（触发时）或 None（未触发时）。
        """
        latency_log = state.get("node_latency_log", [])
        # 提取所有补丁生成轮次的指纹
        patch_fingerprints = [
            entry.get("patch_fingerprint", "")
            for entry in latency_log
            if entry.get("node") == "code_patch_generator" and entry.get("patch_fingerprint")
        ]

        if len(patch_fingerprints) >= self.fingerprint_stagnation_rounds:
            recent = patch_fingerprints[-self.fingerprint_stagnation_rounds:]
            # 所有最近 N 轮指纹完全相同 → 震荡熔断
            if len(set(recent)) == 1:
                return (
                    f"PATCH_FINGERPRINT_STAGNATION "
                    f"(连续 {self.fingerprint_stagnation_rounds} 轮补丁代码指纹未变化: {recent[0]})"
                )
        return None

    def _build_degraded_state(
        self,
        snapshot_state: CVETriageState,
        trip_reason: str,
        elapsed_ms: float,
    ) -> CVETriageState:
        """构建结构化降级 State 快照。

        在熔断触发时，冻结当前 State 快照，注入完整的四维诊断数据到
        degradation_payload，并标记 is_circuit_broken = True。

        Args:
            snapshot_state: 触发熔断时的 State 快照（可能为初始 State）。
            trip_reason:    熔断触发原因描述字符串。
            elapsed_ms:     已经过的总执行延迟（毫秒）。

        Returns:
            注入降级标志与诊断数据的 State 快照。
        """
        from langchain_core.messages import AIMessage

        degraded = dict(snapshot_state)
        degraded["is_circuit_broken"] = True

        # 提取关键诊断指标
        latency_log = snapshot_state.get("node_latency_log", [])
        patch_logs = [e for e in latency_log if e.get("node") == "code_patch_generator"]
        fingerprint_history = [e.get("patch_fingerprint", "") for e in patch_logs]

        degraded["degradation_payload"] = {
            "circuit_breaker_tripped": True,
            "trip_reason": trip_reason,
            "elapsed_ms": round(elapsed_ms, 2),
            "total_supersteps_executed": len(latency_log),
            "total_llm_tokens_consumed": snapshot_state.get("total_llm_tokens", 0),
            "patch_iteration_count": snapshot_state.get("patch_retry_count", 0),
            "patch_fingerprint_history": fingerprint_history,
            "last_validation_verdict": snapshot_state.get("validation_verdict", "UNKNOWN"),
            "severity": snapshot_state.get("severity", "UNKNOWN"),
            "tenant_id": snapshot_state.get("tenant_id", "UNKNOWN"),
            "request_trace_id": snapshot_state.get("request_trace_id", "N/A"),
            "recommended_action": "DISPATCH_JIRA_SECURITY_TICKET_AND_NOTIFY_CSE",
        }

        # 追加熔断通知消息
        existing_messages = list(snapshot_state.get("messages", []))
        existing_messages.append(AIMessage(
            content=(
                f"[多维熔断控制器 🔴] 系统触发安全保护熔断。\n"
                f"触发原因: {trip_reason}\n"
                f"已执行节点数: {len(latency_log)}\n"
                f"累计 Token 消耗: {snapshot_state.get('total_llm_tokens', 0)}\n"
                f"已冻结状态快照，生成结构化运维诊断 Ticket。"
            )
        ))
        degraded["messages"] = existing_messages

        return degraded
