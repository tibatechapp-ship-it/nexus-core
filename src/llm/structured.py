"""Structured Output generation using Ollama's native JSON Schema support."""
import json
import httpx
from typing import Any, Dict

DEFAULT_MODEL = "sam860/qwen3:1.7b-Q4_K_XL"
OLLAMA_URL = "http://127.0.0.1:11434/api/generate"

async def generate_json(
    prompt: str,
    schema: Dict[str, Any],
    model: str = DEFAULT_MODEL,
    timeout: float = 120.0,
    base_url: str = OLLAMA_URL,
) -> Dict[str, Any]:
    """Generate strictly formatted JSON matching the provided schema.
    
    Uses Ollama's `format` parameter which enforces the JSON schema at the
    token generation level. This prevents the model from outputting markdown
    fences or invalid fields, eliminating the need for retries.
    """
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": schema,  # Native constrained decoding
        "options": {
            "temperature": 0.1,  # Low temp for structured tasks
            "num_predict": 1000,
        }
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(base_url, json=payload)
        r.raise_for_status()
        data = r.json()
        raw_reply = data.get("response", "")

    try:
        return json.loads(raw_reply)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Model returned invalid JSON despite schema: {raw_reply[:200]}"
        ) from e
