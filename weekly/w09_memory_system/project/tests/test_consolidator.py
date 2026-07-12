"""
Memory Consolidator Unit Test Module.

设计方案说明：
1. **设计意图**：
   本测试套件旨在验证长期事实记忆库的时序消歧与艾宾浩斯遗忘淘汰机制。
2. **测试维度**：
   - 时序冲突消歧：新事实（如完全改变主语言）与旧冲突事实共存时，旧事实应被物理删除，新事实应存盘。
   - 重复冗余去重：多次提及相同事实时，不堆积垃圾项，而是原地刷新旧事实的时戳和权重。
   - 时间衰减淘汰：通过模拟一段时间以前的事实，验证指数遗忘衰减公式重新计算权重的准确性，并过滤淘汰冷记忆。
"""

import sys
import os
import time
import pytest
import pytest_asyncio

# 物理定位并添加路径
current_dir = os.path.dirname(os.path.abspath(__file__))
project_dir = os.path.abspath(os.path.join(current_dir, ".."))
if project_dir not in sys.path:
    sys.path.insert(0, project_dir)
if os.path.join(project_dir, "app") not in sys.path:
    sys.path.insert(0, os.path.join(project_dir, "app"))

from app.memory_consolidator import MemoryConsolidator, FactItem

@pytest.mark.asyncio
async def test_conflict_resolution():
    """测试时序一致性冲突消歧 (CONFLICT) 是否生效。"""
    consolidator = MemoryConsolidator()
    current_time = time.time()
    
    # 模拟已有的长期事实库 (李明先前擅长 Java，且喜欢咖啡)
    existing_facts = [
        FactItem(fact_key="user_prefer_language", fact_value="Java 后端工程", timestamp=current_time - 100, weight=0.8),
        FactItem(fact_key="user_favorite_drink", fact_value="拿铁咖啡", timestamp=current_time - 50, weight=0.9)
    ]
    
    # 新提取出的冲突 Fact：李明宣称他已全面转入 Python，讨厌 Java
    new_conflict_fact = FactItem(
        fact_key="user_prefer_language", fact_value="Python 开发，并且极其讨厌写 Java", timestamp=current_time, weight=1.0
    )
    
    # 运行合并消歧
    consolidated, deleted_keys = await consolidator.consolidate_facts(existing_facts, new_conflict_fact)
    
    # 验证 Java 被移除，Python 被追加，咖啡未受波及保留
    has_java = any("Java" in f.fact_value and "Python" not in f.fact_value for f in consolidated)
    has_python = any("Python" in f.fact_value for f in consolidated)
    has_coffee = any("咖啡" in f.fact_value for f in consolidated)
    
    print("\n\n=== [测试] 时序冲突消歧结果 ===")
    print(f"被擦除的旧冲突 Facts 键: {deleted_keys}")
    print("消歧后最终的长期事实:")
    for f in consolidated:
        print(f" - {f.fact_key}: {f.fact_value} (权重: {f.weight:.2f})")
        
    assert not has_java, "旧冲突事实 'Java' 应该被消歧物理移除！"
    assert has_python, "最新事实 'Python' 应当被成功沉淀！"
    assert has_coffee, "无关事实 '咖啡' 应该被予以保留！"
    assert "user_prefer_language" in deleted_keys, "被擦除的键列表里应当包含 'user_prefer_language'"


@pytest.mark.asyncio
async def test_redundant_merging():
    """测试冗余偏好 (REDUNDANT) 去重与时间刷新。"""
    consolidator = MemoryConsolidator()
    current_time = time.time()
    
    # 模拟已存偏好，其权重由于时间已经衰减到了 0.4
    existing_facts = [
        FactItem(fact_key="user_employer", fact_value="Google 公司", timestamp=current_time - 200, weight=0.4)
    ]
    
    # 再次提及同样的事实
    new_redundant_fact = FactItem(
        fact_key="user_employer", fact_value="谷歌公司", timestamp=current_time, weight=1.0
    )
    
    # 运行合并
    consolidated, deleted_keys = await consolidator.consolidate_facts(existing_facts, new_redundant_fact)
    
    print("\n=== [测试] 冗余去重合并结果 ===")
    print("去重合并后事实:")
    for f in consolidated:
        print(f" - {f.fact_key}: {f.fact_value} (最新时间戳: {f.timestamp:.0f}, 权重: {f.weight:.2f})")
        
    assert len(consolidated) == 1, "去重后事实数应仍为 1"
    assert consolidated[0].weight == 1.0, "冗余提及后，旧事实的留存权重应当原地重置为 1.0 满权重！"
    assert consolidated[0].timestamp == current_time, "冗余提及后，旧事实的时间戳应当刷新为最新！"


def test_time_decay():
    """测试艾宾浩斯时间遗忘衰减与阈值淘汰。"""
    consolidator = MemoryConsolidator()
    current_time = time.time()
    
    # 构造两个事实：
    # 1. 刚记录的事实 (时间差 0) -> 衰减后应该接近 1.0
    # 2. 500 秒前记录的事实 -> 在 decay_rate=0.005 下，衰减权重为 exp(-0.005 * 500) = 0.082 < 0.2 淘汰阈值
    decay_test_facts = [
        FactItem(fact_key="user_name", fact_value="李明", timestamp=current_time, weight=1.0),
        FactItem(fact_key="user_prefer_sport", fact_value="足球", timestamp=current_time - 500, weight=1.0)
    ]
    
    # 执行时间衰减，衰减速率 0.005，淘汰阈值 0.2
    active_facts, decayed_keys = consolidator.apply_time_decay(
        decay_test_facts, current_time=current_time, decay_rate=0.005, threshold=0.2
    )
    
    print("\n=== [测试] 艾宾浩斯时间衰减结果 ===")
    print(f"被遗忘淘汰的 Facts 键: {decayed_keys}")
    print("保留的活跃事实:")
    for f in active_facts:
        print(f" - {f.fact_key}: {f.fact_value} (折算后权重: {f.weight:.3f})")
        
    assert "user_name" in [f.fact_key for f in active_facts], "新事实 'user_name' 应当被正常保留"
    assert "user_prefer_sport" not in [f.fact_key for f in active_facts], "老事实 'user_prefer_sport' 应当低于 0.2 被物理遗忘"
    assert "user_prefer_sport" in decayed_keys, "被物理淘汰的键列表里应当包含 'user_prefer_sport'"
