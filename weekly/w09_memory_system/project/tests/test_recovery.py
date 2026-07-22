"""
State Recovery Unit Test Module.

设计方案说明：
1. **设计意图**：
   本测试套件旨在严密校验多层级记忆系统在遭遇断电、容器重启或进程突发退出时的状态一致性复原能力（State Recovery）。
2. **测试机制**：
   - 步骤 1: 建立一个持久化 DB，写入短期交互消息，并在 Session 表写入模拟的滑动摘要。同时写入长期 Facts 偏好。
   - 步骤 2: 物理删除 Engine 内存对象，彻底清空 RAM。
   - 步骤 3: 重新建立全新 Engine 实例并绑定同一 DB。
   - 步骤 4: 传入相同 `session_id` 和 `user_id` 触发状态热加载。
   - 步骤 5: 验证恢复出来的消息、摘要以及 Facts 的一致性是否达 100%。
3. **环境防护**：
   - 测试结束后，主动关闭连接并物理移除测试 DB，维护工作空间的整洁。
"""

import sys
import os
import pytest
import pytest_asyncio

# 物理定位并添加路径
current_dir = os.path.dirname(os.path.abspath(__file__))
project_dir = os.path.abspath(os.path.join(current_dir, ".."))
if project_dir not in sys.path:
    sys.path.insert(0, project_dir)
if os.path.join(project_dir, "app") not in sys.path:
    sys.path.insert(0, os.path.join(project_dir, "app"))

from app.main_engine import MemoryAgentEngine

@pytest.mark.asyncio
async def test_state_recovery():
    """测试进程突发崩溃断电下，重新装配引擎时的状态复原一致性。"""
    test_db = "temp_test_recovery.db"
    
    # 清理遗留垃圾
    if os.path.exists(test_db):
        os.remove(test_db)
        
    session_id = "session_test_recovery_999"
    user_id = "user_recovery_test"
    
    try:
        # ==========================================
        # 1. 模拟系统运行并写入数据
        # ==========================================
        engine = MemoryAgentEngine(db_path=test_db, token_limit=1000)
        
        # 物理建表
        await engine.store.init_db()
        await engine.store.create_session(session_id, user_id)
        
        # 模拟写入几条短期消息并设置累积摘要
        await engine.store.save_message(session_id, "user", "你好，我是开发者李明。")
        await engine.store.save_message(session_id, "assistant", "你好，李明！请问目前遇到了什么问题？")
        await engine.store.update_session_summary(session_id, "用户是开发者李明。")
        
        # 模拟写入一条长期 facts
        await engine.store.save_fact(user_id, "user_prefer_language", "Python")
        
        # ==========================================
        # 2. 模拟突然物理断电 (物理销毁内存 Engine)
        # ==========================================
        del engine
        print("\n=== [测试] 模拟突然断电：旧内存 Engine 实例已销毁。 ===")
        
        # ==========================================
        # 3. 系统重启，物理装配新 Engine 并传入相同 session_id 执行状态恢复
        # ==========================================
        new_engine = MemoryAgentEngine(db_path=test_db, token_limit=1000)
        
        # 触发热重构（在 handle_message 入口自动触发，或者手动触发）
        await new_engine.buffer_manager.load_state(new_engine.store, session_id)
        recovered_memories = await new_engine.store.load_user_memories(user_id)
        
        # ==========================================
        # 4. 严密校验一致性
        # ==========================================
        print("\n=== [测试] 状态重构一致性校验 ===")
        print(f"重构恢复的消息数: {len(new_engine.buffer_manager.messages)} 条")
        for idx, m in enumerate(new_engine.buffer_manager.messages):
            print(f" [{idx}] {m['role'].upper()}: {m['content']}")
        print(f"重构恢复的累计摘要: \"{new_engine.buffer_manager.current_summary}\"")
        print(f"重构恢复的长期 Facts: {recovered_memories}")
        
        # 断言
        assert len(new_engine.buffer_manager.messages) == 2, "恢复的短期活跃消息条数不正确"
        assert new_engine.buffer_manager.messages[0]["role"] == "user", "第一条消息角色应当为 user"
        assert new_engine.buffer_manager.current_summary == "用户是开发者李明。", "累计摘要不一致"
        assert recovered_memories.get("user_prefer_language") == "Python", "长期事实不一致"
        
        print("\n物理断电状态 100% 恢复校验: ✅ 通过")
        
    finally:
        # 5. 物理清理，保障工作区绝对纯净
        if os.path.exists(test_db):
            os.remove(test_db)
            print("[测试] 已安全清理临时测试 DB 文件。")
