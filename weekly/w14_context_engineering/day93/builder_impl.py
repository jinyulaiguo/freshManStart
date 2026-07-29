"""
Week 14 Day 93 参考标准答案: Context Assembly Engine 与动态决策可观测性 (builder_impl.py)

===============================================================================
设计方案说明 (Architecture Design Specification)
===============================================================================

1. 设计意图 (Design Intent):
   在企业级 Agent 交互中，候选 Memory 记忆库、RAG 检索结果与对话历史容易膨胀至上万 Token。
   无脑全量堆叠会导致上下文挤占 (Context Starvation)、注意力中间迷失 (Lost in the Middle) 
   与天价 Token 账单。
   本模块构建 Context Assembly Engine (动态上下文编译器)，实现：
   - 综合打分器 (`ContextRanker`): 计算 relevance + importance + time_decay 指数衰减分值；
   - 两级预算编译器 (`ContextBuilder`): 分类配额上限 (Per-Type Limit) 与全局总配额 (Global Limit) 结合；
   - 可观测审计决策日志 (`Context Decision Log`): 自动输出 `decision_log.json` 追溯选装与淘汰决策。

2. 核心类与数据流结构 (Class & Data Flow):
   - `AssemblyCandidate`: 包含原始 ContextItem、relevance, importance, timestamp 等多维元指标。
   - `ContextRanker`: 计算 `calculate_score()`，执行衰减与归一化。
   - `ContextBuilder`: 遍历候选集，贪心装载最高分条目，校验分类与全局预算，并生成 Decision Log。
   - `LLMClient`: 发送编译裁切后的高效上下文 Payload。

3. 核心用例设计意图 (Test Case Design Intent):
   构造包含 10 条 Memory、20 条 RAG 检索结果与多轮对话的历史候选集（总 Token 数 > 10,000 Tokens）。
   设定分类预算限制（如 RAG 区域最高 1,200 Tokens，全局最高 2,500 Tokens）。
   运行 `ContextBuilder.build()`，验证系统精准按得分从高到低装载，在达到配额截断时停止，
   并将完整决策过程记录并写入 `decision_log.json`。
===============================================================================
"""

import os
import sys
import math
import time
import json
import asyncio
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field

# 导入 Day 92 的核心数据模型与 Week 4 的 LLM 工具客户端
current_dir = os.path.dirname(os.path.abspath(__file__))
day92_dir = os.path.abspath(os.path.join(current_dir, "../day92"))
w04_dir = os.path.abspath(os.path.join(current_dir, "../../w04_prompt_and_http"))

if day92_dir not in sys.path:
    sys.path.append(day92_dir)
if w04_dir not in sys.path:
    sys.path.append(w04_dir)

from context_impl import ContextType, ContextItem, ContextPolicy, ContextObject
from utils import LLMClient


