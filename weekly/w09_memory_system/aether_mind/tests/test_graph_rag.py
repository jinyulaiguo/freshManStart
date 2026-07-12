"""
AetherMind GraphRAG Engine Test
===============================

设计意图:
---------
验证 GraphRAG 图检索引擎的正确性。
1. 测试实体关系提取与 NetworkX 有向图织入。
2. 测试 Louvain 社区发现算法与社区报告生成。
3. 测试 Local Search（局部子图一跳邻域检索）与 Global Search（全局 Map-Reduce 报告综述聚合）。
基于真实大模型推理调用。
"""

import asyncio
from aether_mind.utils.client import AetherMindLLMClient
from aether_mind.rag.graph_search import GraphRAGEngine


async def run_graph_rag_test():
    """
    运行 GraphRAG 核心检索提取测试。
    """
    print("\n[开始测试] GraphRAG 图抽取与 Local/Global 检索...")
    
    client = AetherMindLLMClient()
    graph_engine = GraphRAGEngine(client)

    # 1. 模拟注入两段包含关联架构的 Chunk 文本
    chunk_1 = (
        "LangGraph is a framework for building stateful multi-agent applications. "
        "It compiles the execution flow into a StateGraph containing Nodes and Edges. "
        "The Node function executes on host process. It is developed by langchain-ai."
    )
    chunk_2 = (
        "smolagents is a lightweight agent framework developed by Hugging Face. "
        "It utilizes CodeAgent which executes LLM-generated Python code in a "
        "RestrictedPythonExecutor sandbox for maximum security."
    )

    print("步骤 1. 图谱实体关系抽取与 NetworkX 织入...")
    await graph_engine.extract_and_build_graph(1, chunk_1)
    await graph_engine.extract_and_build_graph(2, chunk_2)

    # 验证节点和边数
    nodes = list(graph_engine.graph.nodes)
    edges = list(graph_engine.graph.edges)
    print(f"-> 抽取图谱节点列表: {nodes}")
    print(f"-> 抽取图谱连接边数: {len(edges)}")
    
    assert len(nodes) >= 2, "未能成功提取出实体节点"

    # 2. 社区分类报告生成
    print("\n步骤 2. 运行 Louvain 算法对图谱划分网络社区并生成报告...")
    await graph_engine.build_communities()
    print(f"-> 生成的社区报告数量: {len(graph_engine.community_reports)}")
    for r in graph_engine.community_reports:
        print(f"   社区标题: {r['title']}, 包含实体: {r['entities']}, 权重: {r['importance']}")

    assert len(graph_engine.community_reports) >= 1, "社区划分与报告构建失败"

    # 3. 局部检索测试 (Local Search)
    print("\n步骤 3. 测试 Local Search 邻域图检索...")
    # 查询 smolagents 的安全机制
    local_res = await graph_engine.local_search("Tell me about smolagents security and sandbox")
    print(f"-> Local Search 返回长度: {len(local_res)} 字符")
    print(local_res)
    
    # 局部检索应该找到有关 smolagents 或 RestrictedPythonExecutor 的线索
    assert len(local_res) > 0, "局部子图检索未返回任何内容"
    assert "smolagents" in local_res.lower() or "restrictedpythonexecutor" in local_res.lower(), "局部子图匹配关联性过弱"

    # 4. 全局检索测试 (Global Search)
    print("\n步骤 4. 测试 Global Search 社区 Map-Reduce 宏观聚合检索...")
    global_res = await graph_engine.global_search("Compare the execution environment and sandbox design between LangGraph and smolagents")
    print(f"-> Global Search 返回长度: {len(global_res)} 字符")
    print(global_res)
    
    assert len(global_res) > 0, "全局 Map-Reduce 检索未返回任何内容"
    print("-> ✓ GraphRAG 图分析与多跳推理检索测试成功！")
    print("[测试完成] GraphRAG 测试 100% 通过。\n")


def test_graph_rag_pipeline():
    """
    Pytest 接口。
    """
    asyncio.run(run_graph_rag_test())


if __name__ == "__main__":
    asyncio.run(run_graph_rag_test())

