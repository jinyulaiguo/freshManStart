"""
AetherMind Multi-Tenant & Integration Test
=========================================

设计意图:
---------
验证系统全链路组装的正确性，并重点检查多租户事实隔离机制（Tenant Isolation）。
1. 租户 Alpha 声明其特有的技术偏好并生成记忆。
2. 租户 Beta 在相同会话或独立会话提问其个人偏好，验证 Alpha 的偏好绝不发生越权跨租户泄露。
3. 租户 Alpha 再次询问其偏好，验证长期记忆可被安全召回并指导生成。
"""

import os
import asyncio
from aether_mind.storage.sqlite import SQLiteStore
from aether_mind.storage.qdrant import QdrantVectorStore
from aether_mind.core.engine import MemoryAgentEngine


async def run_integration_test():
    """
    运行全链路多租户隔离与集成匹配测试。
    """
    print("\n[开始测试] 全链路多租户隔离与集成推理...")
    db_file = "test_integration.db"
    
    # 确保无残留
    if os.path.exists(db_file):
        os.remove(db_file)

    # 1. 初始化 SQLite 与 Qdrant 存储后端
    db = SQLiteStore(db_file)
    vector_store = QdrantVectorStore()
    
    # 2. 组装 Master 引擎
    engine = MemoryAgentEngine(db, vector_store)
    await engine.initialize()

    # 租户人设数据
    user_alpha = "usr_alpha_99"
    sess_alpha = "sess_alpha_99"
    
    user_beta = "usr_beta_88"
    sess_beta = "sess_beta_88"

    # ==========================================
    # 步骤 1: 租户 Alpha 建立个人偏好事实
    # ==========================================
    print("\n步骤 1. 租户 Alpha 声明偏好: '我平时极其偏好用 smolagents 进行开发'")
    alpha_stream_1 = engine.handle_message_stream(
        session_id=sess_alpha,
        user_id=user_alpha,
        query="我平时极其偏好用 smolagents 进行开发"
    )
    
    # 消费流以触发后台事实提取
    alpha_reply_1 = []
    async for event in alpha_stream_1:
        if event["type"] == "token":
            alpha_reply_1.append(event["content"])
            
    print(f"-> 助理回复 Alpha: {''.join(alpha_reply_1)}")
    print("-> 等待后台事实提取与消歧消解执行完成...")
    await asyncio.sleep(4.0)  # 给予后台异步 create_task 任务足够的执行时间

    # ==========================================
    # 步骤 2: 租户 Beta 询问其偏好，测试多租户隔离
    # ==========================================
    print("\n步骤 2. 租户 Beta 提问: '我偏好用什么框架？'")
    beta_stream = engine.handle_message_stream(
        session_id=sess_beta,
        user_id=user_beta,
        query="我偏好用什么框架？"
    )
    
    beta_reply = []
    async for event in beta_stream:
        if event["type"] == "token":
            beta_reply.append(event["content"])
            
    beta_reply_text = "".join(beta_reply)
    print(f"-> 助理回复 Beta: {beta_reply_text}")
    
    # 校验安全隔离性：Beta 的回复绝对不应该含有 Alpha 的特有词汇 "smolagents"
    assert "smolagents" not in beta_reply_text.lower(), "多租户越权漏洞：Beta 检索读取到了 Alpha 的长期事实记忆！"
    print("-> ✓ 多租户隔离防护性测试成功！")

    # ==========================================
    # 步骤 3: 租户 Alpha 再次提问，验证记忆召回
    # ==========================================
    print("\n步骤 3. 租户 Alpha 再次提问: '你知道我一般喜欢用什么框架吗？'")
    alpha_stream_2 = engine.handle_message_stream(
        session_id=sess_alpha,
        user_id=user_alpha,
        query="你知道我一般喜欢用什么框架吗？"
    )
    
    alpha_reply_2 = []
    async for event in alpha_stream_2:
        if event["type"] == "token":
            alpha_reply_2.append(event["content"])
            
    alpha_reply_text_2 = "".join(alpha_reply_2)
    print(f"-> 助理回复 Alpha: {alpha_reply_text_2}")
    
    # 校验记忆召回：Alpha 的回复必须成功召回先前的偏好事实，含有 "smolagents" 框架信息
    assert "smolagents" in alpha_reply_text_2.lower(), "长期记忆召回失败：Alpha 的第二轮问答未能结合已有的长期偏好事实。"
    print("-> ✓ 长期记忆事实召回一致性测试成功！")

    # 4. 清理物理表连接
    # SQLite 不需要特别释放，物理删除文件即可
    if os.path.exists(db_file):
        os.remove(db_file)
    print("[测试完成] 生产级多租户隔离与集成联调测试 100% 通过。\n")


def test_tenant_isolation_integration():
    """
    Pytest 接口。
    """
    asyncio.run(run_integration_test())


if __name__ == "__main__":
    asyncio.run(run_integration_test())
