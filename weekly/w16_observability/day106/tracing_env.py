"""
Day 106 · LangSmith 环境绑定（与业务解耦）

只负责加载仓库根 .env，并校验追踪相关变量。
不修改 Agent 业务逻辑。
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[3]
ENV_PATH = REPO_ROOT / ".env"

REQUIRED_TRACING_KEYS = (
    "LANGSMITH_API_KEY",
    "LANGSMITH_TRACING",
)


def load_repo_env(*, dotenv_path: Path | None = None) -> Path:
    """加载仓库根目录 .env，返回实际使用的路径。"""
    path = dotenv_path or ENV_PATH
    if not path.is_file():
        raise FileNotFoundError(
            f"未找到环境文件: {path}\n请先 cp .env.example .env 并填写密钥。"
        )
    load_dotenv(path, override=True)
    return path


def enable_langsmith_tracing(*, dotenv_path: Path | None = None) -> dict[str, str]:
    """
    绑定 LangSmith 追踪环境。

    - 确保 LANGSMITH_TRACING 为 true（字符串）
    - 校验 API Key 存在
    - 回写常用兼容变量，避免个别版本只认 LANGCHAIN_*
    """
    load_repo_env(dotenv_path=dotenv_path)

    api_key = (os.getenv("LANGSMITH_API_KEY") or "").strip()
    if not api_key or api_key.startswith("your_"):
        raise ValueError(
            "LANGSMITH_API_KEY 未配置或仍是占位符。"
            "请到 https://smith.langchain.com/ 创建 Key 并写入根 .env。"
        )

    tracing = (os.getenv("LANGSMITH_TRACING") or "true").strip().lower()
    if tracing not in {"1", "true", "yes", "on"}:
        raise ValueError(
            f"LANGSMITH_TRACING={tracing!r}，Day 106 需要设为 true 才能上报 Trace。"
        )

    project = (os.getenv("LANGSMITH_PROJECT") or "freshman-w16-observability").strip()

    # 进程内显式绑定，保证「业务未改代码」也能追踪
    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_API_KEY"] = api_key
    os.environ["LANGSMITH_PROJECT"] = project
    # 兼容旧文档变量名
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"] = api_key
    os.environ["LANGCHAIN_PROJECT"] = project

    return {
        "LANGSMITH_TRACING": "true",
        "LANGSMITH_PROJECT": project,
        "LANGSMITH_API_KEY_SET": "yes",
    }


def assert_tracing_ready(*, dotenv_path: Path | None = None) -> None:
    """供练习 / 测试调用的显式断言。"""
    status = enable_langsmith_tracing(dotenv_path=dotenv_path)
    assert status["LANGSMITH_TRACING"] == "true"
    assert status["LANGSMITH_API_KEY_SET"] == "yes"
