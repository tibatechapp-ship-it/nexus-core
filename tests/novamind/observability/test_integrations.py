"""Tests for observability.integrations package."""
from __future__ import annotations

from novamind.observability import metrics
from novamind.observability.integrations import (
    estimate_cost,
    instrument_commander,
    instrument_factory,
    record_llm_call,
)


class TestCostEstimation:

    def test_known_openai_model(self) -> None:
        cost = estimate_cost("openai", "gpt-4", input_tokens=1000, output_tokens=500)
        assert cost > 0

    def test_unknown_model_returns_zero(self) -> None:
        cost = estimate_cost("unknown", "unknown-model", input_tokens=1000, output_tokens=500)
        assert cost == 0.0

    def test_zai_glm4_pricing(self) -> None:
        cost = estimate_cost("zai", "glm-4", input_tokens=1_000_000, output_tokens=0)
        assert cost == 1.0

    def test_custom_pricing_overrides(self) -> None:
        custom = {"test/model": (10.0, 20.0)}
        cost = estimate_cost("test", "model", 1_000_000, 1_000_000, pricing=custom)
        assert cost == 30.0


class TestRecordLLMCall:

    def setup_method(self) -> None:
        metrics.reset()

    def test_record_returns_dict(self) -> None:
        result = record_llm_call("openai", "gpt-4", 100, 50)
        assert isinstance(result, dict)
        assert "input_tokens" in result
        assert "output_tokens" in result
        assert "cost_usd" in result

    def test_record_updates_prometheus(self) -> None:
        record_llm_call("zai", "glm-4", 100, 50)
        body, _ = metrics.export_prometheus()
        assert b"novamind_llm_tokens_total" in body


class TestCommanderInstrumentation:

    def test_commander_gets_instrumented(self) -> None:
        from novamind.commander import Commander
        instrument_commander(Commander)
        assert getattr(Commander, "_observability_instrumented", False)

    def test_commander_still_works(self) -> None:
        from novamind.commander import Commander
        instrument_commander(Commander)
        cmd = Commander()
        pipeline = cmd.choose_pipeline("fix bug")
        assert isinstance(pipeline, str)
        assert len(pipeline) > 0


class TestFactoryInstrumentation:

    def test_factory_gets_instrumented(self) -> None:
        from novamind.agents.factory import factory
        instrument_factory(factory)
        assert getattr(factory, "_observability_instrumented", False)

    def test_factory_still_works(self) -> None:
        from novamind.agents.factory import factory
        instrument_factory(factory)
        agent = factory.get("coder")
        assert agent is not None
