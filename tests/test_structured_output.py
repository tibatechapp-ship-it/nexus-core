"""Test native structured JSON generation with Ollama."""
import pytest
from src.llm.structured import generate_json

SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["approve", "reject"]},
        "score": {"type": "integer", "minimum": 0, "maximum": 100}
    },
    "required": ["verdict", "score"],
    "additionalProperties": False
}

@pytest.mark.asyncio
async def test_generate_json_real_ollama():
    """Test structured output with the real local Ollama server."""
    prompt = "Evaluate this deployment: We have 100% test coverage and zero bugs. Should we deploy?"
    
    result = await generate_json(prompt, SCHEMA)
    
    # 1. Must be a dict
    assert isinstance(result, dict), f"Expected dict, got {type(result)}"
    
    # 2. Must match the schema exactly
    assert "verdict" in result, "Missing 'verdict' key"
    assert "score" in result, "Missing 'score' key"
    
    # 3. Enforce enum
    assert result["verdict"] in ("approve", "reject"), f"Invalid verdict: {result['verdict']}"
    
    # 4. Enforce integer bounds
    assert isinstance(result["score"], int), f"Score must be int, got {type(result['score'])}"
    assert 0 <= result["score"] <= 100, f"Score out of bounds: {result['score']}"
