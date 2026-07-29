"""
Day 98 场景一: 用户偏好 Memory 存储 (memory_store.py)

===============================================================================
设计方案说明 (Architecture Design Specification)
===============================================================================

1. 设计意图 (Design Intent):
   模拟 Agent Memory 系统中存储的用户长期偏好记录。研究员过去 6 个月的交互历史
   被归约为 6 条高价值偏好，用于指导 Agent 的输出格式与内容侧重。
   这些偏好通过 Day 92 ContextObject 的 MEMORY 层注入，确保 Agent 能
   个性化响应而不被 RAG 噪音覆盖。

2. 核心数据结构:
   - USER_PREFERENCES: 6 条研究偏好记录
   - retrieve_user_memory(user_id) -> List[AssemblyCandidate]

3. 核心用例设计意图:
   验证 MEMORY 层在 ContextBuilder 中的优先级高于 RETRIEVAL 层，
   确保用户偏好不被 RAG 结果挤出。
===============================================================================
"""

import os
import sys
import time
from typing import List
from dataclasses import dataclass

# 导入 Day 93/92 的数据模型
current_dir = os.path.dirname(os.path.abspath(__file__))
day93_dir = os.path.abspath(os.path.join(current_dir, "../../day93"))
day92_dir = os.path.abspath(os.path.join(current_dir, "../../day92"))

if day93_dir not in sys.path:
    sys.path.append(day93_dir)
if day92_dir not in sys.path:
    sys.path.append(day92_dir)

from builder_impl import AssemblyCandidate
from context_impl import ContextType


# ═══════════════════════════════════════════════════════════════════════════
# 用户研究偏好语料库 (6 条长期 Memory 记录)
# ═══════════════════════════════════════════════════════════════════════════

USER_PREFERENCES: List[dict] = [
    {
        "id": "mem_001",
        "content": "用户偏好: 在生成研究报告时，必须使用结构化对比表格呈现不同方法/模型间的定量性能差异。表格至少应包含模型名称、参数规模、训练数据、核心指标（如 F1、Spearman ρ）和推理速度列。",
        "relevance": 0.90, "importance": 0.95
    },
    {
        "id": "mem_002",
        "content": "用户偏好: 特别关注 Scaling Law 相关的实验数据与理论分析。在总结论文时，若涉及参数规模与性能的关系曲线，必须单独提取并分析 Scaling 趋势（如对数线性关系、收益递减拐点等）。",
        "relevance": 0.88, "importance": 0.92
    },
    {
        "id": "mem_003",
        "content": "用户偏好: 优先引用高引用量（>100 citations）的论文和顶级会议/期刊（NeurIPS, ICML, Nature Methods, Science）发表的成果。低引用的预印本应标注为 [Preprint] 并降低权重。",
        "relevance": 0.82, "importance": 0.80
    },
    {
        "id": "mem_004",
        "content": "用户偏好: 在技术对比分析中，必须明确区分 (1) 判别式任务（分类/回归/结构预测）和 (2) 生成式任务（蛋白质从头设计），因为不同技术路线在这两类任务上的优劣完全不同。",
        "relevance": 0.85, "importance": 0.88
    },
    {
        "id": "mem_005",
        "content": "用户偏好: 研究报告的最终章节必须包含'未来趋势预判'，需涵盖 (1) 多模态融合方向（序列+结构+功能文本）、(2) 工业应用转化进展（药物设计、酶工程）和 (3) 安全与伦理风险。",
        "relevance": 0.78, "importance": 0.85
    },
    {
        "id": "mem_006",
        "content": "用户偏好: 使用中文撰写研究报告主体，但所有学术术语（如 Masked Language Modeling, Contact Prediction, Scaling Law）保留英文原文。引用格式使用 '[Author et al., Year]' 格式。",
        "relevance": 0.75, "importance": 0.78
    },
]


def retrieve_user_memory(user_id: str = "researcher_bio_001") -> List[AssemblyCandidate]:
    """
    模拟从 Memory 系统检索用户长期偏好

    Args:
        user_id: 用户标识符

    Returns:
        List[AssemblyCandidate]: 6 条偏好记录，context_type=MEMORY
    """
    candidates = []
    for pref in USER_PREFERENCES:
        candidates.append(AssemblyCandidate(
            item_id=pref["id"],
            context_type=ContextType.MEMORY,
            content=pref["content"],
            source=f"memory_store/{user_id}",
            relevance=pref["relevance"],
            importance=pref["importance"],
            created_at=time.time() - 86400 * 30,  # 模拟 30 天前的偏好
            metadata={"user_id": user_id, "type": "preference"}
        ))

    return candidates


if __name__ == "__main__":
    print("=" * 70)
    print("🧠 Day 98 场景一: 用户偏好 Memory 存储验证")
    print("=" * 70)

    memories = retrieve_user_memory()
    print(f"\n📊 Memory 记录总数: {len(memories)}")

    total_tokens = sum(m.estimated_tokens for m in memories)
    print(f"   总估计 Tokens: {total_tokens:,}")

    print("\n📋 偏好记录列表:")
    for m in memories:
        print(f"   [{m.item_id}] rel={m.relevance:.2f} imp={m.importance:.2f} "
              f"| tokens={m.estimated_tokens} | {m.content[:50]}...")
