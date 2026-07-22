"""
Memory Consolidator Module.

设计方案说明：
1. **设计意图**：
   本模块为长期事实偏好库提供时序一致性冲突消解与遗忘衰减管理（Memory Consolidator）。
   当用户在不同交互周期陈述了相互矛盾的信息时，系统通过大模型进行时序关系判定（冲突/冗余/兼容），
   并结合艾宾浩斯遗忘曲线对冷记忆执行权重折算与阈值遗忘淘汰，避免大模型生成幻觉。
2. **类结构**：
   - `FactItem`: 包含时间戳和艾宾浩斯留存权重的长期 Facts 实体。
   - `MemoryConsolidator`: 消歧整合与遗忘淘汰管理器。
     - `consolidate_facts(existing_facts, new_fact)`: 对新 Fact 与已有 Facts 执行冲突消歧，返回调整后的最新列表。
     - `apply_time_decay(facts, current_time, decay_rate, threshold)`: 重新折算权重并过滤掉过时冷事实。
3. **时序消解逻辑**：
   - 过滤与新 Fact key 核心特征词相关的旧事实作为冲突判定候选集。
   - 请求大模型判定：
     - `CONFLICT`：新事实推翻了旧事实。将旧事实标记为待物理删除。
     - `REDUNDANT`：重复表达。将旧事实的时间戳重置为最新，留存权重恢复至 1.0。
     - `COMPATIBLE`：不矛盾，可以共存。
"""

import sys
import os
import math
import time
from typing import List, Dict, Any, Optional, Set, Tuple
from pydantic import BaseModel, Field

# 确保导入 config
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from config import get_llm_client
from weekly.w04_prompt_and_http.utils import LLMClient

class FactItem(BaseModel):
    """带时间戳与衰减权重的长期事实偏好数据结构"""
    fact_key: str = Field(description="事实的主体属性名，使用下划线蛇形命名")
    fact_value: str = Field(description="事实的具体内容值")
    timestamp: float = Field(description="事实被记录时的 Unix 时间戳")
    weight: float = Field(default=1.0, description="事实的留存权重，范围 [0.0, 1.0]")


