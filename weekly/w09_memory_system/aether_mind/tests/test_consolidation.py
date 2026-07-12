"""
AetherMind Memory Consolidation & Decay Test
============================================

设计意图:
---------
1. 验证 `MemoryConsolidator` 的时序冲突消歧正确性。
   输入冲突的事实（如 "常用 smolagents" -> "讨厌 smolagents 转用 Letta"），
   验证旧冲突事实是否被物理删除，新事实是否写入。
2. 验证艾宾浩斯时间遗忘衰减与驱逐机制。
   模拟时间向前推移，验证当权重计算衰减到 0.2 以下时，记忆节点是否被彻底淘汰驱逐。
"""

import time
import asyncio
from aether_mind.storage.sqlite import SQLiteStore
from aether_mind.storage.qdrant import QdrantVectorStore
from aether_mind.utils.client import AetherMindLLMClient
from aether_mind.memory.consolidator import MemoryConsolidator


async def run_consolidation_test():
    """
    运行冲突消歧与时间衰减测试。
    """
    print("\n[开始测试] 长期记忆冲突消歧与遗忘衰减...")
    
    # 1. 初始化本地临时测试存储（SQLite 内存模式暂不支持异步跨连接，因此使用 test_temp.db 文件，测试完清理）
    db = SQLiteStore("test_temp.db")
    await db.init_db()
    
    # Qdrant 内存模式
    vector_store = QdrantVectorStore()
    await vector_store.init_collections()
    
    client = AetherMindLLMClient()
    # 衰减率设为 1.0（每秒衰减 1.0 权重），以便于快速测试
    consolidator = MemoryConsolidator(client, decay_rate=1.0)
    
    user_id = "usr_test_con"
    
    # === 第一部分：时序冲突消歧验证 ===
    # 3.1 写入初始偏好 Facts
    print("步骤 1. 写入初始用户偏好: '用户偏好使用 smolagents 框架开发'")
    await consolidator.consolidate_fact(
        user_id=user_id,
        new_fact_key="user_framework_preference",
        new_fact_value="用户偏好使用 smolagents 框架开发",
        db=db,
        vector_store=vector_store
    )
    
    # 验证写入成功
    dummy_vec = [0.0] * 1536
    initial_hits = await vector_store.search_points("memory_collection", dummy_vec, {"user_id": user_id})
    assert len(initial_hits) == 1, "初始 Facts 写入失败"
    print(f"-> 初始事实成功载入，Payload: {initial_hits[0]['payload']['fact']}")

    # 3.2 写入强冲突偏好 Facts
    print("步骤 2. 写入对立冲突偏好: '用户放弃了 smolagents 开发，转投 Letta 阵营并极其讨厌 smolagents'")
    await consolidator.consolidate_fact(
        user_id=user_id,
        new_fact_key="user_framework_preference",
        new_fact_value="用户放弃了 smolagents 开发，转投 Letta 阵营并极其讨厌 smolagents",
        db=db,
        vector_store=vector_store
    )

    # 3.3 验证冲突消歧：只保留 Letta 事实，旧的 smolagents 事实已被删除
    post_hits = await vector_store.search_points("memory_collection", dummy_vec, {"user_id": user_id})
    print(f"-> 消歧后召回事实数量: {len(post_hits)}")
    for h in post_hits:
        print(f"   召回 Payload Fact: {h['payload']['fact']}")
        
    assert len(post_hits) == 1, "时序消歧失败：未能合理合并/覆盖冲突节点。"
    assert "letta" in post_hits[0]["payload"]["fact"].lower(), "旧事实未被覆盖淘汰"
    print("-> ✓ 冲突消歧判定测试成功！")

    # === 第二部分：时间遗忘衰减淘汰验证 ===
    print("\n步骤 3. 开始测试艾宾浩斯时间衰减机制...")
    # 获取当前时间
    now = time.time()
    
    # 模拟在 3 秒后执行遗忘折损
    # W = 1.0 * exp(-1.0 * 3) = exp(-3) = 0.049 < 0.2 -> 应被剔除
    print("-> 模拟时间流逝 3 秒...")
    future_time = now + 3.0
    await consolidator.apply_ebbinghaus_decay(user_id, db, vector_store, current_time=future_time)
    
    # 验证是否已被物理清除
    decay_hits = await vector_store.search_points("memory_collection", dummy_vec, {"user_id": user_id})
    print(f"-> 遗忘衰减后召回事实数量: {len(decay_hits)}")
    assert len(decay_hits) == 0, "时间衰减驱逐淘汰机制失败：过期节点依然残留。"
    print("-> ✓ 艾宾浩斯遗忘衰减驱逐测试成功！")

    # 4. 清理测试文件
    import os
    if os.path.exists("test_temp.db"):
        os.remove("test_temp.db")
    print("[测试完成] 记忆消歧与衰减测试 100% 通过。\n")


def test_consolidation_and_decay():
    """
    Pytest 接口。
    """
    asyncio.run(run_consolidation_test())


if __name__ == "__main__":
    asyncio.run(run_consolidation_test())
