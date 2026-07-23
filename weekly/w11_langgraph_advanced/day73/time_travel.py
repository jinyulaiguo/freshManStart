"""状态“时间旅行”（Time Travel）与回滚分叉重试 (Day 73 参考标准答案)

设计方案与架构说明：
----------------------------------------------------------------
本模块演示了企业级 Agent 在多步骤推演崩溃时的“时间旅行分叉自愈”核心架构。
在多步骤代码重构与安全审查 Pipeline 中：
1. 主分支推演：系统连续执行 Step 1 (语法分析) -> Step 2 (代码重构) -> Step 3 (AST 安全审计)。
2. 故意引入崩溃：在 Step 3 模拟发生 AST 安全审计报错（如检测到硬编码敏感密钥）。
3. 时间旅行回溯：调用 `get_state_history()` 遍历全量状态快照链，找到 Step 2 (重构完成) 的 `checkpoint_id`。
4. 快照修补与分叉：构造锁定该 `checkpoint_id` 的 `fork_config`，通过 `update_state` 注入安全擦除指令，然后发起分叉 `invoke`。
5. 验证独立性：核验分叉分支成功越过 Step 3 走向成功，且原始崩溃分支的历史记录完好保留。

结构与数据流：
--------------
[START] -> parse_code -> refactor_code -> audit_ast (异常/分叉) -> END
"""

import sys
from typing import Dict, Any, List, TypedDict, Optional
from typing_extensions import Annotated
import operator

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver


# ============================================================================
# 状态契约定义 (State Schema)
# ============================================================================

class CodeRefactorState(TypedDict):
    """代码重构 Agent 状态契约。
    
    Attributes:
        task_id: 重构任务 ID
        code_snippet: 代码片段内容
        ast_passed: AST 安全检查是否通过
        step_history: 步骤流转轨迹
        audit_logs: 审计日志链
    """
    task_id: str
    code_snippet: str
    ast_passed: bool
    step_history: Annotated[List[str], operator.add]
    audit_logs: Annotated[List[str], operator.add]


# ============================================================================
# 节点函数定义 (Node Implementations)
# ============================================================================

def parse_code_node(state: CodeRefactorState) -> Dict[str, Any]:
    """Step 1: 代码语法分析与 Token 提取。"""
    print(f"\n[Node 1: Parse] 正在解析代码结构 ({state['task_id']})...")
    return {
        "step_history": ["step1_parse_complete"],
        "audit_logs": ["AST 语法解析成功"]
    }


def refactor_code_node(state: CodeRefactorState) -> Dict[str, Any]:
    """Step 2: 代码重构推演。"""
    print(f"\n[Node 2: Refactor] 正在重构代码与优化计算结构...")
    return {
        "step_history": ["step2_refactor_complete"],
        "audit_logs": [f"代码重构完成。当前代码片段: '{state['code_snippet']}'"]
    }


def audit_ast_node(state: CodeRefactorState) -> Dict[str, Any]:
    """Step 3: AST 安全审计。判定是否存在硬编码密钥。"""
    print(f"\n[Node 3: Audit] 正在执行 AST 深度安全检查...")
    
    snippet = state.get("code_snippet", "")
    # 判定：如果包含 "HARDCODED_KEY"，判定为安全违规崩溃
    if "HARDCODED_KEY" in snippet:
        print("  ⚠️ 安全风险: 拦截到硬编码敏感密钥 'HARDCODED_KEY'！")
        return {
            "ast_passed": False,
            "step_history": ["step3_audit_failed"],
            "audit_logs": ["AST 审计拒绝: 存在安全隐患 HARDCODED_KEY"]
        }
        
    print("  ✅ AST 安全审计无缝通过！")
    return {
        "ast_passed": True,
        "step_history": ["step3_audit_passed"],
        "audit_logs": ["AST 审计通过: 规则符合生产规范"]
    }


# ============================================================================
# 编排有向图
# ============================================================================

def build_time_travel_graph():
    """构建带 Checkpointer 的重构图。"""
    builder = StateGraph(CodeRefactorState)
    
    builder.add_node("parse_code", parse_code_node)
    builder.add_node("refactor_code", refactor_code_node)
    builder.add_node("audit_ast", audit_ast_node)
    
    builder.add_edge(START, "parse_code")
    builder.add_edge("parse_code", "refactor_code")
    builder.add_edge("refactor_code", "audit_ast")
    builder.add_edge("audit_ast", END)
    
    checkpointer = MemorySaver()
    return builder.compile(checkpointer=checkpointer)


# ============================================================================
# 主运行验证程序 (Main Execution Suite)
# ============================================================================

