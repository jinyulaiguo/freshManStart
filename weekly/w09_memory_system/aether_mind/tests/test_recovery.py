"""
AetherMind Session Recovery Test
================================

设计意图:
---------
验证系统的冷启动状态恢复能力（断电无缝恢复）。
模拟写入部分历史消息和背景摘要，然后强行断开并重启数据库连接，
验证重启后的新连接能够 100% 反序列化并复原会话上下文与摘要。
"""

import os
import asyncio
from aether_mind.storage.sqlite import SQLiteStore


async def run_recovery_test():
    """
    运行断电会话状态重构与恢复测试。
    """
    print("\n[开始测试] 会话断电冷启动恢复一致性...")
    db_file = "test_recovery.db"
    
    # 确保没有残留测试文件
    if os.path.exists(db_file):
        os.remove(db_file)

    # 1. 建立初始连接并写入状态
    db_inst1 = SQLiteStore(db_file)
    await db_inst1.init_db()
    
    session_id = "sess_rec_992"
    user_id = "usr_rec_12"
    
    print("步骤 1. 初始化会话与插入多轮交互消息")
    await db_inst1.create_session(session_id, user_id)
    await db_inst1.save_message(session_id, "user", "我想了解 smolagents")
    await db_inst1.save_message(session_id, "assistant", "smolagents 是 Hugging Face 推出的一款轻量级 Agent 框架")
    await db_inst1.save_message(session_id, "user", "那它怎么做代码沙箱？")
    
    # 模拟后台摘要归约产生
    test_summary = "用户正在调研 smolagents 框架并特别关注其代码沙箱机制。"
    await db_inst1.update_session_summary(session_id, test_summary)
    
    # 2. 模拟突发断电：物理销毁/关闭第一个数据库连接
    print("步骤 2. 模拟系统崩溃断电（物理丢弃连接实例）...")
    del db_inst1

    # 3. 系统冷启动：建立全新连接并载入数据
    print("步骤 3. 系统冷启动重启，重新建立数据库连接...")
    db_inst2 = SQLiteStore(db_file)
    await db_inst2.init_db()

    # 重构恢复检查
    recovered_user = await db_inst2.get_session_user(session_id)
    recovered_summary = await db_inst2.get_session_summary(session_id)
    recovered_messages = await db_inst2.load_session_context(session_id)

    print(f"-> 恢复的关联租户: {recovered_user} (预期: {user_id})")
    print(f"-> 恢复的会话摘要: '{recovered_summary}'")
    print(f"-> 恢复的对话轮数: {len(recovered_messages)} 轮 (预期: 3)")

    # 断言强一致性校验
    assert recovered_user == user_id, "恢复的用户 ID 不匹配"
    assert recovered_summary == test_summary, "恢复的摘要内容不匹配"
    assert len(recovered_messages) == 3, "恢复的对话消息数量不一致"
    assert recovered_messages[0]["content"] == "我想了解 smolagents", "消息内容顺序或语义错乱"
    
    print("-> ✓ 会话冷启动无缝状态重构测试成功！")

    # 4. 清理物理文件
    del db_inst2
    if os.path.exists(db_file):
        os.remove(db_file)
    print("[测试完成] 会话断电恢复一致性测试 100% 通过。\n")


def test_recovery_consistency():
    """
    Pytest 接口。
    """
    asyncio.run(run_recovery_test())


if __name__ == "__main__":
    asyncio.run(run_recovery_test())
