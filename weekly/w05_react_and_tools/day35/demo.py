"""
MiniAgent Framework v1.0 — 四个演示场景

使用方式（在项目根目录）：
    python -m weekly.w05_react_and_tools.day35.demo

需要有效的 MINIMAX_API_KEY 环境变量（通过 .env 文件配置）。
"""
from __future__ import annotations

import asyncio

# ── 导入 Framework 核心组件 ──
from weekly.w05_react_and_tools.day35.mini_agent.agent.registry import registry
from weekly.w05_react_and_tools.day35.mini_agent.agent.runner import ReActAgentRunner
from weekly.w05_react_and_tools.day35.mini_agent.agent.event_bus import EventBus
from weekly.w05_react_and_tools.day35.mini_agent.logger.json_logger import JSONStepLogger

# ── 触发工具注册（导入 tools 子包会自动执行 @tool 装饰器）──
import weekly.w05_react_and_tools.day35.mini_agent.tools  # noqa: F401


def build_runner(max_steps: int = 8) -> tuple[ReActAgentRunner, JSONStepLogger]:
    """构建一个带 Logger 的 Runner 实例。"""
    event_bus = EventBus()
    logger = JSONStepLogger(event_bus=event_bus)
    runner = ReActAgentRunner(
        registry=registry,
        max_steps=max_steps,
        max_retries=3,
        stuck_window=3,
        event_bus=event_bus,
    )
    return runner, logger


# ──────────────────────────────────────────────
# Demo 1: 单工具调用
# ──────────────────────────────────────────────
async def demo1_single_tool():
    """Demo 1: 单工具调用 — 查杭州天气，验证基本工具调度能力。"""
    print("\n" + "█" * 60)
    print("  Demo 1: 单工具调用 — 查杭州天气")
    print("█" * 60)

    runner, _ = build_runner()
    state = await runner.run("请查询杭州的当前天气状况，并告诉我需要带雨伞吗？")

    print(f"\n── Demo 1 完成 ──")
    print(f"终止原因: {state.finish_reason}")
    print(f"最终答复: {state.metadata.get('final_reply', '无')}")
    print(f"总步数: {state.step}")
    print(f"工具调用次数: {len(state.tool_history)}")


# ──────────────────────────────────────────────
# Demo 2: 并行工具调用
# ──────────────────────────────────────────────
async def demo2_parallel_tools():
    """Demo 2: 并行工具调用 — 同时查询北京、上海、杭州三城市天气，验证 Parallel Executor。"""
    import time

    print("\n" + "█" * 60)
    print("  Demo 2: 并行工具调用 — 同时查 3 个城市天气")
    print("  （验证并行调度：总时间 ≈ 单次耗时，而非 3 倍）")
    print("█" * 60)

    runner, _ = build_runner()
    start = time.monotonic()
    state = await runner.run("请同时查询北京、上海和杭州三个城市的当前天气，并做一个简单对比总结。")
    elapsed = time.monotonic() - start

    print(f"\n── Demo 2 完成 ──")
    print(f"终止原因: {state.finish_reason}")
    print(f"最终答复: {state.metadata.get('final_reply', '无')}")
    print(f"总步数: {state.step}")
    print(f"工具调用次数: {len(state.tool_history)}")
    print(f"总耗时: {elapsed:.2f}s")


# ──────────────────────────────────────────────
# Demo 3: Self-Correction 自愈
# ──────────────────────────────────────────────
async def demo3_self_correction():
    """
    Demo 3: Self-Correction 自愈 — 模拟参数错误后自动纠正。
    计算 'sqrt(2)' 并要求用科学计数法表示，故意让模型先尝试一个错误格式。
    """
    print("\n" + "█" * 60)
    print("  Demo 3: Self-Correction 自愈 — 错误参数 → 反思 → 纠正")
    print("█" * 60)

    runner, _ = build_runner()
    state = await runner.run(
        "请帮我查询用户 '小明' 在 '2026年6月1日' 这一天的记录。"
        "注意：日期必须严格使用 YYYY-MM-DD 格式才能查询成功。"
        "如果格式不对，请自行反思并修正后重试。"
        "（提示：请使用 calculator 工具计算一个关于当前日期格式的问题）"
    )

    print(f"\n── Demo 3 完成 ──")
    print(f"终止原因: {state.finish_reason}")
    print(f"最终答复: {state.metadata.get('final_reply', '无')}")
    print(f"总步数: {state.step}")
    print(f"重试次数: {state.retry_count}")


# ──────────────────────────────────────────────
# Demo 4: Error Boundary — 超时异常处理
# ──────────────────────────────────────────────
async def demo4_error_boundary():
    """
    Demo 4: Error Boundary — 模拟工具超时场景（通过极短超时设置）。
    验证 TimeoutException 被安全捕获，Runner 不崩溃。
    """
    print("\n" + "█" * 60)
    print("  Demo 4: Error Boundary — 超时工具被安全降级处理")
    print("  （web_search 需要 2s，设置 1s 超时，触发 TimeoutException）")
    print("█" * 60)

    # 创建一个超时极短的 Runner（1 秒超时，web_search 需要 2 秒）
    event_bus = EventBus()
    logger = JSONStepLogger(event_bus=event_bus)
    runner = ReActAgentRunner(
        registry=registry,
        max_steps=6,
        max_retries=2,
        tool_timeout=0.2,   # 1 秒超时（web_search 需要 2 秒，必然触发 TimeoutException）
        event_bus=event_bus,
    )

    state = await runner.run(
        "请搜索 'Python asyncio 的核心原理' 并给我一个简短总结。"
        "（请使用 web_search 工具）"
    )

    print(f"\n── Demo 4 完成 ──")
    print(f"终止原因: {state.finish_reason}")
    print(f"最终答复: {state.metadata.get('final_reply', '无')}")
    print(f"总步数: {state.step}")
    print(f"重试次数: {state.retry_count}")


# ──────────────────────────────────────────────
# 主入口
# ──────────────────────────────────────────────
async def main():
    """按顺序运行所有演示场景（用户可注释掉不需要的场景）。"""
    print("\n" + "=" * 60)
    print("  MiniAgent Framework v1.0 — 演示脚本")
    print("  需要有效的 MINIMAX_API_KEY")
    print("=" * 60)

    # ── 选择要运行的 Demo（注释掉不需要的即可）──
    await demo1_single_tool()
    print("\n" + "-" * 60)

    await demo2_parallel_tools()
    print("\n" + "-" * 60)

    await demo3_self_correction()
    print("\n" + "-" * 60)

    await demo4_error_boundary()

    print("\n" + "=" * 60)
    print("  所有演示场景已完成！")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
