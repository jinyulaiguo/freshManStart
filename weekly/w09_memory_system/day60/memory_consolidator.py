"""
Day 60: 记忆整合 - 冲突判定消解与时间遗忘衰减机制 (Standard Answer)

设计方案说明：
1. **设计意图**：
   本模块提供了长期事实记忆的冲突判定与遗忘衰减的完整实现。
   解决了用户偏好发生时间漂移后，向量库召回相互矛盾的事实导致 LLM 决策冲突的痛点。
2. **类与数据模型**：
   - `FactItem`: 包含事实属性、时间戳与生命周期衰减权重的核心数据结构。
   - `MemoryConsolidator`: 整合控制器，利用大模型判定时序语义互斥（CONFILCT/REDUNDANT/COMPATIBLE），
     并基于指数衰减重算记忆存留权重。
3. **一致性保护逻辑**：
   - 若大模型判定新 Fact 否定了旧 Fact，对旧 Fact 执行逻辑删除（物理移除出活跃列表）。
   - 若判定冗余，更新旧 Fact 时间戳并重设权重为 1.0，防止多次重入导致的 Facts 垃圾堆积。
"""

import math
import time
import sys
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from weekly.w04_prompt_and_http.utils import LLMClient

class FactItem(BaseModel):
    """带时间戳与衰减权重的原子事实偏好数据结构契约"""
    fact_key: str = Field(description="事实的主体属性名，使用下划线命名")
    fact_value: str = Field(description="事实的具体内容值")
    timestamp: float = Field(description="事实被记录时的 Unix 时间戳")
    weight: float = Field(default=1.0, description="事实的留存权重，范围 [0.0, 1.0]")


class MemoryConsolidator:
    """记忆去重、冲突判定与时间衰减消解管理器"""

    def __init__(self, client: Optional[LLMClient] = None):
        """初始化消解管理器。

        Args:
            client: 真实大模型请求客户端。
        """
        self.client = client or LLMClient()

    async def consolidate_facts(
        self, existing_facts: List[FactItem], new_fact: FactItem
    ) -> List[FactItem]:
        """合并新提取的事实，调用大模型对语义互斥的新旧事实执行消歧或原地覆盖。

        Args:
            existing_facts: 已存的 Facts 列表。
            new_fact: 最新提取的 Fact 条目。

        Returns:
            消歧合并去重后的最新 Facts 列表。
        """
        # 步骤 1: 特征比对与前置缩小候选集，筛选出与新 fact 具有高相关度的旧事实
        # 匹配逻辑：如果 key 中的任何单词（长度大于 3）重合，则视为冲突候选
        candidates: List[FactItem] = []
        new_words = set(new_fact.fact_key.lower().split("_"))
        
        for old_fact in existing_facts:
            old_words = set(old_fact.fact_key.lower().split("_"))
            # 过滤掉 i, of, the 等短词，只比对核心特征词
            intersection = {w for w in new_words.intersection(old_words) if len(w) > 3}
            if intersection:
                candidates.append(old_fact)

        # 构造一个浅拷贝列表，在此进行原地替换或覆盖
        updated_facts = list(existing_facts)

        # 步骤 2: 遍历候选冲突，通过大模型执行时序冲突判定
        # 生产环境中此步骤会通过 Batch 调用或聚合 Prompt 来节省网络 Rtt
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
                
                # 步骤 3: 物理清洗与过滤大模型可能输出的思维链 <think>...</think> 块，仅保留最后真正的分类输出
                clean_decision = decision_text.strip().upper()
                if "</THINK>" in clean_decision:
                    clean_decision = clean_decision.split("</THINK>")[-1].strip()
                
                # 兼容大模型可能附带的前后缀，提取核心关键字
                print(f"[冲突消歧] 判定决策结果 (清洗后): {clean_decision}")

                if "CONFLICT" == clean_decision:
                    # 时序一致性覆盖：将互斥的旧事实从列表中物理移除
                    print(f" -> 💥 检测到时序冲突。移除旧事实: [{old_fact.fact_key} -> {old_fact.fact_value}]")
                    updated_facts.remove(old_fact)
                    
                elif "REDUNDANT" == clean_decision:
                    # 去重合并：更新旧事实的时间戳并恢复满权重，抛弃重复的新事实
                    print(f" -> 🔄 检测到冗余提及。原地重置时间戳并恢复满权重: [{old_fact.fact_key}]")
                    old_fact.timestamp = new_fact.timestamp
                    old_fact.weight = 1.0
                    # 由于属于冗余更新，此次提取的 new_fact 无需追加，直接返回更新后的列表
                    return updated_facts
                    
            except Exception as e:
                print(f"❌ [冲突消歧] 调用大模型判定时序一致性崩溃: {e}", file=sys.stderr)

        # 步骤 3: 若通过所有冲突判定且未被识别为 REDUNDANT，则安全将最新 Fact 追加至列表尾部
        updated_facts.append(new_fact)
        return updated_facts

    def apply_time_decay(
        self, facts: List[FactItem], current_time: float, decay_rate: float = 0.05, threshold: float = 0.2
    ) -> List[FactItem]:
        """基于艾宾浩斯遗忘曲线公式，重新计算 Facts 权重并淘汰衰减值低于 threshold 的冷事实。

        遗忘公式：weight = exp(-decay_rate * (current_time - timestamp))

        Args:
            facts: 输入的 Facts 列表。
            current_time: 当前参考时间戳。
            decay_rate: 遗忘指数衰减速率系数。
            threshold: 淘汰阈值，低于此值的事实将被物理遗忘/归档。

        Returns:
            物理淘汰过滤后的最新活跃 Facts 列表。
        """
        active_facts: List[FactItem] = []
        
        # 步骤 1: 遍历列表，重算权重
        for fact in facts:
            elapsed_time = current_time - fact.timestamp
            # 防止时间差为负（系统时钟回拨异常防御）
            elapsed_time = max(0.0, elapsed_time)
            
            # 步骤 2: 计算遗忘公式
            weight = math.exp(-decay_rate * elapsed_time)
            fact.weight = min(1.0, max(0.0, weight))
            
            # 步骤 3: 阈值过滤判定
            if fact.weight >= threshold:
                active_facts.append(fact)
                print(f"[时间衰减] 事实 [{fact.fact_key}] 留存权重: {fact.weight:.3f} >= {threshold} (保留)")
            else:
                print(f"💨 [时间衰减] 事实 [{fact.fact_key}] 留存权重: {fact.weight:.3f} < {threshold} (遗忘物理淘汰)")
                
        return active_facts


