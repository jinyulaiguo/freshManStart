"""
Day 84 综合实战: Research Agent 完整 LangGraph 图编排组装

【架构拓扑说明】
1. PlannerNode ➔ PlanValidatorNode
2. PlanValidatorNode ➔ (合法) ➔ ReWOOExecutorNode
                       ➔ (熔断/错误) ➔ END
3. ReWOOExecutorNode ➔ ObservationCollectorNode ➔ ContextBuilderNode ➔ ReportGeneratorNode
4. ReportGeneratorNode ➔ CriticNode
5. CriticNode ➔ (PASS) ➔ AntiHallucinationVerifierNode
              ➔ (REJECT) ➔ ReflectorNode ➔ ReplannerNode ➔ ReWOOExecutorNode
6. AntiHallucinationVerifierNode ➔ (PASS) ➔ END (输出 Final Report)
                                 ➔ (HALLUCINATION) ➔ ReportGeneratorNode (带纠偏指令重新生成)
"""

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from weekly.w12_planning_and_reflection.day84.state.research_state import ResearchState
from weekly.w12_planning_and_reflection.day84.graph.nodes.planner import PlannerNode
from weekly.w12_planning_and_reflection.day84.graph.nodes.plan_validator import PlanValidatorNode
from weekly.w12_planning_and_reflection.day84.graph.nodes.executor import ReWOOExecutorNode
from weekly.w12_planning_and_reflection.day84.graph.nodes.observation_collector import ObservationCollectorNode
from weekly.w12_planning_and_reflection.day84.graph.nodes.context_builder import ContextBuilderNode
from weekly.w12_planning_and_reflection.day84.graph.nodes.generator import ReportGeneratorNode
from weekly.w12_planning_and_reflection.day84.graph.nodes.critic import CriticNode
from weekly.w12_planning_and_reflection.day84.graph.nodes.reflector import ReflectorNode
from weekly.w12_planning_and_reflection.day84.graph.nodes.replanner import ReplannerNode
from weekly.w12_planning_and_reflection.day84.graph.nodes.verifier import AntiHallucinationVerifierNode


def build_research_graph():
    """
    组装并编译生产级 Research Agent 拓扑图
    """
    builder = StateGraph(ResearchState)

    # 1. 实例化所有微引擎节点
    planner = PlannerNode()
    plan_validator = PlanValidatorNode()
    executor = ReWOOExecutorNode()
    obs_collector = ObservationCollectorNode()
    context_builder = ContextBuilderNode()
    generator = ReportGeneratorNode()
    critic = CriticNode()
    reflector = ReflectorNode()
    replanner = ReplannerNode()
    verifier = AntiHallucinationVerifierNode()

    # 2. 注册节点到图
    builder.add_node("planner", planner)
    builder.add_node("plan_validator", plan_validator)
    builder.add_node("executor", executor)
    builder.add_node("obs_collector", obs_collector)
    builder.add_node("context_builder", context_builder)
    builder.add_node("generator", generator)
    builder.add_node("critic", critic)
    builder.add_node("reflector", reflector)
    builder.add_node("replanner", replanner)
    builder.add_node("verifier", verifier)

    # 3. 构建控制流边 (Edges)
    builder.add_edge(START, "planner")
    builder.add_edge("planner", "plan_validator")

    # 条件边 1: PlanValidator 路由
    builder.add_conditional_edges(
        "plan_validator",
        PlanValidatorNode.route_guard,
        {
            "TO_EXECUTOR": "executor",
            "TO_FALLBACK": END
        }
    )

    builder.add_edge("executor", "obs_collector")
    builder.add_edge("obs_collector", "context_builder")
    builder.add_edge("context_builder", "generator")
    builder.add_edge("generator", "critic")

    # 条件边 2: Critic 审查路由
    builder.add_conditional_edges(
        "critic",
        CriticNode.route_guard,
        {
            "TO_VERIFIER": "verifier",
            "TO_REFLECTOR": "reflector"
        }
    )

    builder.add_edge("reflector", "replanner")
    builder.add_edge("replanner", "executor")

    # 条件边 3: Verifier NLI 校验路由
    builder.add_conditional_edges(
        "verifier",
        AntiHallucinationVerifierNode.route_guard,
        {
            "TO_END": END,
            "TO_GENERATOR": "context_builder"  # 回退组装含纠偏指令的 Context 并修补生成
        }
    )

    # 4. 绑定 Checkpointer 编译图
    checkpointer = MemorySaver()
    compiled_graph = builder.compile(checkpointer=checkpointer)
    return compiled_graph