class MemoryConsolidator:
    """记忆整合去重、冲突判定与时间衰减消解管理器。"""

    def __init__(self, client: Optional[LLMClient] = None):
        """初始化消解管理器。

        Args:
            client: 真实大模型请求客户端。
        """
        self.client = client or get_llm_client()

    async def consolidate_facts(
        self, existing_facts: List[FactItem], new_fact: FactItem
    ) -> Tuple[List[FactItem], List[str]]:
        """合并新提取的事实，调用大模型对语义互斥的新旧事实执行消歧，返回消歧后的列表以及待删除的 key 列表。

        Args:
            existing_facts: 用户已存的长期 Facts 列表。
            new_fact: 最新从对话历史中提取出的 Fact 实体。

        Returns:
            元组 (updated_facts, deleted_keys)，其中 updated_facts 是合并后的 Facts 列表，deleted_keys 是被覆盖擦除的 key。
        """
        # 步骤 1: 特征比对与前置缩小候选集，筛选出与新 fact 具有高相关度的旧事实
        # 匹配逻辑：如果 key 中的任何单词（长度大于 3）重合，则视为冲突候选
        candidates: List[FactItem] = []
        new_words = set(new_fact.fact_key.lower().split("_"))
        
        for old_fact in existing_facts:
            old_words = set(old_fact.fact_key.lower().split("_"))
            # 过滤掉短词，比对核心特征词
            intersection = {w for w in new_words.intersection(old_words) if len(w) > 3}
            if intersection:
                candidates.append(old_fact)

        updated_facts = list(existing_facts)
        deleted_keys: List[str] = []

        # 步骤 2: 遍历候选冲突，通过大模型执行时序冲突判定
        for old_fact in candidates:
            system_prompt = (
                "你是一个时序一致性冲突判定引擎。你的任务是分析一条【已有事实】与【最新事实】，判定最新事实是否否定、替代或冲突于已有事实。\n"
                "请严格输出以下三个选项之一，不要包含任何标点符号、解释或说明：\n"
                "1. CONFLICT : 代表最新事实否定、替换或冲突于已有事实，已有事实应该被物理擦除。\n"
                "2. REDUNDANT : 代表最新事实与已有事实语义及倾向完全一致，只是重复提及。\n"
                "3. COMPATIBLE : 代表两个事实描述不同维度的信息，互不矛盾，可以共存。"
            )
            
            user_prompt = (
                f"【已有事实】: key={old_fact.fact_key}, value={old_fact.fact_value}\n"
                f"【最新事实】: key={new_fact.fact_key}, value={new_fact.fact_value}\n"
                f"请输出判定结果 (CONFLICT / REDUNDANT / COMPATIBLE):"
            )
            
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]

            try:
                print(f"[冲突消歧] 正在判定 [{old_fact.fact_key}] 与 [{new_fact.fact_key}] 的时序对立性...")
                decision_text = await self.client.request_llm(messages, temperature=0.1)
                
                # 物理清洗与过滤大模型的思绪块
                clean_decision = decision_text.strip().upper()
                if "</THINK>" in clean_decision:
                    clean_decision = clean_decision.split("</THINK>")[-1].strip()
                
                # 兼容格式前后缀
                for char in ".\"'`[]：: \n\t。，":
                    clean_decision = clean_decision.replace(char, "")

                print(f"[冲突消歧] 判定决策结果 (清洗后): {clean_decision}")

                if "CONFLICT" == clean_decision:
                    # 时序一致性覆盖：将互斥的旧事实从列表中移除，并记录待删除
                    print(f" -> 💥 检测到时序冲突。移除旧事实: [{old_fact.fact_key} -> {old_fact.fact_value}]")
                    if old_fact in updated_facts:
                        updated_facts.remove(old_fact)
                    deleted_keys.append(old_fact.fact_key)
                    
                elif "REDUNDANT" == clean_decision:
                    # 去重合并：更新旧事实的时间戳并恢复满权重，抛弃重复的新事实
                    print(f" -> 🔄 检测到冗余提及。原地重置时间戳并恢复满权重: [{old_fact.fact_key}]")
                    for f in updated_facts:
                        if f.fact_key == old_fact.fact_key:
                            f.timestamp = new_fact.timestamp
                            f.weight = 1.0
                    # 冗余状态直接返回更新后的列表
                    return updated_facts, deleted_keys
                    
            except Exception as e:
                print(f"❌ [冲突消歧] 调用大模型判定时序一致性崩溃: {e}", file=sys.stderr)

        # 若通过所有冲突判定且未被识别为 REDUNDANT，则安全将最新 Fact 追加至列表
        updated_facts.append(new_fact)
        return updated_facts, deleted_keys

    def apply_time_decay(
        self, facts: List[FactItem], current_time: float, decay_rate: float = 0.005, threshold: float = 0.2
    ) -> Tuple[List[FactItem], List[str]]:
        """基于艾宾浩斯遗忘曲线，重算权重并筛选出低于淘汰阈值的冷记忆。

        遗忘公式：weight = exp(-decay_rate * (current_time - timestamp))

        为了便于在日常测试中观察到变化，默认 decay_rate 设为 0.005 (以秒为单位)。
        在实际生产中可调整为更小的系数（以小时或天为单位计算时间差）。

        Args:
            facts: 用户当前所有的长期 Facts。
            current_time: 当前参考 Unix 时间戳。
            decay_rate: 指数衰减速率系数。
            threshold: 遗忘淘汰阈值，低于此值将被擦除。

        Returns:
            元组 (active_facts, decayed_keys)，包含活跃事实列表与物理遗忘的 key 列表。
        """
        active_facts: List[FactItem] = []
        decayed_keys: List[str] = []
        
        for fact in facts:
            # 物理时间差
            elapsed_time = current_time - fact.timestamp
            elapsed_time = max(0.0, elapsed_time)
            
            # 计算遗忘比率
            weight = math.exp(-decay_rate * elapsed_time)
            fact.weight = min(1.0, max(0.0, weight))
            
            if fact.weight >= threshold:
                active_facts.append(fact)
                print(f"[时间衰减] 事实 [{fact.fact_key}] 留存权重: {fact.weight:.3f} >= {threshold} (保留)")
            else:
                print(f"💨 [时间衰减] 事实 [{fact.fact_key}] 留存权重: {fact.weight:.3f} < {threshold} (遗忘物理淘汰)")
                decayed_keys.append(fact.fact_key)
                
        return active_facts, decayed_keys
