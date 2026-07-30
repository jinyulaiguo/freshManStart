"""Day 107 单元测试：Phoenix OTEL 配置契约（默认不真实连接导出器）。"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

DAY_DIR = Path(__file__).resolve().parents[1]
if str(DAY_DIR) not in sys.path:
    sys.path.insert(0, str(DAY_DIR))


def test_resolve_phoenix_endpoint_appends_traces_suffix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import phoenix_otel as po

    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.setenv("PHOENIX_COLLECTOR_ENDPOINT", "http://0.0.0.0:6006")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_PROTOCOL", "http/protobuf")
    assert po.resolve_phoenix_endpoint() == "http://0.0.0.0:6006/v1/traces"


def test_resolve_phoenix_endpoint_rewrites_localhost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import phoenix_otel as po

    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.setenv("PHOENIX_COLLECTOR_ENDPOINT", "http://localhost:6006")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_PROTOCOL", "http/protobuf")
    assert po.resolve_phoenix_endpoint() == "http://0.0.0.0:6006/v1/traces"


def test_resolve_phoenix_endpoint_keeps_existing_traces_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import phoenix_otel as po

    monkeypatch.setenv(
        "OTEL_EXPORTER_OTLP_ENDPOINT", "http://0.0.0.0:6006/v1/traces"
    )
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_PROTOCOL", "http/protobuf")
    assert po.resolve_phoenix_endpoint() == "http://0.0.0.0:6006/v1/traces"


def test_disable_langsmith_for_local_otel(monkeypatch: pytest.MonkeyPatch) -> None:
    import phoenix_otel as po

    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    po.disable_langsmith_for_local_otel()
    assert os.environ["LANGSMITH_TRACING"] == "false"
    assert os.environ["LANGCHAIN_TRACING_V2"] == "false"


def test_enable_phoenix_otel_wires_instrumentor(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import phoenix_otel as po

    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "PHOENIX_COLLECTOR_ENDPOINT=http://0.0.0.0:6006",
                "PHOENIX_PROJECT_NAME=unit-phoenix-project",
                "OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf",
                "LANGSMITH_TRACING=true",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    fake_provider = MagicMock(name="TracerProvider")
    fake_register = MagicMock(return_value=fake_provider)
    fake_instrumentor_cls = MagicMock()
    fake_instrumentor = MagicMock()
    fake_instrumentor_cls.return_value = fake_instrumentor

    monkeypatch.setattr(po, "register", fake_register)
    monkeypatch.setattr(po, "LangChainInstrumentor", fake_instrumentor_cls)
    monkeypatch.setattr(po, "_INSTRUMENTED", False)

    status = po.enable_phoenix_otel(dotenv_path=env_file, verbose=False)
    assert status["PHOENIX_ENDPOINT"] == "http://0.0.0.0:6006/v1/traces"
    assert status["PHOENIX_PROJECT_NAME"] == "unit-phoenix-project"
    assert status["LANGSMITH_TRACING"] == "false"
    fake_register.assert_called_once()
    assert fake_register.call_args.kwargs["endpoint"].endswith("/v1/traces")
    fake_instrumentor.instrument.assert_called_once_with(tracer_provider=fake_provider)
