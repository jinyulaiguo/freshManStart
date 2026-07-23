"""终端 REPL 交互入口 (Day 77 交互控制台)

设计方案与架构说明：
----------------------------------------------------------------
本模块提供纯终端交互式 REPL 运行环境。
1. 自然语言交互：输入查询驱动主图运行。
2. HITL 断点交互拦截：
   - 当检测到图中断挂起在 `sql_execution` 之前时，打印待执行 SQL 告警。
   - 交互提示输入：
     - `approve`: 直接批准放行。
     - `reject`: 拒绝阻断，写入 audit_trail。
     - `edit:<new_sql>`: 修改 SQL，使用 `update_state(config, patch, as_node="risk_assess")` 覆写并恢复。
3. 时间旅行 (Time Travel) 操作台：
   - 输入 `history`: 遍历展示该 thread 上的全量 Checkpoint 链。
   - 输入 `fork:<idx>`: 选择特定历史快照点修补参数并启动分叉二次推演。

数据流与生命周期：
------------------
REPL Loop -> app.ainvoke() -> [Interrupt Handler] -> [Time Travel Handler] -> 终局展示
"""

import os
import sys
import asyncio
from typing import Dict, Any

from langchain_core.messages import HumanMessage

# 动态将工作区根目录添加到 sys.path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../"))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from weekly.w11_langgraph_advanced.day77.graph.build_graph import build_sql_agent_graph
from weekly.w11_langgraph_advanced.day77.checkpoint.redis_checkpointer import ProductionRedisCheckpointer


async def run_hitl_approval_loop(app, config):
    """处理断点挂起的人工审批与参数纠偏逻辑。"""
    snapshot = app.get_state(config)

    # 检查是否处于中断挂起状态
    if snapshot.next == ("sql_execution",):
        print("\n" + "=" * 70)
        print("⛔ 触发 HITL 断点挂起：检测到敏感/写操作 SQL 指令，等待人工安全审计！")
        print("=" * 70)
        print(f"  • 待执行 SQL: '{snapshot.values.get('generated_sql')}'")
        print(f"  • 风险评估分析: {snapshot.values.get('risk_analysis')}")
        print("-" * 70)
        print("请选择审批动作: [1] approve (批准) | [2] reject (拒绝) | [3] edit:<新SQL> (修改SQL后放行)")

        user_action = input("审批指令 > ").strip()

        if user_action.startswith("edit:"):
            new_sql = user_action[5:].strip()
            print(f"  ✏️ 人工修正 SQL 为: '{new_sql}'，通过 update_state (as_node='risk_assess') 写入...")
            app.update_state(
                config,
                {
                    "generated_sql": new_sql,
                    "approval_status": "edited",
                    "audit_trail": [f"Human auditor edited SQL to: '{new_sql}' and approved."]
                },
                as_node="risk_assess"
            )
            print("  ▶️ 解冻控制流，继续推演...")
            return await app.ainvoke(None, config)

        elif user_action == "reject" or user_action == "2":
            print("  ❌ 人工否定该笔操作，终止执行并记录审计...")
            app.update_state(
                config,
                {
                    "approval_status": "rejected",
                    "audit_trail": ["Human auditor REJECTED execution."]
                },
                as_node="risk_assess"
            )
            return await app.ainvoke(None, config)

        else:
            print("  ✅ 人工审查批准通过！解冻放行...")
            app.update_state(
                config,
                {
                    "approval_status": "approved",
                    "audit_trail": ["Human auditor APPROVED execution."]
                },
                as_node="risk_assess"
            )
            return await app.ainvoke(None, config)

    return snapshot.values


async def handle_time_travel(app, config):
    """处理 Time Travel 历史查看与分叉推演。"""
    print("\n--- 检索 Redis 中的全量 Checkpoint 历史快照链 (按时间倒序) ---")
    history = list(app.get_state_history(config))
    print(f"共检索到 {len(history)} 个快照版本:")

    for idx, snap in enumerate(history):
        cp_id = snap.config["configurable"]["checkpoint_id"]
        next_node = snap.next
        sql_val = snap.values.get("generated_sql", "N/A")
        tag = "[最新]" if idx == 0 else ""
        print(f"  [{idx}] {tag} cp_id: {cp_id[:8]}... | next: {next_node} | SQL: '{sql_val[:40]}'")

    print("\n如需发起“时间旅行”分叉，请输入快照编号 (如 1)；或直接回车跳过:")
    choice = input("分叉编号 > ").strip()
    if choice.isdigit() and int(choice) < len(history):
        target_snap = history[int(choice)]
        fork_config = target_snap.config
        print(f"\n🎯 已选择快照点 [{choice}] (cp_id: {fork_config['configurable']['checkpoint_id'][:8]})")
        new_sql = input("请输入分叉后执行的新 SQL 语句 > ").strip()

        # 注入 Patch 并获取 new_config
        new_config = app.update_state(
            fork_config,
            {
                "generated_sql": new_sql,
                "audit_trail": [f"Time Travel Fork created with new SQL: '{new_sql}'"]
            }
        )
        print("  🚀 启动分叉二次推演...")
        res = await app.ainvoke(None, new_config)
        print(f"  ✅ 分叉推演完结! 结果记录数: {len(res.get('execution_result', []) or [])}")


async def main_cli():
    """CLI 主运行循环。"""
    print("=" * 70)
    print("🚀 Day 77: 企业级 SQL 执行 Agent 交互控制台 (PG + Redis Checkpointer)")
    print("=" * 70)

    checkpointer = ProductionRedisCheckpointer()
    app = build_sql_agent_graph(checkpointer)

    thread_id = "cli_session_9900"
    config = {"configurable": {"thread_id": thread_id}}

    while True:
        print("\n" + "-" * 70)
        print("请输入自然语言查询需求 (或输入 'history'/'fork'/'quit'):")
        user_input = input("User > ").strip()

        if not user_input or user_input.lower() == "quit":
            print("👋 再见！")
            break

        if user_input.lower() in ["history", "fork"]:
            await handle_time_travel(app, config)
            continue

        init_state = {
            "messages": [HumanMessage(content=user_input)],
            "generated_sql": None,
            "sql_params": None,
            "risk_level": "safe",
            "risk_analysis": None,
            "approval_status": "pending",
            "execution_result": None,
            "error_log": [],
            "audit_trail": [f"CLI user initiated query: '{user_input}'"]
        }

        # 1. 启动图运行
        await app.ainvoke(init_state, config)

        # 2. 检查并处理断点挂起循环
        final_values = await run_hitl_approval_loop(app, config)

        print("\n--- 阶段终局状态 ---")
        print(f"  • 风险等级: {final_values.get('risk_level')}")
        print(f"  • 审批状态: {final_values.get('approval_status')}")
        print(f"  • 执行数据行数: {len(final_values.get('execution_result', []) or [])}")
        print("  • 审计日志:")
        for log in final_values.get("audit_trail", [])[-3:]:
            print(f"      - {log}")


if __name__ == "__main__":
    asyncio.run(main_cli())
