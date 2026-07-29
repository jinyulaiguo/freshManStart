"""
Week 14 Day 93 学员练习模版: Context Assembly Engine (practice.py)

===============================================================================
练习说明 (Exercise Specification)
===============================================================================
本练习目标是实现动态上下文编译器 (Context Assembly Engine) 与两级预算治理。
学员需要补充以下两个核心函数的实现：
1. `ContextRanker.calculate_score()`: 结合 relevance, importance 与时间衰减计算综合分值。
2. `ContextBuilder.build()`: 对候选集降序排序，校验分类与全局 Token 上限，装载满足预算的条目并记录 Decision Log。

请根据提示完成 TODO 部分的代码！
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
    """粗略估算 Token 数量"""
    return max(1, len(text) // 2 + len(text.split()))


@dataclass
class AssemblyCandidate:
    """上下文编译候选对象"""
    item_id: str
    context_type: ContextType
    content: str
    source: str = "internal"
    relevance: float = 0.5
    importance: float = 0.5
    created_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
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
        half_life_seconds: float = 3600.0
    ):
        self.w_r = weight_relevance
        self.w_i = weight_importance
        self.w_t = weight_recency
        self.half_life = half_life_seconds

    def calculate_score(self, candidate: AssemblyCandidate, current_time: Optional[float] = None) -> float:
        """
        TODO 1: 计算单条候选对象的综合得分
        要求：
        1. 计算 delta_t = current_time - candidate.created_at；
        2. 根据半衰期计算 recency = e^(-lambda * delta_t)，其中 lambda = ln(2) / half_life；
        3. 计算 total_score = w_r * relevance + w_i * importance + w_t * recency；
        4. 将得分赋值给 candidate.score 并返回。
        """
        # ---------------------------------------------------------------------
        # TODO: 请在此处实现打分算法逻辑
        # ---------------------------------------------------------------------
        raise NotImplementedError("TODO 1: 请实现 ContextRanker 综合打分与时间衰减算法！")


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
        TODO 2: 执行动态上下文编译主逻辑
        要求：
        1. 调用 self.ranker.calculate_score 为所有候选条目计算得分；
        2. 按 score 降序排序所有候选集；
        3. 维护 category_tokens 与 global_used_tokens 计数器；
        4. 强制添加 System 指令到 ContextObject 中；
        5. 遍历候选集，校验分类上限与全局上限，装载符合预算的条目，记录 decision_logs 决策；
        6. 输出并写入 decision_log.json。
        """
        # ---------------------------------------------------------------------
        # TODO: 请在此处实现 ContextBuilder 上下文编译与两级预算治理
        # ---------------------------------------------------------------------
        raise NotImplementedError("TODO 2: 请实现 ContextBuilder 编译打包与两级预算治理逻辑！")


# ===============================================================================
# 调试主入口 (Debug Main Entrypoint)
# ===============================================================================
async def main():
    print("=================================================================")
    print("📝 运行 Day 93 学员练习调试入口 (practice.py)")
    print("=================================================================\n")

    builder = ContextBuilder(global_max_tokens=2000)
    candidates = [
        AssemblyCandidate(
            item_id="cand_1",
            context_type=ContextType.MEMORY,
            content="示例候选条目",
            relevance=0.8
        )
    ]

    try:
        result = builder.build(candidates, system_instructions="System test")
        print("✅ 恭喜！你的实现成功完成了动态编译！")
    except NotImplementedError as e:
        print(f"📌 [TODO 拦截提示]: {e}")
        print("💡 提示: 请打开 `weekly/w14_context_engineering/day93/practice.py` 完成对应的 TODO 函数。")
        print("💡 参考: 完成后可对照参考标准答案 `weekly/w14_context_engineering/day93/builder_impl.py`。")

if __name__ == "__main__":
    asyncio.run(main())
