"""
Day 98 场景二: Human Approval 审批管理器 (approval_manager.py)

管理 Interrupt 挂起与恢复流程。当 Agent 尝试执行高危操作
（如 database_migrations.py 修改）时触发审批挂起。
"""

import os
import sys
import time
import uuid
import asyncio
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field

current_dir = os.path.dirname(os.path.abspath(__file__))
day94_dir = os.path.abspath(os.path.join(current_dir, "../../day94"))
if day94_dir not in sys.path:
    sys.path.append(day94_dir)

from governance_impl import HumanApprovalRequiredException


@dataclass
class ApprovalRequest:
    """审批请求数据模型"""
    approval_id: str
    filename: str
    operation: str
    reason: str
    estimated_impact: str
    requested_at: float = field(default_factory=time.time)
    status: str = "pending"  # pending / approved / rejected
    resolved_at: Optional[float] = None
    resolved_by: Optional[str] = None


class ApprovalManager:
    """
    Human Approval 审批管理器

    管理高危操作的审批流：
    1. Agent 尝试执行高危操作 → 生成 ApprovalRequest 并挂起 asyncio.Event
    2. 通过 WebSocket 推送审批请求到 Dashboard
    3. 用户在 Dashboard 上确认审批/拒绝 → 触发 Event.set() 唤醒 Agent 恢复或拦截执行
    """

    def __init__(self):
        self.pending_approvals: Dict[str, ApprovalRequest] = {}
        self.resolved_approvals: List[ApprovalRequest] = []
        self.approval_events: Dict[str, asyncio.Event] = {}

    def check_and_request_approval(
        self,
        filename: str,
        operation: str = "modify",
        file_metadata: Optional[Dict] = None
    ) -> Optional[ApprovalRequest]:
        """
        检查是否需要审批

        Args:
            filename: 操作的目标文件
            operation: 操作类型 (modify/delete/execute)
            file_metadata: 文件元数据

        Returns:
            ApprovalRequest 如果需要审批，否则 None
        """
        needs_approval = False
        reason = ""
        impact = ""

        meta = file_metadata or {}

        # 判定规则
        if meta.get("requires_approval"):
            needs_approval = True
            reason = "文件标记为需要人工审批"
            impact = "可能修改生产数据库 Schema"

        if meta.get("is_dangerous"):
            needs_approval = True
            reason = "高危操作文件 — 涉及数据库迁移"
            impact = "直接修改生产数据库 Schema，可能导致数据丢失或服务中断"

        if "migration" in filename.lower() or "database" in filename.lower():
            needs_approval = True
            reason = "数据库相关文件需要 DBA 审批"
            impact = "Schema 变更需要备份确认与 DBA 签字"

        if not needs_approval:
            return None

        # 生成审批请求
        approval = ApprovalRequest(
            approval_id=str(uuid.uuid4())[:8],
            filename=filename,
            operation=operation,
            reason=reason,
            estimated_impact=impact
        )

        self.pending_approvals[approval.approval_id] = approval
        self.approval_events[approval.approval_id] = asyncio.Event()
        return approval

    def resolve_approval(self, approval_id: str, approved: bool, resolved_by: str = "admin") -> bool:
        """
        解决审批请求

        Args:
            approval_id: 审批 ID
            approved: 是否批准
            resolved_by: 审批人

        Returns:
            True 如果审批已解决
        """
        approval = self.pending_approvals.get(approval_id)
        if not approval:
            return False

        approval.status = "approved" if approved else "rejected"
        approval.resolved_at = time.time()
        approval.resolved_by = resolved_by

        del self.pending_approvals[approval_id]
        self.resolved_approvals.append(approval)

        # 唤醒挂起的 asyncio.Event
        event = self.approval_events.pop(approval_id, None)
        if event:
            event.set()

        return True

    async def wait_for_approval(self, approval_id: str, timeout: float = 120.0) -> bool:
        """
        异步挂起等待用户审批结果

        Args:
            approval_id: 审批 ID
            timeout: 最长等待超时秒数，超时自动拦截拒绝

        Returns:
            bool: True 为批准，False 为拒绝/超时
        """
        event = self.approval_events.get(approval_id)
        if event:
            try:
                await asyncio.wait_for(event.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                # 超时自动解决为拒绝
                self.resolve_approval(approval_id, approved=False, resolved_by="system_timeout_reject")

        is_app = self.is_approved(approval_id)
        return is_app if is_app is not None else False

    def is_approved(self, approval_id: str) -> Optional[bool]:
        """检查审批是否已通过"""
        if approval_id in self.pending_approvals:
            return None  # 仍在等待
        for a in self.resolved_approvals:
            if a.approval_id == approval_id:
                return a.status == "approved"
        return None

    def get_approval_log(self) -> List[Dict[str, Any]]:
        """导出审批日志"""
        all_approvals = list(self.pending_approvals.values()) + self.resolved_approvals
        return [
            {
                "approval_id": a.approval_id,
                "filename": a.filename,
                "operation": a.operation,
                "reason": a.reason,
                "impact": a.estimated_impact,
                "status": a.status,
                "requested_at": a.requested_at,
                "resolved_at": a.resolved_at,
                "resolved_by": a.resolved_by
            }
            for a in all_approvals
        ]
