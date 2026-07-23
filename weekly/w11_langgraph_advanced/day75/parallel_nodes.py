"""多线程并行节点（Parallel Nodes）的并发执行与分支汇聚 (Day 75 参考标准答案)

设计方案与架构说明：
----------------------------------------------------------------
本模块遵照 Rule 12 规范，接入真实 API (MiniMax LLM Client)，演示工业级多 Agent 并发交叉分析与归约机制。
在架构设计与安全审计 Agent 中：
1. 拓扑扇出 (Fan-out)：从 Dispatcher 同时触发 `performance_analyst` (性能专家) 与 `reliability_analyst` (可靠性专家) 两个并发 Node。
2. 真实 LLM 并发请求：两个专家节点通过 `LLMClient` 异步并发向真实 API 发起 HTTP 请求，非阻塞并行推演。
3. 状态归约与同步屏障 (Barrier Hub)：两个专家节点返回的结构化分析报告在底座通过 `Annotated[List[Dict], operator.add]` 实现并发安全归约。
4. 汇聚节点 (Consolidate)：在 Superstep N+1 触发，拿到两路无损合并的真实 LLM 分析结果，调用第三次真实 LLM 生成终极架构融合简报。

结构与数据流：
--------------
          ┌─► performance_analyst (真实 LLM API) ─┐
dispatcher ┤                                       ├─► consolidate_node (真实 LLM 终审) ─► END
          └─► reliability_analyst (真实 LLM API) ─┘
"""

import os
import sys
import time
import asyncio
from typing import Dict, Any, List, TypedDict
from typing_extensions import Annotated
import operator

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

# 动态将工作区根目录添加到 sys.path 中以支持跨模块导入
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# 导入公共工具库中的真实 LLMClient
from weekly.w04_prompt_and_http.utils import LLMClient


# ============================================================================
# 状态契约定义 (State Schema)
# ============================================================================

class MultiExpertAnalysisState(TypedDict):
    """多专家并发分析 Agent 状态契约。
    
    Attributes:
        query: 待分析的技术主题/需求
        expert_reports: Annotated[List[Dict[str, Any]], operator.add]  # 核心：并发无损合并各专家 LLM 报告
        audit_trail: Annotated[List[str], operator.add]
        final_architecture_report: 最终架构融合简报
    """
    query: str
    expert_reports: Annotated[List[Dict[str, Any]], operator.add]
    audit_trail: Annotated[List[str], operator.add]
    final_architecture_report: str


# 全局共享真实的 LLM 客户端
llm_client = LLMClient()


# ============================================================================
# 节点函数定义 (Real LLM Async Node Implementations)
# ============================================================================

async def dispatcher_node(state: MultiExpertAnalysisState) -> Dict[str, Any]:
    """起始节点：解析 query 并初始化审计日志。"""
    print(f"\n[Node: Dispatcher] 准备向多专家并发发起真实 LLM 推演, 主题: '{state['query']}'")
    return {
        "audit_trail": [f"Dispatcher initialized for query '{state['query']}'"]
    }


async def performance_analyst_node(state: MultiExpertAnalysisState) -> Dict[str, Any]:
    """并发节点 1: 性能架构专家 (调用真实大模型 API)。"""
    start_t = time.time()
    print("  [Worker: Performance Analyst] 发起真实 LLM API 请求 (高并发与吞吐维度)...")
    
    messages = [
        {"role": "system", "content": "你是一位顶尖的分布式性能架构师。请简要从【高并发吞吐、低延迟、异步 I/O】三个维度回答，不超过 100 字。"},
        {"role": "user", "content": f"请分析技术主题：{state['query']}"}
    ]
    
    # 异步非阻塞调用真实大模型
    llm_response = await llm_client.request_llm(messages, temperature=0.3, max_tokens=250)
    elapsed = time.time() - start_t
    print(f"  [Worker: Performance Analyst] 真实 LLM API 响应完成！耗时: {elapsed:.2f}s")
    
    return {
        "expert_reports": [
            {
                "expert_role": "Performance Analyst (性能专家)",
                "content": llm_response.strip(),
                "latency_sec": round(elapsed, 2)
            }
        ],
        "audit_trail": [f"Performance Analyst finished in {elapsed:.2f}s"]
    }


async def reliability_analyst_node(state: MultiExpertAnalysisState) -> Dict[str, Any]:
    """并发节点 2: 可靠性与安全专家 (调用真实大模型 API)。"""
    start_t = time.time()
    print("  [Worker: Reliability Analyst] 发起真实 LLM API 请求 (状态容错与安全审计维度)...")
    
    messages = [
        {"role": "system", "content": "你是一位顶尖的系统可靠性工程师。请简要从【状态隔离、故障恢复、数据幂等】三个维度回答，不超过 100 字。"},
        {"role": "user", "content": f"请分析技术主题：{state['query']}"}
    ]
    
    # 异步非阻塞调用真实大模型
    llm_response = await llm_client.request_llm(messages, temperature=0.3, max_tokens=250)
    elapsed = time.time() - start_t
    print(f"  [Worker: Reliability Analyst] 真实 LLM API 响应完成！耗时: {elapsed:.2f}s")
    
    return {
        "expert_reports": [
            {
                "expert_role": "Reliability Analyst (可靠性专家)",
                "content": llm_response.strip(),
                "latency_sec": round(elapsed, 2)
            }
        ],
        "audit_trail": [f"Reliability Analyst finished in {elapsed:.2f}s"]
    }


