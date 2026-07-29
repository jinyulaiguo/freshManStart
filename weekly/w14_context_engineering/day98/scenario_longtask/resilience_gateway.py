"""
Day 98 场景三: 容灾网关集成层 (resilience_gateway.py)

封装 Day 97 LLMGateway 并提供故障注入能力。
在第 15、45、85 个文件扫描时模拟主模型 503 故障。
"""

import os
import sys
import time
from typing import Dict, Any, Optional, List, Set
from dataclasses import dataclass, field

current_dir = os.path.dirname(os.path.abspath(__file__))
day97_dir = os.path.abspath(os.path.join(current_dir, "../../day97"))
w04_dir = os.path.abspath(os.path.join(current_dir, "../../../w04_prompt_and_http"))

for d in [day97_dir, w04_dir]:
    if d not in sys.path:
        sys.path.append(d)

from router_gateway_impl import (
    ProviderHealthTracker, ErrorClassifier, ErrorCategory,
    PROVIDER_REGISTRY
)
from utils import LLMClient


FAULT_INJECTION_POINTS: Set[int] = {15, 45, 85}


class ResilienceGateway:
    """
    容灾网关集成层

    封装 Day 97 LLMGateway + ProviderHealthTracker，提供：
    - 故障注入调度器 (在指定文件序号处模拟 503)
    - Fallback 降级链执行
    - 健康分实时跟踪
    """

    def __init__(self):
        self.health_tracker = ProviderHealthTracker()
        self.error_classifier = ErrorClassifier()
        self.client = LLMClient()
        self.fault_log: List[Dict[str, Any]] = []
        self.health_log: List[Dict[str, Any]] = []
        self.total_calls: int = 0
        self.total_faults: int = 0
        self.total_recoveries: int = 0

    async def call_with_resilience(
        self,
        payload: List[Dict[str, str]],
        scan_index: int,
        max_tokens: int = 500
    ) -> Dict[str, Any]:
        """
        带容灾能力的 LLM 调用

        Args:
            payload: Messages Payload
            scan_index: 当前扫描的全局文件序号
            max_tokens: 最大输出 Token

        Returns:
            Dict: response_text, model_used, was_fault, health_snapshot
        """
        self.total_calls += 1

        # 检查是否为故障注入点
        if scan_index in FAULT_INJECTION_POINTS:
            return await self._handle_fault(payload, scan_index, max_tokens)

        # 正常调用
        try:
            start = time.time()
            response = await self.client.request_llm(
                messages=payload, temperature=0.1, max_tokens=max_tokens
            )
            latency = (time.time() - start) * 1000

            # 记录主模型成功
            primary_model = PROVIDER_REGISTRY[0].model_name  # gpt-4o
            self.health_tracker.record_success(primary_model, latency)

            return {
                "response_text": response,
                "model_used": "MiniMax-M3",  # 实际使用的是 MiniMax
                "was_fault": False,
                "latency_ms": round(latency, 1),
                "health_snapshot": self._get_health_snapshot()
            }
        except Exception as e:
            return {
                "response_text": f"[审计结果: 无法连接 LLM] {str(e)[:100]}",
                "model_used": "fallback",
                "was_fault": True,
                "latency_ms": 0,
                "health_snapshot": self._get_health_snapshot()
            }

    async def _handle_fault(
        self, payload: List[Dict[str, str]], scan_index: int, max_tokens: int
    ) -> Dict[str, Any]:
        """处理故障注入"""
        self.total_faults += 1
        primary_model = "gpt-4o"

        # 模拟主模型 503 故障
        self.health_tracker.record_failure(primary_model)

        fault_entry = {
            "scan_index": scan_index,
            "model": primary_model,
            "error": "503 Service Unavailable (Simulated)",
            "timestamp": time.time()
        }

        # 尝试 Fallback
        fallback_model = None
        response_text = ""

        try:
            # 使用实际 LLM 客户端 (会走 MiniMax)
            start = time.time()
            response_text = await self.client.request_llm(
                messages=payload, temperature=0.1, max_tokens=max_tokens
            )
            latency = (time.time() - start) * 1000
            fallback_model = "MiniMax-M3"  # 实际 Fallback
            self.total_recoveries += 1

            fault_entry["fallback_model"] = fallback_model
            fault_entry["recovery"] = True

        except Exception as e:
            response_text = f"[所有模型不可用] {str(e)[:100]}"
            fault_entry["recovery"] = False

        self.fault_log.append(fault_entry)

        # 记录健康快照
        health_snap = self._get_health_snapshot()
        self.health_log.append({
            "scan_index": scan_index,
            "scores": health_snap,
            "event": "fault_injection",
            "timestamp": time.time()
        })

        return {
            "response_text": response_text,
            "model_used": fallback_model or "none",
            "was_fault": True,
            "fault_detail": fault_entry,
            "latency_ms": 0,
            "health_snapshot": health_snap
        }

    def _get_health_snapshot(self) -> Dict[str, float]:
        """获取健康分快照"""
        snapshot = {}
        for p in PROVIDER_REGISTRY:
            snapshot[p.model_name] = self.health_tracker.get_health_score(p.model_name)
        return snapshot

    def get_fault_log(self) -> List[Dict[str, Any]]:
        return self.fault_log

    def get_health_log(self) -> List[Dict[str, Any]]:
        return self.health_log