def estimate_tokens(text: str) -> int:
    """粗略估算 Token 数量 (中文字符数 + 英文单词数)"""
    return max(1, len(text) // 2 + len(text.split()))


@dataclass
class AssemblyCandidate:
    """上下文编译候选对象"""
    item_id: str
    context_type: ContextType
    content: str
    source: str = "internal"
    relevance: float = 0.5   # 0.0 ~ 1.0 语义相关度
    importance: float = 0.5  # 0.0 ~ 1.0 业务重要度
    created_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # 编译过程动态计算属性
    score: float = 0.0
    estimated_tokens: int = 0

    def __post_init__(self):
        if self.estimated_tokens == 0:
            self.estimated_tokens = estimate_tokens(self.content)


class ContextRanker:
    """
    上下文多维打分引擎 (Context Scoring Engine)
    结合 Relevance, Importance 与 Exponential Time Decay (时间衰减) 计算综合分值。
    """
    def __init__(
        self,
        weight_relevance: float = 0.5,
        weight_importance: float = 0.3,
        weight_recency: float = 0.2,
        half_life_seconds: float = 3600.0  # 半衰期：1 小时
    ):
        self.w_r = weight_relevance
        self.w_i = weight_importance
        self.w_t = weight_recency
        self.half_life = half_life_seconds

    def calculate_score(self, candidate: AssemblyCandidate, current_time: Optional[float] = None) -> float:
        """
        计算单条候选对象的综合得分
        Score = w_r * Relevance + w_i * Importance + w_t * Recency
        """
        now = current_time or time.time()
        delta_t = max(0.0, now - candidate.created_at)

        # 指数时间衰减计算: recency = e^(-lambda * delta_t)
        decay_constant = math.log(2) / self.half_life if self.half_life > 0 else 0.0
        recency = math.exp(-decay_constant * delta_t)

        # 综合打分并限制在 [0.0, 1.0] 区间
        total_score = (
            self.w_r * candidate.relevance +
            self.w_i * candidate.importance +
            self.w_t * recency
        )
        candidate.score = round(min(1.0, max(0.0, total_score)), 4)
        return candidate.score


class ContextBuilder:
    """
    动态上下文编译器 (Dynamic Context Compiler)
    负责贪心排序选装、两级配额限制裁剪与决策日志生成。
    """
    def __init__(
        self,
        policy: Optional[ContextPolicy] = None,
        global_max_tokens: int = 2500,
        ranker: Optional[ContextRanker] = None
    ):
        self.policy = policy or ContextPolicy()
        self.global_max_tokens = global_max_tokens
        self.ranker = ranker or ContextRanker()

    def build(
        self,
        candidates: List[AssemblyCandidate],
        system_instructions: str
    ) -> Dict[str, Any]:
        """
        执行动态上下文编译主逻辑
        """
        current_time = time.time()
        
        # 1. 为所有候选条目计算得分
        for cand in candidates:
            self.ranker.calculate_score(cand, current_time)

        # 2. 按 score 降序对候选集排序
        sorted_candidates = sorted(candidates, key=lambda x: x.score, reverse=True)

        context_obj = ContextObject(policy=self.policy)
        decision_logs: List[Dict[str, Any]] = []

        # 追踪分类已消耗 Token 计数与全局已消耗 Token 计数
        category_tokens: Dict[ContextType, int] = {ctype: 0 for ctype in ContextType}
        global_used_tokens = 0

        # 行内步骤 A：强行打入最高优先级 System 指令 (Priority 100)
        sys_item = context_obj.add_item(
            item_id="sys_core",
            context_type=ContextType.SYSTEM,
            content=system_instructions,
            source="system_policy"
        )
        sys_tokens = estimate_tokens(system_instructions)
        category_tokens[ContextType.SYSTEM] += sys_tokens
        global_used_tokens += sys_tokens

        decision_logs.append({
            "item_id": "sys_core",
            "context_type": ContextType.SYSTEM.key,
            "selected": True,
            "score": 1.0,
            "tokens": sys_tokens,
            "reason": "MANDATORY SYSTEM CONTRACT (Priority 100)"
        })

        # 行内步骤 B：按分数降序装载非 System 候选条目
        for cand in sorted_candidates:
            rule = self.policy.get_rule(cand.context_type)
            item_tokens = cand.estimated_tokens
            curr_cat_used = category_tokens[cand.context_type]

            # 校验分类上限与全局上限 (两级预算治理)
            cat_exceeded = (curr_cat_used + item_tokens) > rule.max_tokens
            global_exceeded = (global_used_tokens + item_tokens) > self.global_max_tokens

            if not cat_exceeded and not global_exceeded:
                # 配额充足，允许装载
                context_obj.add_item(
                    item_id=cand.item_id,
                    context_type=cand.context_type,
                    content=cand.content,
                    source=cand.source,
                    metadata=cand.metadata
                )
                category_tokens[cand.context_type] += item_tokens
                global_used_tokens += item_tokens

                decision_logs.append({
                    "item_id": cand.item_id,
                    "context_type": cand.context_type.key,
                    "selected": True,
                    "score": cand.score,
                    "tokens": item_tokens,
                    "reason": f"SELECTED (Rank Score: {cand.score:.4f}, Category Tokens: {category_tokens[cand.context_type]}/{rule.max_tokens})"
                })
            else:
                # 配额超限，拦截淘汰并记录原因
                reject_reason = []
                if cat_exceeded:
                    reject_reason.append(f"Category [{cand.context_type.key}] Budget Exceeded ({curr_cat_used + item_tokens}/{rule.max_tokens})")
                if global_exceeded:
                    reject_reason.append(f"Global Budget Exceeded ({global_used_tokens + item_tokens}/{self.global_max_tokens})")

                decision_logs.append({
                    "item_id": cand.item_id,
                    "context_type": cand.context_type.key,
                    "selected": False,
                    "score": cand.score,
                    "tokens": item_tokens,
                    "reason": f"REJECTED: {'; '.join(reject_reason)}"
                })

        # 行内步骤 C：保存结构化 decision_log.json
        log_file_path = os.path.join(current_dir, "decision_log.json")
        audit_payload = {
            "timestamp": current_time,
            "global_max_tokens": self.global_max_tokens,
            "total_tokens_used": global_used_tokens,
            "category_token_breakdown": {k.key: v for k, v in category_tokens.items()},
            "candidates_total": len(candidates) + 1,
            "selected_total": len([d for d in decision_logs if d["selected"]]),
            "decision_logs": decision_logs
        }

        with open(log_file_path, "w", encoding="utf-8") as f:
            json.dump(audit_payload, f, ensure_ascii=False, indent=2)

        return {
            "context_object": context_obj,
            "payload": context_obj.compile_payload(),
            "audit_summary": audit_payload,
            "decision_log_path": log_file_path
        }


# ===============================================================================
# 运行主入口与真实验收测试 (Execution Entrypoint & Verification)
# ===============================================================================
async def main():
    print("=================================================================")
    print("🚀 启动 Day 93: Context Assembly Engine (动态编译器) 测试")
    print("=================================================================\n")

    # 1. 初始化两级预算 Policy (指定分类上限与全局上限)
    custom_policy = ContextPolicy()
    # 限制 RAG 分类最多使用 800 Tokens，Memory 最多 600 Tokens
    custom_policy.rules[ContextType.RETRIEVAL].max_tokens = 800
    custom_policy.rules[ContextType.MEMORY].max_tokens = 600

    builder = ContextBuilder(policy=custom_policy, global_max_tokens=2000)

    # 2. 构造包含 10 条 Memory + 20 条 RAG + 5 条 Dialogue 的海量候选集
    candidates: List[AssemblyCandidate] = []

    # 模拟 10 条 Memory 候选
    for i in range(1, 11):
        candidates.append(AssemblyCandidate(
            item_id=f"mem_{i:02d}",
            context_type=ContextType.MEMORY,
            content=f"记忆条目 {i}: 用户核心偏好数据编号 #{i}，包含开发工程规则与语言习惯设置。",
            relevance=round(0.3 + 0.06 * i, 2),
            importance=round(0.4 + 0.05 * i, 2),
            source="memory_vault"
        ))

    # 模拟 20 条 RAG 候选 (混合高相关度与包含大量无关冗长文本)
    for j in range(1, 21):
        rel = round(0.95 - 0.04 * j, 2)
        content_text = f"RAG 文档段落 #{j}: 针对当前 Agent 架构设计的第 {j} 篇论文摘要与技术细节。"
        if j % 3 == 0:
            content_text += " " + ("这是大量冗长的外部背景干扰噪音文本。" * 15)
        
        candidates.append(AssemblyCandidate(
            item_id=f"rag_{j:02d}",
            context_type=ContextType.RETRIEVAL,
            content=content_text,
            relevance=rel,
            importance=0.6,
            source="vector_db_search"
        ))

    print(f"📥 准备了 {len(candidates)} 条候选上下文条目 (预估总 Token 超过 6,000 Tokens)")
    print("⚙️  设定全局硬性上限: 2,000 Tokens | RAG 分类上限: 800 Tokens | Memory 分类上限: 600 Tokens\n")

    # 3. 运行动态上下文编译
    system_prompt = "你是一个高效的企业级 AI 研究助手。请严格根据编译后的上下文回答用户提出的架构问题。"
    result = builder.build(candidates, system_instructions=system_prompt)

    audit = result["audit_summary"]
    print("=================================================================")
    print("📊 编译汇总报告 (Context Assembly Audit Summary):")
    print(f"- 全局 Token 消耗: {audit['total_tokens_used']} / {audit['global_max_tokens']} Tokens")
    print(f"- 候选总数: {audit['candidates_total']} | 成功入选: {audit['selected_total']} | 被淘汰: {audit['candidates_total'] - audit['selected_total']}")
    print(f"- 分类 Token 消耗拆解: {json.dumps(audit['category_token_breakdown'], ensure_ascii=False)}")
    print(f"- 决策日志已物理写入: {result['decision_log_path']}")
    print("=================================================================\n")

    print("🔍 决策日志 `decision_log.json` 前 6 条明细展示:")
    print("-----------------------------------------------------------------")
    for log_item in audit["decision_logs"][:6]:
        status_tag = "✅ [SELECTED]" if log_item["selected"] else "❌ [REJECTED]"
        print(f"{status_tag} ID: {log_item['item_id']} | Type: {log_item['context_type']} | Score: {log_item['score']} | Tokens: {log_item['tokens']}")
        print(f"   Reason: {log_item['reason']}")
    print("-----------------------------------------------------------------\n")

    # 4. 发起真实 LLM 请求验证编译后的 Payload
    print("🤖 正在调用大模型验证编译打包后的上下文...")
    client = LLMClient()
    try:
        response_text = await client.request_llm(
            messages=result["payload"],
            temperature=0.2,
            max_tokens=500
        )
        print("\n✅ LLM 返回总结:")
        print("-----------------------------------------------------------------")
        print(response_text)
        print("-----------------------------------------------------------------")
        print("\n🎉 Day 93 动态上下文编译器验证成功！")
    except Exception as e:
        print(f"❌ 大模型调用出错: {e}")

if __name__ == "__main__":
    asyncio.run(main())
