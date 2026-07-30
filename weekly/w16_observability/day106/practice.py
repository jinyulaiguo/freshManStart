"""
Week 16 Day 106 练习入口: LangSmith 零侵入追踪绑定

===============================================================================
练习目标
===============================================================================
1. 通过 tracing_env 加载环境变量，绑定 LangSmith（不改 agent_core）。
2. 运行会触发多轮 Tool Call 的 ReAct Query。
3. 到 LangSmith 后台确认 Thought -> Action -> Observation 树状 Trace。

运行:
  cd weekly/w16_observability/day106
  python practice.py
===============================================================================
"""

from __future__ import annotations

import ast
from pathlib import Path

from agent_core import run_agent
from tracing_env import assert_tracing_ready, enable_langsmith_tracing

DAY_DIR = Path(__file__).resolve().parent

# 必须能逼出 lookup_stock + calc_quote 的多步问题
DEFAULT_QUERY = (
    "请查询 SKU-1001 的库存与单价，然后按采购 4 件计算报价小计，"
    "并说明库存是否足够。"
)


def _agent_core_imports_langsmith() -> bool:
    """静态检查：核心业务文件不得依赖 langsmith。"""
    source = (DAY_DIR / "agent_core.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "langsmith" or alias.name.startswith("langsmith."):
                    return True
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module == "langsmith" or node.module.startswith("langsmith."):
                return True
    return False


def main() -> None:
    # TODO(学员可自测): 调用 enable_langsmith_tracing 并打印 project 名
    status = enable_langsmith_tracing()
    assert_tracing_ready()
    print("[Day106] LangSmith tracing bound:")
    for k, v in status.items():
        print(f"  {k}={v}")

    if _agent_core_imports_langsmith():
        raise RuntimeError(
            "过关失败：agent_core.py 不应 import langsmith。"
            "请保持业务与追踪解耦。"
        )
    print("[Day106] agent_core 无 langsmith 依赖 ✓")

    print(f"[Day106] query: {DEFAULT_QUERY}")
    answer = run_agent(DEFAULT_QUERY)
    print("[Day106] agent answer:")
    print(answer)
    print()
    print("[Day106] 请打开 https://smith.langchain.com")
    print(f"         项目: {status['LANGSMITH_PROJECT']}")
    print("         验收: 最新 Run 中可见 LLM + lookup_stock / calc_quote 嵌套节点")


if __name__ == "__main__":
    main()
