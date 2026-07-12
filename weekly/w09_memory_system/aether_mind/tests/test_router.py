"""
AetherMind Router Unit Test
===========================

设计意图:
---------
验证 `MemoryRouter` 意图分流路由器的分类准确率。
输入闲聊、个人偏好和技术框架客观问题的测试样本，验证分发决策的正确性。
根据真实 API 规范，不使用 Mock，调用真实 MiniMax 接口测试。
"""

import asyncio
from aether_mind.utils.client import AetherMindLLMClient
from aether_mind.core.router import MemoryRouter


async def run_router_test():
    """
    运行路由器分类测试，直观打印输出（符合 Rule 6 规范）。
    """
    print("\n[开始测试] Router 意图分流...")
    client = AetherMindLLMClient()
    router = MemoryRouter(client)

    # 测试样本集 (Query -> 预期路由标签列表)
    test_cases = [
        ("你好，今天天气不错", ["NONE"]),
        ("你知道我的开发习惯吗，我常用什么语言？", ["MEM", "MEM+RAG"]),
        ("smolagents 的 ast 受限沙箱是怎么工作的？", ["RAG", "MEM+RAG"]),
        ("帮我比较下 smolagents 与 Letta 的多租户设计并重构一个设计", ["PLAN"])
    ]

    correct = 0
    for query, expected_routes in test_cases:
        route = await router.route(query)
        is_correct = route in expected_routes
        if is_correct:
            correct += 1
        print(f"Query: '{query}' -> 路由判定: {route} (预期: {expected_routes}) -> {'✓' if is_correct else '✗'}")

    accuracy = (correct / len(test_cases)) * 100
    print(f"[测试完成] 路由器分类准确度: {accuracy:.1f}%\n")
    assert accuracy >= 75.0, f"Router 准确度过低: {accuracy}%"


def test_intent_router():
    """
    Pytest 接口。
    """
    asyncio.run(run_router_test())


if __name__ == "__main__":
    # 支持直接 python test_router.py 运行（符合 Rule 6）
    asyncio.run(run_router_test())
