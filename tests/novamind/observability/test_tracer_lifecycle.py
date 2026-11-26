"""Lifecycle regression tests for the OpenTelemetry tracer."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from novamind.observability import tracer


def test_console_exporter_uses_synchronous_span_processor(monkeypatch) -> None:
    """Console export must not leave a worker writing after captured stdout closes."""
    processors: list[Any] = []

    class FakeProcessor:
        def __init__(self, exporter: object) -> None:
            self.exporter = exporter

    class FakeProvider:
        def __init__(self, *, resource: object) -> None:
            self.resource = resource
            self.stopped = False

        def add_span_processor(self, processor: object) -> None:
            processors.append(processor)

        def shutdown(self) -> None:
            self.stopped = True

    class FakeTracer:
        def start_span(self, name: str) -> object:
            return object()

    provider: FakeProvider | None = None

    def make_provider(*, resource: object) -> FakeProvider:
        nonlocal provider
        provider = FakeProvider(resource=resource)
        return provider

    monkeypatch.setattr(tracer, "_OTEL_AVAILABLE", True)
    monkeypatch.setattr(tracer, "_initialized", False)
    monkeypatch.setattr(tracer, "_tracer", None)
    monkeypatch.setattr(
        tracer, "get_config",
        lambda: SimpleNamespace(
            tracing_enabled=True,
            service_name="test-service",
            service_version="1.0",
            exporter="console",
            otlp_endpoint="http://localhost:4317",
        ),
    )
    monkeypatch.setattr(tracer, "TracerProvider", make_provider)
    monkeypatch.setattr(tracer, "ConsoleSpanExporter", lambda: object())
    monkeypatch.setattr(tracer, "SimpleSpanProcessor", FakeProcessor)
    monkeypatch.setattr(tracer, "BatchSpanProcessor", lambda exporter: object())
    monkeypatch.setattr(tracer.otel_trace, "set_tracer_provider", lambda value: None)
    monkeypatch.setattr(tracer.otel_trace, "get_tracer_provider", lambda: provider)
    monkeypatch.setattr(tracer.otel_trace, "get_tracer", lambda *args: FakeTracer())

    tracer._init_otel()

    assert len(processors) == 1
    assert isinstance(processors[0], FakeProcessor)
    tracer.shutdown()
    assert provider is not None and provider.stopped


def test_shutdown_is_idempotent_after_provider_is_stopped(monkeypatch) -> None:
    """A second shutdown must not attempt to close an already released provider."""
    class FakeProvider:
        def __init__(self) -> None:
            self.shutdown_calls = 0

        def shutdown(self) -> None:
            self.shutdown_calls += 1

    provider = FakeProvider()
    monkeypatch.setattr(tracer, "_OTEL_AVAILABLE", True)
    monkeypatch.setattr(tracer, "_initialized", True)
    monkeypatch.setattr(tracer, "_tracer", object())
    monkeypatch.setattr(tracer.otel_trace, "get_tracer_provider", lambda: provider)

    tracer.shutdown()
    tracer.shutdown()

    assert provider.shutdown_calls == 1
    assert tracer._tracer is None
    assert tracer._initialized is False