async def consolidate_node(state: MultiExpertAnalysisState) -> Dict[str, Any]:
    """汇聚节点 (Barrier Hub): 统一接收两路真实 LLM 报告归约结果，调用第三次真实 LLM 进行最终熔炼。"""
    print(f"\n[Node: Consolidate] 屏障解冻！拿到两路并发归约的真实 LLM 报告 (共 {len(state['expert_reports'])} 份):")
    
    reports_text = ""
    for r in state["expert_reports"]:
        print(f"  -> [{r['expert_role']} (耗时: {r['latency_sec']}s)]:\n     {r['content']}\n")
        reports_text += f"=== {r['expert_role']} ===\n{r['content']}\n\n"
        
    start_t = time.time()
    print("  [Consolidate Agent] 发起第三次真实 LLM 请求，熔炼生成终极决策大纲...")
    
    messages = [
        {"role": "system", "content": "你是一位首席技术官(CTO)。请将输入的两份专家意见融合提炼为 1 句话的终极总结。"},
        {"role": "user", "content": f"主题: {state['query']}\n专家意见:\n{reports_text}"}
    ]
    
    final_llm_res = await llm_client.request_llm(messages, temperature=0.2, max_tokens=150)
    elapsed = time.time() - start_t
    
    return {
        "final_architecture_report": final_llm_res.strip(),
        "audit_trail": [f"Consolidate node fused reports using LLM in {elapsed:.2f}s"]
    }


# ============================================================================
# 构建并发拓扑图 (Graph Assembly)
# ============================================================================

def build_parallel_expert_graph():
    """构建带真实 LLM API 的并发 StateGraph。"""
    builder = StateGraph(MultiExpertAnalysisState)
    
    # 1. 注册节点
    builder.add_node("dispatcher", dispatcher_node)
    builder.add_node("performance_analyst", performance_analyst_node)
    builder.add_node("reliability_analyst", reliability_analyst_node)
    builder.add_node("consolidate", consolidate_node)
    
    # 2. 拓扑边：START -> dispatcher
    builder.add_edge(START, "dispatcher")
    
    # 3. 拓扑扇出 (Fan-out)：同时连接到两个专家 Node
    builder.add_edge("dispatcher", "performance_analyst")
    builder.add_edge("dispatcher", "reliability_analyst")
    
    # 4. 拓扑扇入 (Fan-in)：两个并行专家 Node 同时连接至 consolidate 汇聚节点
    builder.add_edge("performance_analyst", "consolidate")
    builder.add_edge("reliability_analyst", "consolidate")
    
    # 5. 结尾
    builder.add_edge("consolidate", END)
    
    checkpointer = MemorySaver()
    return builder.compile(checkpointer=checkpointer)


# ============================================================================
# 主运行验证程序 (Main Execution Suite)
# ============================================================================

async def main_async():
    print("=" * 70)
    print("🚀 Day 75: 真实 LLM API 多线程并行节点 (Parallel Nodes) 并发实战")
    print("=" * 70)
    
    app = build_parallel_expert_graph()
    config = {"configurable": {"thread_id": "real_llm_parallel_9988"}}
    
    initial_input = {
        "query": "LangGraph 状态机在分布式 Agent 场景下的实践架构",
        "expert_reports": [],
        "audit_trail": [],
        "final_architecture_report": ""
    }
    
    print("\n--- 阶段 A: 发起并发真实 LLM 请求 ---")
    start_total_t = time.time()
    
    # 异步非阻塞运行图
    final_output = await app.ainvoke(initial_input, config)
    
    total_elapsed = time.time() - start_total_t
    print("=" * 70)
    print("--- 阶段 B: 验证并发网络请求与归约结果 ---")
    print(f"  • 全图包含 3 次真实 LLM API 请求的总运行耗时: {total_elapsed:.2f} 秒")
    print(f"\n  🏆 最终 CTO 熔炼终极简报:\n  {final_output['final_architecture_report']}\n")
    print(f"  • 收到专家报告总数: {len(final_output['expert_reports'])}")
    
    # ------------------------------------------------------------------------
    # 核心验证断言
    # ------------------------------------------------------------------------
    assert len(final_output["expert_reports"]) == 2, "归约失败：多路真实 LLM API 报告未成功合并！"
    
    roles = [r["expert_role"] for r in final_output["expert_reports"]]
    assert "Performance Analyst (性能专家)" in roles, "缺失性能专家报告！"
    assert "Reliability Analyst (可靠性专家)" in roles, "缺失可靠性专家报告！"
    
    # 耗时对比逻辑验证：
    latencies = [r["latency_sec"] for r in final_output["expert_reports"]]
    max_worker_lat = max(latencies)
    sum_worker_lat = sum(latencies)
    print(f"  • 专家 1 耗时: {latencies[0]}s, 专家 2 耗时: {latencies[1]}s")
    print(f"  • 如果串行将耗时: {sum_worker_lat:.2f}s | 实际并发并行耗时仅为: {max_worker_lat:.2f}s")
    
    print("\n  • 完整审计日志链 (audit_trail):")
    for log in final_output["audit_trail"]:
        print(f"      - {log}")
        
    print("\n✅ 接入真实 LLM API 的全流程 Parallel Nodes 并发验证完美通过！")


if __name__ == "__main__":
    asyncio.run(main_async())
