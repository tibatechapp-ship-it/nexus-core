"""Compatibility paths must delegate to the single canonical execution layer."""
from __future__ import annotations

import asyncio
from unittest.mock import patch


def test_hive_pipeline_is_canonical_facade() -> None:
    from novamind.core.hive.factory import pipeline as hive_pipeline
    from novamind.factory import pipeline as canonical_pipeline

    assert hive_pipeline.run_pipeline is canonical_pipeline.run_pipeline
    assert hive_pipeline.run_pipeline_sync is canonical_pipeline.run_pipeline_sync
    assert hive_pipeline.PIPELINES is canonical_pipeline.PIPELINES
    assert hive_pipeline.PipelineContext is canonical_pipeline.PipelineContext


def test_hive_executor_delegates_to_canonical_executor() -> None:
    from novamind.core.hive.factory import executor as hive_executor
    from novamind.factory import executor as canonical_executor

    async def expected(*args, **kwargs):
        return {"success": True, "agent": "coder", "output": {"text": "ok"}}

    with patch.object(canonical_executor, "execute_agent", side_effect=expected) as run:
        result = asyncio.run(hive_executor.execute_agent("coder", "task", llm_call=None))

    assert result["success"] is True
    run.assert_awaited_once()


def test_hive_executor_preserves_legacy_provider_patching() -> None:
    from novamind.core.hive.factory import executor as hive_executor
    from novamind.factory import executor as canonical_executor

    async def fake_llm(prompt):
        return {"text": "Mocked Success", "tokens": 1}

    with (
        patch.object(hive_executor, "is_llm_available", return_value=True),
        patch.object(hive_executor, "make_llm_call", return_value=fake_llm),
        patch.object(canonical_executor, "execute_agent", return_value=None) as run,
    ):
        # The canonical call is async; AsyncMock-like mock returns must be awaitable.
        async def delegated(*args, **kwargs):
            return {"success": True, "agent": "coder"}

        run.side_effect = delegated
        result = asyncio.run(hive_executor.execute_agent("coder", "task"))

    assert result["success"] is True
    assert run.await_args.kwargs["llm_call"] is fake_llm


def test_canonical_executor_fails_when_no_real_provider_is_configured() -> None:
    from novamind.factory import executor as canonical_executor

    with patch.object(canonical_executor, "is_llm_available", return_value=False):
        result = asyncio.run(canonical_executor.execute_agent("coder", "write a parser"))

    assert result["success"] is False
    assert result["status"] == "llm_unavailable"
    assert "no simulated output" in result["error"]


def test_canonical_executor_rejects_explicit_simulated_provider_output() -> None:
    from novamind.factory.executor import execute_agent

    async def simulated_llm(_prompt):
        return {
            "ok": True,
            "simulated": True,
            "text": "synthetic successful response",
            "provider": "mock",
            "tokens": 0,
        }

    result = asyncio.run(
        execute_agent("coder", "write a parser", llm_call=simulated_llm)
    )

    assert result["success"] is False
    assert result["status"] == "simulated_provider_rejected"


def test_canonical_executor_retries_provider_failures_with_bounded_attempts() -> None:
    from novamind.factory.executor import execute_agent

    calls = {"count": 0}

    async def unavailable(_prompt):
        calls["count"] += 1
        return {
            "ok": False,
            "simulated": False,
            "text": "",
            "provider": "groq_01",
            "error": "temporary upstream failure",
        }

    result = asyncio.run(
        execute_agent(
            "coder",
            "write a parser",
            llm_call=unavailable,
            max_retries=2,
        )
    )

    assert result["success"] is False
    assert result["status"] == "llm_provider_error"
    assert result["attempts"] == 3
    assert calls["count"] == 3


def test_canonical_executor_rejects_unverified_provider_metadata() -> None:
    from novamind.factory.executor import execute_agent

    async def incomplete_response(_prompt):
        return {
            "text": "plausible but unverified output",
            "provider": "router",
            "model": "unknown",
        }

    result = asyncio.run(
        execute_agent("coder", "write a parser", llm_call=incomplete_response)
    )

    assert result["success"] is False
    assert result["status"] == "unverified_provider_response"
