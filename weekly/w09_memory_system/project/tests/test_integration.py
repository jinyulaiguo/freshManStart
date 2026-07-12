"""
Integration and Multi-Tenant Isolation Test Module.

设计方案说明：
1. **设计意图**：
   本测试套件执行多租户物理隔离与多层级记忆全链路集成的综合功能测试。
2. **测试流程**：
   - 步骤 1: 租户 A (user_leeming) 交互声明：“我叫李明，我主要用 Python 语言。”
   - 步骤 2: 租户 B (user_zhangsan) 交互声明：“我叫张三，我只用 Go 语言。”
   - 步骤 3: 异步睡眠等待，确保后台非阻塞事实提取与消岐任务完成。
   - 步骤 4: 跨租户安全检索验证。张三提问“我最喜欢的语言是什么”，核对大模型是否只能看到张三自己的偏好，绝不泄漏李明的数据。
   - 步骤 5: 意图分流与外部 RAG 综合测试。提问客观知识“微软 GraphRAG 框架机制是什么”，验证路由为 RAG，且上下文包含召回的 RAG 知识并正确生成回复。
"""

import sys
import os
import asyncio
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
async def test_integration_and_isolation():
    """测试多租户物理隔离及自适应 RAG 检索全链路功能。"""
    test_db = "temp_test_integration.db"
    
    # 清理垃圾
    if os.path.exists(test_db):
        os.remove(test_db)
        
    engine = MemoryAgentEngine(db_path=test_db, token_limit=1000)
    
    try:
        # ==========================================
        # 1. 租户 A (user_leeming) 对话与偏好沉淀
        # ==========================================
        session_a = "session_leeming_111"
        user_a = "user_leeming"
        
        print("\n\n=== [集成测试] 租户 A 发送交互消息 ===")
        res_a1 = await engine.handle_message(
            session_id=session_a,
            user_id=user_a,
            query="你好，我叫李明。我是一名 Python 开发者，极其喜欢 Python，讨厌 Java。"
        )
        print(f"Assistant A1: \"{res_a1['reply']}\"")
        
        # ==========================================
        # 2. 租户 B (user_zhangsan) 对话与偏好沉淀
        # ==========================================
        session_b = "session_zhangsan_222"
        user_b = "user_zhangsan"
        
        print("\n=== [集成测试] 租户 B 发送交互消息 ===")
        res_b1 = await engine.handle_message(
            session_id=session_b,
            user_id=user_b,
            query="你好，我是张三。我目前只使用 Go 语言写后端，我讨厌 Python。"
        )
        print(f"Assistant B1: \"{res_b1['reply']}\"")
        
        # ==========================================
        # 3. 等待后台非阻塞异步 Facts 提取与冲突判定任务执行结束
        # ==========================================
        print("\n⏳ 正在睡眠 6 秒以等待后台非阻塞 Facts 提取与消歧写入数据库...")
        await asyncio.sleep(6.0)
        
        # 检查数据库是否写入成功
        memories_a = await engine.store.load_user_memories(user_a)
        memories_b = await engine.store.load_user_memories(user_b)
        
        print(f"数据库中李明的 Facts: {memories_a}")
        print(f"数据库中张三的 Facts: {memories_b}")
        
        # ==========================================
        # 4. 多租户物理隔离安全检索验证 (由大模型回答进行二重确认)
        # ==========================================
        print("\n=== [集成测试] 验证多租户数据泄露隔离 ===")
        
        # 让张三提问，看他是否能得知自己喜欢的语言，且不被李明喜欢 Python 干扰
        res_b2 = await engine.handle_message(
            session_id=session_b,
            user_id=user_b,
            query="我叫什么？我比较喜欢写什么编程语言来着？"
        )
        print(f"张三提问路由决策: {res_b2['route']} | Rtt: {res_b2['rtt_ms']}ms")
        print(f"召回的背景偏好 payload: {res_b2['payload']}")
        print(f"Assistant 对张三的回答: \"{res_b2['reply']}\"")
        
        # 验证大模型对张三的回复里包含 Go，绝不包含 Python，也没提及李明
        assert "Go" in res_b2['reply'] or "go" in res_b2['reply'].lower(), "张三的回复应当指明是 Go 语言"
        assert "Python" not in res_b2['reply'], "张三的回复绝对不能泄露李明的 Python 偏好！"
        
        # ==========================================
        # 5. 意图分流路由为 RAG 且检索成功合并验证
        # ==========================================
        print("\n=== [集成测试] 验证自适应 RAG 客观文档检索 ===")
        res_a2 = await engine.handle_message(
            session_id=session_a,
            user_id=user_a,
            query="请问微软 GraphRAG 框架的核心检索机制是什么？"
        )
        print(f"李明提问 RAG 路由决策: {res_a2['route']} | Rtt: {res_a2['rtt_ms']}ms")
        print(f"RAG 召回的知识 payload: {res_a2['payload']}")
        print(f"Assistant 回答: \"{res_a2['reply']}\"")
        
        assert res_a2['route'] == "RAG", "客观提问路由应当预测为 RAG"
        assert any("MemGPT" in doc or "Letta" in doc or "GraphRAG" in doc for doc in res_a2['payload']), "应该检索到客观技术文档"
        
        print("\n多租户物理隔离与自适应 RAG 全链路集成测试: ✅ 成功通过")
        
    finally:
        # 清理
        if os.path.exists(test_db):
            os.remove(test_db)
            print("[测试] 临时测试数据库已清理。")
