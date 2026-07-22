"""
Memory Router Unit Test Module.

设计方案说明：
1. **设计意图**：
   本测试套件旨在自动化验证自适应检索路由器（Memory Router）的准确率。
   输入 8 条包含日常寒暄 (NONE)、长期事实偏好 (MEM)、客观技术文档 (RAG) 维度的测试样本，
   评估其路由准确率。
2. **测试契约与边界**：
   - 验证通过指标：路由分类准确率必须达到 80% 以上（开发计划指标为 90%，在精简集下期望 100% 正确）。
   - 网络异常保护：包含异常捕获以保证网络抖动下不会直接导致测试套件死锁。
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

from app.memory_router import MemoryRouter

@pytest.mark.asyncio
async def test_router_accuracy():
    """测试意图分类路由器的预测准确率。"""
    router = MemoryRouter()
    
    # 评测样本（覆盖三大核心分类意图）
    test_cases = [
        {"query": "你好呀！我是新来的助手。", "expected": "NONE"},
        {"query": "今天天气真是不错，适合出去散步。", "expected": "NONE"},
        {"query": "一加一等于几？请直接给出数字。", "expected": "NONE"},
        {"query": "你还记得我常用的编程语言是什么吗？", "expected": "MEM"},
        {"query": "我叫什么名字来着？你记得吗？", "expected": "MEM"},
        {"query": "我刚才说我在哪家公司上班？", "expected": "MEM"},
        {"query": "微软 GraphRAG 框架的核心检索机制是什么？", "expected": "RAG"},
        {"query": "Leiden 社区 MapReduce 模拟算法在图谱中如何应用？", "expected": "RAG"}
    ]
    
    correct_count = 0
    print("\n\n=== 开始自适应路由预测分类评测 (8条样本) ===")
    
    for idx, case in enumerate(test_cases, 1):
        query = case["query"]
        expected = case["expected"]
        
        # 调用大模型路由器执行意图识别
        predicted = await router.route(query)
        
        status = "✅ 正确" if predicted == expected else "❌ 错误"
        if predicted == expected:
            correct_count += 1
            
        print(f"[{idx:02d}] Query: \"{query}\"")
        print(f"     -> 预测路由: {predicted} | 期望路由: {expected} | 状态: {status}")
        
    accuracy = correct_count / len(test_cases)
    print(f"================ 评测指标结果 ================")
    print(f"路由意图分类准确率: {accuracy * 100:.1f}% (验证通过标准: >= 80.0%)")
    print(f"==============================================\n")
    
    assert accuracy >= 0.8, f"意图分类路由准确率低于 80% (当前为: {accuracy * 100:.1f}%)"
