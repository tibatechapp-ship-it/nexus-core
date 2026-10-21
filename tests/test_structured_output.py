"""Test native structured JSON generation with Ollama.

This is a live integration test — it requires a local Ollama server.
On CI (GitHub Actions), Ollama is not available, so the test skips.
To force it locally when Ollama is not running, set NEXUS_OLLAMA_LIVE=1
(but it will still fail — the env is only for demos).
"""
import os

import httpx
import pytest

from src.llm.structured import generate_json


def _ollama_reachable() -> bool:
    """Probe the local Ollama server. Returns True if /api/version responds."""
    try:
        r = httpx.get("http://127.0.0.1:11434/api/version", timeout=1.0)
        return r.status_code == 200
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _ollama_reachable() and os.environ.get("NEXUS_OLLAMA_LIVE") != "1",
    reason=(
        "Ollama not reachable at 127.0.0.1:11434. "
        "This is a live integration test — skipped on CI. "
        "Set NEXUS_OLLAMA_LIVE=1 to force (requires running server)."
    ),
)


SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["approve", "reject"]},
        "score": {"type": "integer", "minimum": 0, "maximum": 100},
    },
    "required": ["verdict", "score"],
    "additionalProperties": False,
}


@pytest.mark.asyncio
async def test_generate_json_real_ollama():
    """Test structured output with the real local Ollama server."""
    prompt = (
        "Evaluate this deployment: We have 100% test coverage and zero bugs. "
        "Should we deploy?"
    )
    result = await generate_json(prompt, SCHEMA)

    # 1. Must be a dict
    assert isinstance(result, dict), f"Expected dict, got {type(result)}"

    # 2. Must match the schema exactly
    assert "verdict" in result, "Missing 'verdict' key"
    assert "score" in result, "Missing 'score' key"

    # 3. Enforce enum
    assert result["verdict"] in ("approve", "reject"), (
        f"Invalid verdict: {result['verdict']}"
    )

    # 4. Enforce integer bounds
    assert isinstance(result["score"], int), (
        f"Score must be int, got {type(result['score'])}"
    )
    assert 0 <= result["score"] <= 100, f"Score out of bounds: {result['score']}"
