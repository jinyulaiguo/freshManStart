"""
Day 98 场景三: Context Runtime 集成层 (context_integrator.py)

适配长任务安全审计场景，将 Day 92+93+96 串联。
"""

import os
import sys
import time
import hashlib
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field

current_dir = os.path.dirname(os.path.abspath(__file__))
day92_dir = os.path.abspath(os.path.join(current_dir, "../../day92"))
day93_dir = os.path.abspath(os.path.join(current_dir, "../../day93"))
day96_dir = os.path.abspath(os.path.join(current_dir, "../../day96"))

for d in [day92_dir, day93_dir, day96_dir]:
    if d not in sys.path:
        sys.path.append(d)

from context_impl import ContextType, ContextPolicy, ContextObject, ContextPolicyRule
from builder_impl import AssemblyCandidate, ContextRanker, ContextBuilder
from layout_impl import ContextSegment, LayoutPlanner, CacheAnalyzer


AUDIT_SYSTEM_PROMPT = """你是一位企业级安全合规审计 AI 助手。你的职责是逐文件审计代码中的安全漏洞。

严格规则：
1. 对每个文件进行 OWASP Top 10 漏洞模式扫描
2. 检测硬编码凭证、SQL 注入、不安全反序列化、路径遍历等
3. 对发现的漏洞标注 CVE 编号和严重程度 (CRITICAL/HIGH/MEDIUM/LOW)
4. 输出格式: 漏洞类型 | 严重程度 | CVE编号 | 修复建议
5. 如果文件安全，输出 "PASS: 未发现安全漏洞"
"""


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 2 + len(text.split()))


class AuditContextIntegrator:
    """长任务审计场景 Context 集成器"""

    def __init__(self, global_budget: int = 5000):
        self.global_budget = global_budget
        self.token_growth_log: List[Dict[str, Any]] = []
        self.prefix_hash_log: List[str] = []

    def assemble_audit_payload(
        self,
        file_content: str,
        file_info: Dict[str, Any],
        snapshot_text: str,
        scan_index: int
    ) -> Dict[str, Any]:
        """
        为单个文件审计组装 Payload

        Args:
            file_content: 文件代码内容
            file_info: 文件元数据
            snapshot_text: 当前压缩快照 Markdown
            scan_index: 全局扫描序号

        Returns:
            Dict: payload, token_stats, prefix_hash
        """
        # 构造 7 层 Layout
        segments = [
            ContextSegment(
                name="audit_rules",
                content=AUDIT_SYSTEM_PROMPT,
                layer_index=1, stability="static", cache_scope="global"
            ),
            ContextSegment(
                name="compliance_template",
                content="[合规模板] OWASP Top 10 + CWE-259 + CWE-798 + PCI-DSS 3.2.1 审计标准",
                layer_index=2, stability="static", cache_scope="global"
            ),
        ]

        # 快照作为 Dialogue (替代原始历史)
        if snapshot_text:
            segments.append(ContextSegment(
                name="dialogue_snapshot",
                content=snapshot_text,
                layer_index=6, stability="dynamic", cache_scope="task"
            ))

        # 当前审计文件
        segments.append(ContextSegment(
            name="current_file",
            content=f"[当前审计文件: {file_info.get('filename', 'unknown')}]\n{file_content}",
            layer_index=7, stability="dynamic", cache_scope="task"
        ))

        # Layout + Cache
        ordered = LayoutPlanner.plan_layout(segments)
        analysis = CacheAnalyzer.analyze_layout(ordered)
        prefix_hash = CacheAnalyzer.compute_prefix_hash(ordered)

        self.prefix_hash_log.append(prefix_hash)

        # 编译 Payload
        system_parts = []
        user_parts = []
        for s in ordered:
            if s.layer_index <= 2:
                system_parts.append(s.content)
            else:
                user_parts.append(s.content)

        payload = [
            {"role": "system", "content": "\n\n".join(system_parts)},
            {"role": "user", "content": "\n\n".join(user_parts)}
        ]

        total_tokens = analysis.get("total_tokens", 0)
        self.token_growth_log.append({
            "scan_index": scan_index,
            "filename": file_info.get("filename", "unknown"),
            "total_tokens": total_tokens,
            "static_ratio": analysis.get("static_prefix_ratio", 0),
            "timestamp": time.time()
        })

        return {
            "payload": payload,
            "total_tokens": total_tokens,
            "prefix_hash": prefix_hash,
            "layout_analysis": analysis,
        }

    def get_prefix_stability(self) -> Dict[str, Any]:
        """检查 Prefix Hash 稳定性"""
        if not self.prefix_hash_log:
            return {"stable": True, "unique_hashes": 0}

        unique = set(self.prefix_hash_log)
        return {
            "stable": len(unique) <= 1,
            "unique_hashes": len(unique),
            "total_checks": len(self.prefix_hash_log),
            "first_hash": self.prefix_hash_log[0][:12] if self.prefix_hash_log else ""
        }
