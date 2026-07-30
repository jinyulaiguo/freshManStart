"""
Day 107 · Phoenix + OpenTelemetry / OpenInference 绑定

与业务解耦：只负责加载 .env、关闭 LangSmith、注册 OTLP Exporter，
并对 LangChain/LangGraph 启用 OpenInference 自动埋点。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from openinference.instrumentation.langchain import LangChainInstrumentor
from opentelemetry import trace
from phoenix.otel import register

REPO_ROOT = Path(__file__).resolve().parents[3]
ENV_PATH = REPO_ROOT / ".env"

_INSTRUMENTED = False


def load_repo_env(*, dotenv_path: Path | None = None) -> Path:
    path = dotenv_path or ENV_PATH
    if not path.is_file():
        raise FileNotFoundError(
            f"未找到环境文件: {path}\n请先 cp .env.example .env 并填写密钥。"
        )
    load_dotenv(path, override=True)
    return path


def disable_langsmith_for_local_otel() -> None:
    """避免与 Day 106 托管追踪双写，便于观察本地 Phoenix。"""
    os.environ["LANGSMITH_TRACING"] = "false"
    os.environ["LANGCHAIN_TRACING_V2"] = "false"


def resolve_otel_protocol() -> Literal["http/protobuf", "grpc"]:
    protocol = (os.getenv("OTEL_EXPORTER_OTLP_PROTOCOL") or "http/protobuf").strip()
    if protocol not in {"http/protobuf", "grpc"}:
        return "http/protobuf"
    return protocol  # type: ignore[return-value]


def _rewrite_loopback_host(url: str) -> str:
    """
    macOS / Docker Desktop 下 `localhost` 常解析到 IPv6 ::1，
    而容器端口只绑在 IPv4，导致 Connection reset / 连不上。
    统一改写为 0.0.0.0（本机实测与 127.0.0.1 均可达）。
    """
    return (
        url.replace("://localhost", "://0.0.0.0")
        .replace("://[::1]", "://0.0.0.0")
    )


def resolve_phoenix_endpoint(*, protocol: str | None = None) -> str:
    """
    解析 Phoenix collector 地址。

    注意：当前 arize-phoenix-otel 对 HTTP 导出时，endpoint 需带 `/v1/traces`，
    仅传根地址会 POST 到 `/` 得到 405。
    gRPC 使用 `http://0.0.0.0:4317`。
    """
    proto = protocol or resolve_otel_protocol()

    if proto == "grpc":
        raw = (
            os.getenv("PHOENIX_GRPC_ENDPOINT")
            or "http://0.0.0.0:4317"
        ).strip()
        return _rewrite_loopback_host(raw)

    raw = (
        os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
        or os.getenv("PHOENIX_COLLECTOR_ENDPOINT")
        or "http://0.0.0.0:6006"
    ).strip()
    raw = _rewrite_loopback_host(raw)
    if raw.endswith("/v1/traces"):
        return raw
    return raw.rstrip("/") + "/v1/traces"


def enable_phoenix_otel(
    *,
    dotenv_path: Path | None = None,
    verbose: bool = True,
) -> dict[str, Any]:
    """
    注册 TracerProvider → OTLP → 本地 Phoenix，并 instrument LangChain。

    返回便于打印的状态字典（不含密钥）。
    """
    global _INSTRUMENTED

    load_repo_env(dotenv_path=dotenv_path)
    disable_langsmith_for_local_otel()

    protocol = resolve_otel_protocol()
    endpoint = resolve_phoenix_endpoint(protocol=protocol)
    project = (
        os.getenv("PHOENIX_PROJECT_NAME")
        or os.getenv("OTEL_SERVICE_NAME")
        or "freshman-w16-observability"
    ).strip()

    tracer_provider = register(
        endpoint=endpoint,
        project_name=project,
        protocol=protocol,
        batch=False,  # 学习环境：立即导出，便于马上在 UI 看到
        verbose=verbose,
        set_global_tracer_provider=True,
    )

    if not _INSTRUMENTED:
        LangChainInstrumentor().instrument(tracer_provider=tracer_provider)
        _INSTRUMENTED = True

    return {
        "PHOENIX_ENDPOINT": endpoint,
        "PHOENIX_PROJECT_NAME": project,
        "OTEL_PROTOCOL": protocol,
        "LANGSMITH_TRACING": os.environ.get("LANGSMITH_TRACING", "false"),
        "OPENINFERENCE": "langchain",
        "tracer_provider": tracer_provider,
    }


def flush_traces(timeout_millis: int = 10_000) -> None:
    """确保进程退出前 Span 已导出到 Phoenix。"""
    provider = trace.get_tracer_provider()
    force_flush = getattr(provider, "force_flush", None)
    if callable(force_flush):
        force_flush(timeout_millis)


def assert_phoenix_ready(*, dotenv_path: Path | None = None) -> None:
    status = enable_phoenix_otel(dotenv_path=dotenv_path, verbose=False)
    assert "/v1/traces" in status["PHOENIX_ENDPOINT"] or status["OTEL_PROTOCOL"] == "grpc"
    assert status["LANGSMITH_TRACING"] == "false"


def _smoke_probe() -> None:
    """不跑 Agent：只绑定 OTEL 并导出一条探测 Span，验证链路通不通。"""
    status = enable_phoenix_otel(verbose=True)
    printable = {k: v for k, v in status.items() if k != "tracer_provider"}
    print("[phoenix_otel] bound:")
    for k, v in printable.items():
        print(f"  {k}={v}")

    tracer = trace.get_tracer("day107.phoenix_otel.smoke")
    with tracer.start_as_current_span("day107-smoke-probe") as span:
        span.set_attribute("smoke", True)
        span.set_attribute("openinference.span.kind", "CHAIN")
    flush_traces()
    print("[phoenix_otel] smoke span exported")
    print(f"[phoenix_otel] 打开 {printable['PHOENIX_ENDPOINT'].replace('/v1/traces', '')}")
    print(f"               项目: {printable['PHOENIX_PROJECT_NAME']}")


if __name__ == "__main__":
    _smoke_probe()

