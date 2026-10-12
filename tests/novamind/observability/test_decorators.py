"""Tests for observability.decorators module."""
from __future__ import annotations

import pytest

from novamind.observability import metrics
from novamind.observability.decorators import metered, timed, traced


class TestDecorators:

    def setup_method(self) -> None:
        metrics.reset()

    def test_traced_preserves_result(self) -> None:
        @traced("test.operation")
        def add(a: int, b: int) -> int:
            return a + b

        assert add(2, 3) == 5

    def test_traced_preserves_name(self) -> None:
        @traced("test.operation")
        def my_function() -> None:
            pass

        assert my_function.__name__ == "my_function"

    def test_metered_records_success(self) -> None:
        @metered("agent_calls", agent="test_agent")
        def run() -> str:
            return "ok"

        assert run() == "ok"
        body, _ = metrics.export_prometheus()
        assert b'agent="test_agent"' in body

    def test_metered_records_error(self) -> None:
        @metered("agent_calls", agent="failing_agent")
        def fail() -> None:
            raise ValueError("boom")

        with pytest.raises(ValueError):
            fail()
        body, _ = metrics.export_prometheus()
        assert b"novamind_agent_errors_total" in body

    def test_timed_returns_result(self) -> None:
        @timed
        def slow() -> int:
            return 42

        assert slow() == 42

    def test_traced_and_metered_combined(self) -> None:
        @traced("test.combined")
        @metered("agent_calls", agent="combined_agent")
        def run(x: int) -> int:
            return x * 2

        assert run(5) == 10
        body, _ = metrics.export_prometheus()
        assert b'agent="combined_agent"' in body
