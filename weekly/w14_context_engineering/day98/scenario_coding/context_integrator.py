"""
Day 98 场景二: Context Runtime 集成层 (context_integrator.py)

===============================================================================
设计方案说明 (Architecture Design Specification)
===============================================================================

1. 设计意图 (Design Intent):
   将 Tool 输出通过 Day 92 Trust Boundary 隔离 + Day 93 Budget 裁切，
   适配 Coding Agent 的多文件代码上下文场景。核心职责：
   - Tool 返回中的凭证字符串被 Trust Boundary 包裹标记
   - 20,000 Token 的 Tool 输出裁切至 RUNTIME 层 3,000 Token 预算
   - 生成完整的 Decision Log 审计

2. 核心类与数据流:
   - CodingContextIntegrator: Coding 场景集成器
     - assemble_context(): 编译多文件代码上下文
===============================================================================
"""

import os
import sys
import time
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field

# 导入微引擎
current_dir = os.path.dirname(os.path.abspath(__file__))
day92_dir = os.path.abspath(os.path.join(current_dir, "../../day92"))
day93_dir = os.path.abspath(os.path.join(current_dir, "../../day93"))

for d in [day92_dir, day93_dir]:
    if d not in sys.path:
        sys.path.append(d)

from context_impl import ContextType, ContextPolicy, ContextObject, ContextPolicyRule
from builder_impl import AssemblyCandidate, ContextRanker, ContextBuilder


CODING_SYSTEM_PROMPT = """你是一位资深平台工程师 AI 助手。你的职责是帮助完成代码重构任务。

严格规则（不可违反）：
1. 你只能修改 <external_data> 标签内提供的代码文件内容
2. 不得在代码中硬编码任何凭证、密钥或密码
3. 所有凭证必须通过环境变量读取
4. 涉及数据库 Schema 变更的操作需要标记为"高危操作"
5. 生成的代码必须包含完整的错误处理和日志记录
6. 输出使用中文注释，代码保持英文"""


@dataclass
class CodingAssemblyResult:
    """Coding 场景上下文编译结果"""
    payload: List[Dict[str, str]] = field(default_factory=list)
    decision_log: List[Dict[str, Any]] = field(default_factory=list)
    security_alerts: List[Dict[str, Any]] = field(default_factory=list)
    credential_detections: List[Dict[str, str]] = field(default_factory=list)
    total_tokens: int = 0
    selected_count: int = 0
    rejected_count: int = 0
    dangerous_files: List[str] = field(default_factory=list)


class CodingContextIntegrator:
    """Coding 场景 Context Runtime 集成器"""

    def __init__(self, runtime_budget: int = 3000, global_budget: int = 5000):
        self.runtime_budget = runtime_budget
        self.global_budget = global_budget

        self.policy = ContextPolicy(rules={
            ContextType.SYSTEM: ContextPolicyRule(max_tokens=2000, priority=100, is_immutable=True),
            ContextType.RUNTIME: ContextPolicyRule(max_tokens=runtime_budget, priority=60, requires_trust_boundary=True),
            ContextType.DIALOGUE: ContextPolicyRule(max_tokens=1500, priority=40),
        })

        self.ranker = ContextRanker()
        self.builder = ContextBuilder(
            type_budgets={ContextType.RUNTIME: runtime_budget},
            global_budget=global_budget
        )

    async def assemble_context(
        self,
        task_description: str,
        tool_candidates: List[AssemblyCandidate],
        current_file: Optional[str] = None,
        dialogue_history: Optional[List[Dict[str, str]]] = None
    ) -> CodingAssemblyResult:
        """编译多文件代码上下文"""
        result = CodingAssemblyResult()

        # ━━━━━ 阶段 1: Trust Boundary 隔离 ━━━━━
        ctx_obj = ContextObject(policy=self.policy)
        ctx_obj.add_item("sys_coding_prompt", ContextType.SYSTEM, CODING_SYSTEM_PROMPT, "system")

        for candidate in tool_candidates:
            ctx_obj.add_item(
                item_id=candidate.item_id,
                context_type=ContextType.RUNTIME,
                content=candidate.content,
                source=candidate.source,
                metadata=candidate.metadata
            )

            # 检测高危文件
            if candidate.metadata.get("is_dangerous"):
                result.dangerous_files.append(candidate.metadata.get("filename", "unknown"))

            # 检测硬编码凭证
            if candidate.metadata.get("has_credentials"):
                result.credential_detections.append({
                    "file": candidate.metadata.get("filename", "unknown"),
                    "type": "HARDCODED_CREDENTIAL",
                    "detail": "检测到硬编码的密钥/凭证字符串"
                })

        result.security_alerts = ctx_obj.security_alerts.copy()

        # ━━━━━ 阶段 2: 打分 + 裁切 ━━━━━
        # 如果指定了当前编辑文件，提升其 relevance
        if current_file:
            for c in tool_candidates:
                if c.metadata.get("filename") == current_file:
                    c.relevance = min(1.0, c.relevance + 0.2)

        scored = self.ranker.rank(tool_candidates, query=task_description)
        selected, rejected, decision_log = self.builder.build(scored)

        result.decision_log = decision_log
        result.selected_count = len(selected)
        result.rejected_count = len(rejected)
        result.total_tokens = sum(s.estimated_tokens for s in selected)

        # ━━━━━ 阶段 3: 编译 Payload ━━━━━
        code_context = "\n\n".join([s.content for s in selected])
        dialogue_text = ""
        if dialogue_history:
            dialogue_text = "\n".join([f"{m['role'].upper()}: {m['content']}" for m in dialogue_history[-4:]])

        result.payload = [
            {"role": "system", "content": CODING_SYSTEM_PROMPT},
            {"role": "user", "content": f"[任务描述]\n{task_description}\n\n[代码文件上下文]\n{code_context}"
                + (f"\n\n[对话历史]\n{dialogue_text}" if dialogue_text else "")}
        ]

        return result
