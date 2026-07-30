"""Day 106 单元测试：环境绑定契约（不依赖外网 / LangSmith）。"""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

import pytest

DAY_DIR = Path(__file__).resolve().parents[1]
if str(DAY_DIR) not in sys.path:
    sys.path.insert(0, str(DAY_DIR))


def test_agent_core_must_not_import_langsmith() -> None:
    source = (DAY_DIR / "agent_core.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("langsmith")
        if isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith("langsmith")


def test_enable_langsmith_tracing_requires_api_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import tracing_env as te

    env_file = tmp_path / ".env"
    env_file.write_text(
        "LANGSMITH_TRACING=true\nLANGSMITH_API_KEY=\n",
        encoding="utf-8",
    )
    for key in (
        "LANGSMITH_API_KEY",
        "LANGCHAIN_API_KEY",
        "LANGSMITH_TRACING",
        "LANGCHAIN_TRACING_V2",
    ):
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(ValueError, match="LANGSMITH_API_KEY"):
        te.enable_langsmith_tracing(dotenv_path=env_file)


def test_enable_langsmith_tracing_sets_process_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import tracing_env as te

    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "LANGSMITH_API_KEY=lsv2_pt_test_key_for_unit",
                "LANGSMITH_TRACING=true",
                "LANGSMITH_PROJECT=unit-test-project",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    for key in (
        "LANGSMITH_API_KEY",
        "LANGCHAIN_API_KEY",
        "LANGSMITH_TRACING",
        "LANGCHAIN_TRACING_V2",
        "LANGSMITH_PROJECT",
        "LANGCHAIN_PROJECT",
    ):
        monkeypatch.delenv(key, raising=False)

    status = te.enable_langsmith_tracing(dotenv_path=env_file)
    assert status["LANGSMITH_PROJECT"] == "unit-test-project"
    assert os.environ["LANGSMITH_TRACING"] == "true"
    assert os.environ["LANGSMITH_API_KEY"] == "lsv2_pt_test_key_for_unit"
    assert os.environ["LANGCHAIN_PROJECT"] == "unit-test-project"
