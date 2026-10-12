"""Tests for observability.metrics module."""
from __future__ import annotations

from novamind.observability import metrics


class TestMetrics:

    def setup_method(self) -> None:
        metrics.reset()

    def test_snapshot_initial(self) -> None:
        snap = metrics.snapshot()
        assert "available" in snap
        assert "metrics_count" in snap

    def test_record_agent_call(self) -> None:
        metrics.record_agent_call("coder", "success")
        metrics.record_agent_call("coder", "error")
        body, ct = metrics.export_prometheus()
        assert b"novamind_agent_calls_total" in body

    def test_record_llm_tokens(self) -> None:
        metrics.record_llm_tokens("zai", "glm-4", input_tokens=100, output_tokens=50)
        body, _ = metrics.export_prometheus()
        assert b"novamind_llm_tokens_total" in body

    def test_record_cost(self) -> None:
        metrics.record_cost("openai", 0.001)
        body, _ = metrics.export_prometheus()
        assert b"novamind_cost_usd_total" in body

    def test_record_agent_error(self) -> None:
        metrics.record_agent_error("coder", "ValueError")
        body, _ = metrics.export_prometheus()
        assert b"novamind_agent_errors_total" in body

    def test_time_pipeline_context(self) -> None:
        import time
        with metrics.time_pipeline("test_pipeline"):
            time.sleep(0.01)
        body, _ = metrics.export_prometheus()
        assert b"novamind_pipeline_duration_seconds" in body

    def test_active_agents_gauge(self) -> None:
        metrics.set_active_agents(5)
        body, _ = metrics.export_prometheus()
        assert b"novamind_active_agents" in body

    def test_export_returns_bytes_and_content_type(self) -> None:
        body, ct = metrics.export_prometheus()
        assert isinstance(body, bytes)
        assert isinstance(ct, str)