def main():
    print("=" * 70)
    print("🚀 Day 73: 状态“时间旅行”（Time Travel）与回滚分叉重试实战")
    print("=" * 70)
    
    app = build_time_travel_graph()
    thread_id = "time_travel_thread_2026"
    config = {"configurable": {"thread_id": thread_id}}
    
    # 初始状态输入 (故意带入含有隐患的代码)
    initial_input = {
        "task_id": "REFACTOR_TASK_009",
        "code_snippet": "def connect_db(): return connect(key='HARDCODED_KEY')",
        "ast_passed": False,
        "step_history": [],
        "audit_logs": []
    }
    
    # ------------------------------------------------------------------------
    # 阶段 A: 运行主分支，直至在 Step 3 发生审计失败
    # ------------------------------------------------------------------------
    print("\n--- 阶段 A: 运行原始主分支 (Original Execution Trace) ---")
    main_output = app.invoke(initial_input, config)
    print(f"\n[主分支运行完结] 最终 AST 状态: ast_passed={main_output.get('ast_passed')}")
    print("  日志链:")
    for log in main_output["audit_logs"]:
        print(f"    - {log}")
        
    assert main_output["ast_passed"] is False, "测试预警：主分支未能模拟出预期的安全拦截错误！"
    
    # ------------------------------------------------------------------------
    # 阶段 B: 读取 Checkpoint 历史快照链
    # ------------------------------------------------------------------------
    print("\n--- 阶段 B: 调用 get_state_history 检索快照链 (DAG) ---")
    history_list = list(app.get_state_history(config))
    print(f"  • 共检索到 {len(history_list)} 个 Checkpoint 历史快照版本:")
    
    for i, snapshot in enumerate(history_list):
        cp_id = snapshot.config["configurable"]["checkpoint_id"]
        next_node = snapshot.next
        step_hist = snapshot.values.get("step_history", [])
        print(f"    [{i}] checkpoint_id: {cp_id} | 待执行 next: {next_node} | 已完成步骤: {step_hist}")
        
    # ------------------------------------------------------------------------
    # 阶段 C: 挑选 Step 2 (refactor_code 执行完毕) 的快照作为分叉起点
    # ------------------------------------------------------------------------
    print("\n--- 阶段 C: 寻找 Step 2 完成时的快照点，发起“时间旅行” ---")
    
    # 过滤找到待执行节点为 'audit_ast' (即 Step 2 执行完，准备进入 Step 3) 的快照
    target_snapshot = None
    for snap in history_list:
        if snap.next == ("audit_ast",):
            target_snapshot = snap
            break
            
    assert target_snapshot is not None, "历史寻找失败：未查找到准备进入 audit_ast 的 Checkpoint 点！"
    
    fork_cp_id = target_snapshot.config["configurable"]["checkpoint_id"]
    print(f"  🎯 找到的目标时间旅行点 checkpoint_id: {fork_cp_id}")
    
    # ------------------------------------------------------------------------
    # 阶段 D: 构造 fork_config，在历史点 update_state 并发起分叉运行
    # ------------------------------------------------------------------------
    print("\n--- 阶段 D: 原位修补状态 (Patch State) 并启动分叉二次推演 ---")
    # 直接复用 target_snapshot.config 包含完整的 checkpoint_ns 等引擎元数据
    fork_config = target_snapshot.config
    
    safe_code = "def connect_db(): return connect(key=os.getenv('DB_KEY'))"
    # 注入修正后的安全代码，接收 update_state 生成的最新分叉 checkpoint config (new_config)
    new_config = app.update_state(
        fork_config,
        {
            "code_snippet": safe_code,
            "audit_logs": [f"Human Architect performed Time Travel patch: Safe code injected ('{safe_code}')"]
        }
    )
    
    print("  -> 已写入分叉 Patch，调用 invoke(None, new_config) 解冻分叉分支...")
    fork_output = app.invoke(None, new_config)
    
    # ------------------------------------------------------------------------
    # 阶段 E: 核验分叉结果与历史独立性
    # ------------------------------------------------------------------------
    print("\n--- 阶段 E: 核验时间旅行分叉结果 ---")
    print(f"  • 分叉分支 AST 状态: ast_passed={fork_output.get('ast_passed')}")
    print("  • 分叉分支日志链:")
    for log in fork_output["audit_logs"]:
        print(f"    - {log}")
        
    assert fork_output["ast_passed"] is True, "时间旅行失败：分叉分支未能通过 AST 检查！"
    
    # 再次读取全量历史，验证原始崩溃分支与新分叉分支的 Checkpoint 均完好存盘
    all_history_after = list(app.get_state_history(config))
    print(f"\n  • 当前数据库中总 Checkpoint 节点数: {len(all_history_after)}")
    assert len(all_history_after) > len(history_list), "隔离验证失败：分叉运行未产生新的独立 Checkpoint 节点！"
    
    print("\n✅ 全流程“时间旅行”与分叉重试测试成功通过！")


if __name__ == "__main__":
    main()