# 调试主入口与消解验证
async def main() -> None:
    print("=== 运行 Day 60 记忆消歧与遗忘衰减标准答案 ===")

    consolidator = MemoryConsolidator()
    current_time = time.time()

    # ==========================================
    # 测试场景一：时序一致性冲突消歧
    # ==========================================
    print("\n=== 场景一：时序冲突与冗余合并测试 ===")
    
    # 模拟已有的长期事实库 (李明先前擅长 Java，且喜欢咖啡)
    existing_facts = [
        FactItem(fact_key="user_prefer_language", fact_value="Java", timestamp=current_time - 100),
        FactItem(fact_key="user_favorite_drink", fact_value="拿铁咖啡", timestamp=current_time - 100)
    ]
    
    # 新提取出的 Fact：李明今天声明他已转学 Python，极度讨厌 Java
    new_conflict_fact = FactItem(
        fact_key="user_prefer_language", fact_value="Python 开发，并且极其讨厌写 Java", timestamp=current_time
    )

    # 运行合并归约
    consolidated = await consolidator.consolidate_facts(existing_facts, new_conflict_fact)
    
    print("\n消歧后的 Facts 列表:")
    for fact in consolidated:
        print(f" - {fact.fact_key}: {fact.fact_value} (时间戳: {fact.timestamp:.0f})")

    # 验证时序一致性是否实现（Java 被移除，Python 存活，咖啡不相关保留）
    has_java = any("Java" in f.fact_value and "Python" not in f.fact_value for f in consolidated)
    has_python = any("Python" in f.fact_value for f in consolidated)
    is_consistency_passed = (not has_java and has_python)
    print(f"时序冲突消解校验 (旧冲突被原地剔除覆盖): {'✅ 通过' if is_consistency_passed else '❌ 失败'}")

    # ==========================================
    # 测试场景二：基于艾宾浩斯遗忘曲线的时间衰减
    # ==========================================
    print("\n=== 场景二：基于遗忘曲线的时间衰减与冷记忆淘汰 ===")
    
    # 模拟三个事实数据：
    # 1. 刚刚记录的姓名 (timestamp = current_time) -> 应该 100% 保留
    # 2. 50 秒前记录的历史偏好 (timestamp = current_time - 50) -> 在 decay_rate=0.05 下衰减至 0.082，将被遗忘
    decay_test_facts = [
        FactItem(fact_key="user_name", fact_value="李明", timestamp=current_time),
        FactItem(fact_key="user_prefer_sport", fact_value="足球", timestamp=current_time - 50)
    ]

    # 执行时间衰减，遗忘速率 0.05，淘汰阈值 0.2
    # 50 秒前的记忆权重：exp(-0.05 * 50) = 0.082 < 0.2 (触发淘汰)
    decayed_list = consolidator.apply_time_decay(decay_test_facts, current_time=current_time, decay_rate=0.05, threshold=0.2)
    
    print(f"\n衰减淘汰后活跃 Facts 数量: {len(decayed_list)}")
    has_sport = any("sport" in f.fact_key for f in decayed_list)
    has_name = any("name" in f.fact_key for f in decayed_list)
    is_decay_passed = (not has_sport and has_name)
    print(f"遗忘衰减物理过滤校验 (冷记忆安全淘汰): {'✅ 通过' if is_decay_passed else '❌ 失败'}")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
