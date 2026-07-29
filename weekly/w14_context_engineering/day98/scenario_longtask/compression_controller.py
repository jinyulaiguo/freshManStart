"""
Day 98 场景三: 增量压缩控制器 (compression_controller.py)

封装 Day 95 IncrementalCompressor + SnapshotValidator，
管理长任务中的增量归约压缩与关键变量校验。
"""

import os
import sys
import time
import json
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field

current_dir = os.path.dirname(os.path.abspath(__file__))
day95_dir = os.path.abspath(os.path.join(current_dir, "../../day95"))
w04_dir = os.path.abspath(os.path.join(current_dir, "../../../w04_prompt_and_http"))

for d in [day95_dir, w04_dir]:
    if d not in sys.path:
        sys.path.append(d)

from compressor_impl import IncrementalCompressor, SnapshotValidator, DialogueSnapshot
from utils import LLMClient


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 2 + len(text.split()))


@dataclass
class CompressionEvent:
    """压缩事件记录"""
    version: int
    module_name: str
    before_tokens: int
    after_tokens: int
    compression_ratio: float
    retention_rate: float
    repairs: List[str]
    timestamp: float = field(default_factory=time.time)


class CompressionController:
    """
    长任务增量压缩控制器

    管理长任务中的增量归约压缩循环：
    1. 每个子模块扫描完成后触发一次压缩
    2. SnapshotValidator 校验关键变量留存率
    3. 记录快照演进链到 snapshot_evolution.json
    """

    def __init__(self, compression_threshold: int = 4000):
        self.compressor = IncrementalCompressor()
        self.current_snapshot = DialogueSnapshot(
            goal_and_task="微服务网关安全合规审计 — OWASP Top 10 漏洞扫描",
            architectural_decisions=[],
            key_technical_facts={},
            open_issues_and_next_steps=["启动全模块扫描"],
            version=1
        )
        self.compression_threshold = compression_threshold
        self.accumulated_messages: List[Dict[str, str]] = []
        self.accumulated_tokens: int = 0
        self.compression_events: List[CompressionEvent] = []
        self.total_compressions: int = 0

    async def add_audit_result(
        self,
        file_info: Dict[str, Any],
        audit_response: str
    ):
        """
        累积审计结果消息

        Args:
            file_info: 文件信息
            audit_response: LLM 审计响应
        """
        msg_content = (
            f"[审计: {file_info.get('filename', 'unknown')}]\n"
            f"模块: {file_info.get('module', 'unknown')}\n"
            f"结果: {audit_response[:300]}"
        )

        self.accumulated_messages.append({"role": "assistant", "content": msg_content})
        self.accumulated_tokens += estimate_tokens(msg_content)

    def should_compress(self) -> bool:
        """检查是否达到压缩阈值"""
        return self.accumulated_tokens >= self.compression_threshold

    async def force_compress(self, module_name: str) -> CompressionEvent:
        """
        强制执行增量压缩

        Args:
            module_name: 当前子模块名

        Returns:
            CompressionEvent: 压缩事件记录
        """
        if not self.accumulated_messages:
            return CompressionEvent(
                version=self.current_snapshot.version,
                module_name=module_name,
                before_tokens=0, after_tokens=0,
                compression_ratio=1.0, retention_rate=1.0,
                repairs=[]
            )

        before_tokens = self.accumulated_tokens
        self.total_compressions += 1

        # 调用 Day 95 增量压缩引擎
        try:
            new_snapshot = await self.compressor.compress_incrementally(
                old_snapshot=self.current_snapshot,
                delta_messages=self.accumulated_messages
            )
        except Exception as e:
            # 降级：手动合并
            new_snapshot = DialogueSnapshot(
                goal_and_task=self.current_snapshot.goal_and_task,
                architectural_decisions=self.current_snapshot.architectural_decisions.copy(),
                key_technical_facts=dict(self.current_snapshot.key_technical_facts),
                open_issues_and_next_steps=[f"压缩异常: {str(e)}"],
                version=self.current_snapshot.version + 1
            )

        # Day 95 SnapshotValidator 校验变量留存率
        delta_text = "\n".join([m["content"] for m in self.accumulated_messages])
        retention_rate, repairs = SnapshotValidator.validate_and_repair(
            self.current_snapshot, delta_text, new_snapshot
        )

        # 添加模块扫描进度到 key_technical_facts
        new_snapshot.key_technical_facts[f"MODULE_SCANNED_{module_name.upper().replace('-','_')}"] = "completed"

        after_tokens = estimate_tokens(new_snapshot.to_markdown())

        event = CompressionEvent(
            version=new_snapshot.version,
            module_name=module_name,
            before_tokens=before_tokens,
            after_tokens=after_tokens,
            compression_ratio=round(1 - after_tokens / max(before_tokens, 1), 4),
            retention_rate=retention_rate,
            repairs=repairs
        )

        self.compression_events.append(event)
        self.current_snapshot = new_snapshot
        self.accumulated_messages = []
        self.accumulated_tokens = 0

        return event

    def get_snapshot_text(self) -> str:
        """获取当前快照的 Markdown 文本"""
        return self.current_snapshot.to_markdown()

    def get_evolution_chain(self) -> List[Dict[str, Any]]:
        """获取快照演进链"""
        return [
            {
                "version": e.version,
                "module": e.module_name,
                "before_tokens": e.before_tokens,
                "after_tokens": e.after_tokens,
                "compression_ratio": e.compression_ratio,
                "retention_rate": e.retention_rate,
                "repairs_count": len(e.repairs),
                "timestamp": e.timestamp
            }
            for e in self.compression_events
        ]
