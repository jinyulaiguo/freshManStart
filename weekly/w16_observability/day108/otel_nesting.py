"""
Day 108 · 手写 OTel 嵌套 Span 包装（装饰器 + 上下文管理器）

语义对齐课纲「手写 Span 包装类」，但底层走真实 TracerProvider，
导出到本地 Phoenix——不再维护与 OTel 平行的第二套运行时。
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager, contextmanager
from functools import wraps
from typing import Any, AsyncIterator, Callable, Iterator, TypeVar

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

F = TypeVar("F", bound=Callable[..., Any])

TRACER_NAME = "freshman.w16.day108"

# 测试可注入 TracerProvider，避免全局 set_tracer_provider 不可覆盖
_test_provider: trace.TracerProvider | None = None


def set_test_tracer_provider(provider: trace.TracerProvider | None) -> None:
    global _test_provider
    _test_provider = provider


def get_tracer():
    if _test_provider is not None:
        return _test_provider.get_tracer(TRACER_NAME)
    return trace.get_tracer(TRACER_NAME)


@contextmanager
def span(name: str, *, kind: str | None = None, **attributes: Any) -> Iterator[Any]:
    """同步嵌套 Span；kind 写入 openinference.span.kind。"""
    attrs = dict(attributes)
    if kind:
        attrs["openinference.span.kind"] = kind
    with get_tracer().start_as_current_span(name) as otel_span:
        for k, v in attrs.items():
            if v is not None:
                otel_span.set_attribute(k, v)
        t0 = time.monotonic()
        try:
            yield otel_span
        except BaseException as exc:
            otel_span.record_exception(exc)
            otel_span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise
        finally:
            otel_span.set_attribute(
                "duration_ms", round((time.monotonic() - t0) * 1000, 3)
            )


@asynccontextmanager
async def aspan(
    name: str, *, kind: str | None = None, **attributes: Any
) -> AsyncIterator[Any]:
    """异步嵌套 Span。"""
    attrs = dict(attributes)
    if kind:
        attrs["openinference.span.kind"] = kind
    with get_tracer().start_as_current_span(name) as otel_span:
        for k, v in attrs.items():
            if v is not None:
                otel_span.set_attribute(k, v)
        t0 = time.monotonic()
        try:
            yield otel_span
        except BaseException as exc:
            otel_span.record_exception(exc)
            otel_span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise
        finally:
            otel_span.set_attribute(
                "duration_ms", round((time.monotonic() - t0) * 1000, 3)
            )


def traced(name: str | None = None, *, kind: str | None = None, **attributes: Any):
    """装饰同步/异步函数为单个 Span。"""

    def decorator(fn: F) -> F:
        span_name = name or fn.__name__
        import asyncio

        if asyncio.iscoroutinefunction(fn):

            @wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                async with aspan(span_name, kind=kind, **attributes):
                    return await fn(*args, **kwargs)

            return async_wrapper  # type: ignore[return-value]

        @wraps(fn)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            with span(span_name, kind=kind, **attributes):
                return fn(*args, **kwargs)

        return sync_wrapper  # type: ignore[return-value]

    return decorator


def add_event(name: str, **attributes: Any) -> None:
    current = trace.get_current_span()
    if not current or not current.is_recording():
        raise RuntimeError("add_event 必须在活跃 Span 内调用")
    current.add_event(name, attributes=dict(attributes))
