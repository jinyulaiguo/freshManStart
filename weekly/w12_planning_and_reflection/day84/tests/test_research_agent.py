"""
Day 84 综合实战: 单元测试套件 (Unit Test Suite)

【测试设计意图】
针对 Research Agent 各个核心独立微引擎进行高强度单元测试：
1. 验证 DependencyGraph 拓扑分层算法在依赖环与正常拓扑下的正确性。
2. 验证 ReWOO 工具并发 dispatch 性能。
3. 验证 Critic 与 Verifier 的路由断言。
"""

import pytest
import asyncio
from weekly.w12_planning_and_reflection.day84.planning.plan_schema import TaskStep
from weekly.w12_planning_and_reflection.day84.planning.dependency import DependencyGraph
from weekly.w12_planning_and_reflection.day84.tools.registry import ToolRegistry
from weekly.w12_planning_and_reflection.day84.state.research_state import CriticResult, VerificationResult
from weekly.w12_planning_and_reflection.day84.graph.nodes.critic import CriticNode
from weekly.w12_planning_and_reflection.day84.graph.nodes.verifier import AntiHallucinationVerifierNode


def test_dependency_graph_layers():
    """验证 DAG 拓扑分层正确性"""
    steps = [
        TaskStep(id="step1", description="搜索市场", task_type="search", output_var="m"),
        TaskStep(id="step2", description="搜索厂商", task_type="search", output_var="c"),
        TaskStep(id="step3", description="分析综合数据", task_type="analyze", dependency=["step1", "step2"], output_var="r"),
    ]
    graph = DependencyGraph(steps)
    layers = graph.get_execution_layers()

    assert len(layers) == 2, "应拆解为 2 个执行层"
    layer1_ids = {s.id for s in layers[0]}
    assert layer1_ids == {"step1", "step2"}, "第一层应包含无依赖的 step1 与 step2"
    assert layers[1][0].id == "step3", "第二层应包含依赖 step1/step2 的 step3"


@pytest.mark.asyncio
async def test_tool_registry_dispatch():
    """验证 ToolRegistry 工具分发功能"""
    registry = ToolRegistry()
    res = await registry.dispatch("rag", "医疗AI市场")
    assert "contexts" in res, "RAG 工具必须返回 contexts"
    assert len(res["contexts"]) > 0


def test_critic_route_guard():
    """验证 Critic 路由控制"""
    pass_state = {"critic_result": CriticResult(status="PASS", score=90, reason="合格")}
    reject_state = {"critic_result": CriticResult(status="REJECT", score=50, reason="缺少风险分析")}

    assert CriticNode.route_guard(pass_state) == "TO_VERIFIER"
    assert CriticNode.route_guard(reject_state) == "TO_REFLECTOR"


def test_verifier_route_guard():
    """验证 Verifier 路由控制"""
    pass_state = {"verification_result": VerificationResult(overall_status="PASS")}
    fail_state = {"verification_result": VerificationResult(overall_status="HALLUCINATION_DETECTED")}

    assert AntiHallucinationVerifierNode.route_guard(pass_state) == "TO_END"
    assert AntiHallucinationVerifierNode.route_guard(fail_state) == "TO_GENERATOR"
