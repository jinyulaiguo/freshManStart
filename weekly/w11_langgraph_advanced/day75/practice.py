"""Day 75 练习模版：多线程并行节点（Parallel Nodes）的并发执行与分支汇聚

说明：
本文件为学员练习专用模版。请根据规范完成其中的 TODO 核心逻辑。
目标：实现 Fan-out 并发发散与 Fan-in 汇聚归约，使用 Annotated[list, operator.add] 防止并发覆盖。
"""

import sys
import asyncio
import time
from typing import Dict, Any, List, TypedDict
from typing_extensions import Annotated
import operator

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver


# ============================================================================
# 1. 契约定义
# ============================================================================

class ParallelPracticeState(TypedDict):
    """并发练习状态契约"""
    query: str
    results: Annotated[List[str], operator.add]
    logs: Annotated[List[str], operator.add]


# ============================================================================
# 2. 节点逻辑与图编排 (TODO 练习)
# ============================================================================

async def start_dispatch_node(state: ParallelPracticeState) -> Dict[str, Any]:
    """起始节点"""
    print("[Practice Dispatcher] 开始并发分发...")
    return {"logs": ["Started dispatch"]}


async def worker_alpha_node(state: ParallelPracticeState) -> Dict[str, Any]:
    """并行 Worker A (模拟延迟 0.3s)"""
    await asyncio.sleep(0.3)
    print("  [Worker Alpha] Alpha 运行完成")
    return {"results": ["Alpha Result"], "logs": ["Alpha done"]}


async def worker_beta_node(state: ParallelPracticeState) -> Dict[str, Any]:
    """并行 Worker B (模拟延迟 0.5s)"""
    await asyncio.sleep(0.5)
    print("  [Worker Beta] Beta 运行完成")
    return {"results": ["Beta Result"], "logs": ["Beta done"]}


async def consolidate_practice_node(state: ParallelPracticeState) -> Dict[str, Any]:
    """汇聚节点"""
    print(f"[Practice Consolidate] 汇聚节点拿到 {len(state['results'])} 条并发结果: {state['results']}")
    return {"logs": ["Consolidate completed"]}


def build_parallel_practice_graph():
    """构建并发拓扑图"""
    # TODO 1.1: 构建 StateGraph(ParallelPracticeState)
    # TODO 1.2: 注册节点 "start", "alpha", "beta", "consolidate"
    # TODO 1.3: 配置 Fan-out 拓扑边 (为 "start" 分别添加两条边指往 "alpha" 与 "beta")
    # TODO 1.4: 配置 Fan-in 拓扑边 ("alpha" -> "consolidate", "beta" -> "consolidate")
    # TODO 1.5: 编译并返回 compiled app
    raise NotImplementedError("TODO: 请实现 build_parallel_practice_graph 逻辑")


# ============================================================================
# 调试主入口 (带有友好的 TODO 拦截)
# ============================================================================

async def main_async():
    print("=" * 60)
    print("🚀 Day 75 多线程并行节点练习入口")
    print("=" * 60)
    
    try:
        app = build_parallel_practice_graph()
        config = {"configurable": {"thread_id": "prac_par_01"}}
        
        init_state = {"query": "Test Parallel", "results": [], "logs": []}
        output = await app.ainvoke(init_state, config)
        print(f"✅ 执行成功，最终汇聚结果数: {len(output.get('results', []))}")
        
    except NotImplementedError as e:
        print(f"💡 [TODO 提示] 练习未完成: {e}")
    except Exception as e:
        print(f"❌ 运行报错: {e}")


if __name__ == "__main__":
    asyncio.run(main_async())
