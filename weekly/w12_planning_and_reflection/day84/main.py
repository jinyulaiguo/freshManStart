"""
Day 84 综合实战主入口: Advanced Industry Research Agent

【系统设计方案说明】
1. 设计意图 (Design Intent):
   作为零逻辑主入口 (Zero-Logic Entrypoint)，遵守 AGENTS.md 规范 10。
   仅负责串联组装好的 LangGraph 拓扑图、控制台 REPL 交互调度与生命周期管理，
   驱动带任务解耦 (Plan-and-Execute)、ReWOO 并行、LLM-as-Critic 审查、Reflexion 反思与 NLI 防幻觉校验的行业研报 Agent。

2. 核心用例验证意图 (Test Case Design Intent):
   验证课题: "分析2026年医疗AI行业发展趋势，重点关注：1. 市场规模 2. 技术路线 3. 主要厂商 4. 投资机会 5. 风险因素"
   验证点 1: 验证 Planner 正确生成多阶段 TaskStep 拓扑图。
   验证点 2: 验证 ReWOOExecutorNode 使用 asyncio.gather 并发分发 Qdrant RAG 与 Web 搜索工具。
   验证点 3: 验证 Critic 审查草稿完整性，并触发 Reflexion 归纳指导规则。
   验证点 4: 验证 AntiHallucinationVerifierNode 逐句 NLI 校验，剔除凭空捏造与矛盾断言，输出 100% 可信研报。
"""

import sys
import os
import asyncio

# 将项目根目录添加到 sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../")))

from weekly.w04_prompt_and_http.utils import load_env_file
from weekly.w12_planning_and_reflection.day84.graph.research_graph import build_research_graph
from weekly.w12_planning_and_reflection.day84.evaluation.research_logger import ResearchLogger

load_env_file()


async def run_research_pipeline(user_query: str):
    """
    驱动端到端 Research Agent Pipeline
    """
    print("=" * 80)
    print("🚀 Advanced Industry Research Agent Engine Launching...")
    print(f"📋 课题任务: {user_query}")
    print("=" * 80)

    logger = ResearchLogger()
    logger.log_event("SESSION_START", {"query": user_query})

    graph = build_research_graph()
    initial_state = {
        "user_query": user_query,
        "planner_call_count": 0,
        "loop_counter": 0,
        "observations": {},
        "variables": {},
        "reflections": []
    }

    config = {"configurable": {"thread_id": "research_session_001"}}

    final_state = None
    async for event in graph.astream(initial_state, config=config):
        for node_name, state_update in event.items():
            print(f"\n📍 [Graph Node Transition] ---> 节点: '{node_name}'")
            keys = list(state_update.keys()) if isinstance(state_update, dict) else []
            logger.log_event("NODE_TRANSITION", {"node": node_name, "update_keys": keys})

            if state_update and isinstance(state_update, dict) and "final_report" in state_update:
                final_state = state_update

    print("\n" + "=" * 80)
    print("🎉 [Research Agent 运行完成] 最终高品质行业研报交付物:")
    print("=" * 80)

    # 从 Checkpoint 或 final_state 获取结果
    state_snap = graph.get_state(config)
    final_report = state_snap.values.get("final_report", state_snap.values.get("draft_report", "生成失败"))

    print(final_report)
    print("=" * 80)

    reflections = state_snap.values.get("reflections", [])
    print(f"📊 运行总结统计: 经历 {state_snap.values.get('loop_counter', 0)} 轮质量迭代，积累 {len(reflections)} 条 Reflexion 规则。")
    logger.log_event("SESSION_END", {"final_report_length": len(final_report), "reflections_count": len(reflections)})


def main():
    query = """分析2026年医疗AI行业发展趋势，重点关注：
1. 市场规模与增长率
2. 核心技术路线与突破
3. 主要领军厂商与竞争格局
4. 投资机会
5. 关键风险与合规因素

输出一份严谨、带数据来源标注的行业深度报告。"""
    asyncio.run(run_research_pipeline(query))


if __name__ == "__main__":
    main()
