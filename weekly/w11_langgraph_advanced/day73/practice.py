"""Day 73 练习模版：状态“时间旅行”（Time Travel）与回滚分叉重试

说明：
本文件为学员练习专用模版。请根据规范完成其中的 TODO 核心逻辑。
目标：运行多步骤图产生历史快照，读取 get_state_history 挑选特定 checkpoint_id，利用 update_state 进行 Patch 修补并启动分叉执行。
"""

import sys
from typing import Dict, Any, List, TypedDict
from typing_extensions import Annotated
import operator

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver


# ============================================================================
# 状态契约定义
# ============================================================================

class PipelinePracticeState(TypedDict):
    """流水线练习状态契约"""
    task_id: str
    stage: str
    is_valid: bool
    logs: Annotated[List[str], operator.add]


# ============================================================================
# 节点函数与图编排 (TODO 练习)
# ============================================================================

def step_one_node(state: PipelinePracticeState) -> Dict[str, Any]:
    """步骤 1：初始化校验"""
    print("[Practice] 执行步骤 1: 初始化数据")
    return {"stage": "STAGE_1_DONE", "logs": ["Step 1 completed"]}


def step_two_node(state: PipelinePracticeState) -> Dict[str, Any]:
    """步骤 2：核心处理 (可能产生误操作)"""
    print("[Practice] 执行步骤 2: 数据加工")
    return {"stage": "STAGE_2_DONE", "logs": ["Step 2 completed"]}


def step_three_node(state: PipelinePracticeState) -> Dict[str, Any]:
    """步骤 3：终极检测"""
    print("[Practice] 执行步骤 3: 结果检测")
    if not state.get("is_valid", False):
        print("  ⚠️ 步骤 3 校验失败 (is_valid=False)！")
        return {"stage": "FAILED", "logs": ["Step 3 failed validation"]}
    print("  ✅ 步骤 3 校验成功！")
    return {"stage": "SUCCESS", "logs": ["Step 3 passed"]}


def build_practice_graph():
    """构建带 MemorySaver 持久化的多步骤图"""
    # TODO 1.1: 构建 StateGraph(PipelinePracticeState)
    # TODO 1.2: 注册节点 step1 -> step2 -> step3 并连接 START 到 END
    # TODO 1.3: 绑定 MemorySaver 并返回 compiled app
    raise NotImplementedError("TODO: 请实现 build_practice_graph 逻辑")


# ============================================================================
# 调试主入口 (带有友好的 TODO 拦截)
# ============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("🚀 Day 73 时间旅行与分叉重试练习入口")
    print("=" * 60)
    
    try:
        app = build_practice_graph()
        config = {"configurable": {"thread_id": "prac_tt_thread_01"}}
        
        # 1. 启动失败批次
        init_state = {"task_id": "TASK_73", "stage": "INIT", "is_valid": False, "logs": []}
        app.invoke(init_state, config)
        
        # 2. 遍历历史寻找 step3 执行前的快照
        history = list(app.get_state_history(config))
        print(f"✅ 获取到 {len(history)} 个历史 Checkpoint 快照")
        
        # TODO 2.1: 找到待执行节点为 ('step_three_node',) 的 snapshot
        # TODO 2.2: 获取 snapshot.config 作为 fork_config
        # TODO 2.3: 执行 new_config = app.update_state(fork_config, {"is_valid": True})
        # TODO 2.4: 执行 final_output = app.invoke(None, new_config)
        
    except NotImplementedError as e:
        print(f"💡 [TODO 提示] 练习未完成: {e}")
    except Exception as e:
        print(f"❌ 运行报错: {e}")
