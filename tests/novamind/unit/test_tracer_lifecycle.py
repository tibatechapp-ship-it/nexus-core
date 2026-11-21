"""Regression tests for safe, one-shot OpenTelemetry exporter lifecycle."""
from types import SimpleNamespace

from novamind.observability import tracer


def test_console_exporter_uses_stable_stdout_and_shutdown_flushes(monkeypatch):
    captured = {}

    class FakeTracer:
        def start_span(self, name):
            return SimpleNamespace(
                set_attribute=lambda *args: None,
                end=lambda: captured.setdefault("span_ended", True),
            )

    class FakeProvider:
        def __init__(self, resource):
            captured["resource"] = resource
            captured["processors"] = []

        def add_span_processor(self, processor):
            captured["processors"].append(processor)

        def force_flush(self, timeout_millis):
            captured["flush_timeout"] = timeout_millis
            return True

        def shutdown(self):
            captured["shutdown"] = True

    class FakeTrace:
        def set_tracer_provider(self, provider):
            captured["provider"] = provider

        def get_tracer(self, *args):
            return FakeTracer()

        def get_tracer_provider(self):
            return captured["provider"]

    class FakeExporter:
        def __init__(self, out):
            captured["exporter_stream"] = out

    class FakeProcessor:
        def __init__(self, exporter):
            captured["exporter"] = exporter

    monkeypatch.setattr(tracer, "_OTEL_AVAILABLE", True)
    monkeypatch.setattr(tracer, "_initialized", False)
    monkeypatch.setattr(tracer, "_tracer", None)
    monkeypatch.setattr(tracer, "otel_trace", FakeTrace())
    monkeypatch.setattr(tracer, "Resource", SimpleNamespace(create=lambda value: value))
    monkeypatch.setattr(tracer, "TracerProvider", FakeProvider)
    monkeypatch.setattr(tracer, "BatchSpanProcessor", FakeProcessor)
    monkeypatch.setattr(tracer, "ConsoleSpanExporter", FakeExporter)
    monkeypatch.setattr(
        tracer,
        "get_config",
        lambda: SimpleNamespace(
            tracing_enabled=True,
            service_name="test-service",
            service_version="test",
            exporter="console",
            otlp_endpoint="",
        ),
    )

    tracer._init_otel()

    assert captured["exporter_stream"] is not None
    assert captured["exporter_stream"] is getattr(__import__("sys"), "__stdout__")
    assert len(captured["processors"]) == 1

    with tracer.start_span("lifecycle.test"):
        pass

    tracer.shutdown()
    assert captured["flush_timeout"] == 5000
    assert captured["shutdown"] is True
    assert captured["span_ended"] is True
    assert tracer._tracer is None
    assert tracer._initialized is True

    # Shutdown is idempotent and does not attempt to re-register the provider.
    tracer.shutdown()
    assert captured["shutdown"] is True


def test_console_exporter_is_skipped_when_stable_stdout_is_closed(monkeypatch):
    captured = {}

    class ClosedStream:
        closed = True

    class FakeProvider:
        def __init__(self, resource):
            captured["provider_created"] = True
            self.processors = []

        def add_span_processor(self, processor):
            self.processors.append(processor)

    monkeypatch.setattr(tracer, "_OTEL_AVAILABLE", True)
    monkeypatch.setattr(tracer, "_initialized", False)
    monkeypatch.setattr(tracer, "_tracer", None)
    monkeypatch.setattr(tracer.sys, "__stdout__", ClosedStream())
    monkeypatch.setattr(tracer, "Resource", SimpleNamespace(create=lambda value: value))
    monkeypatch.setattr(tracer, "TracerProvider", FakeProvider)
    monkeypatch.setattr(
        tracer,
        "get_config",
        lambda: SimpleNamespace(
            tracing_enabled=True,
            service_name="test-service",
            service_version="test",
            exporter="console",
            otlp_endpoint="",
        ),
    )

    tracer._init_otel()

    assert captured["provider_created"] is True
    assert tracer._initialized is True
    assert tracer._tracer is not None
    assert tracer.otel_trace.get_tracer_provider().processors == []
