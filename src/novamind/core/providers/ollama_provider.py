import os
import json
import httpx


class OllamaProvider:
    """مزود التشغيل المحلي للنماذج بدون إنترنت عبر Ollama"""

    def __init__(self, model_name: str = "qwen2.5:0.5b", priority: int = 1):
        self.name = f"ollama-{model_name}"
        self.model_name = model_name
        self.priority = priority
        self.base_url = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=3.0, read=15.0, write=10.0, pool=3.0)
        )

    async def close(self):
        await self._client.aclose()

    async def generate(self, prompt: str, system_prompt: str = "") -> str:
        url = f"{self.base_url}/api/generate"
        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.2,
                "num_ctx": 4096,
            },
        }
        if system_prompt:
            payload["system"] = system_prompt

        response = await self._client.post(url, json=payload)
        response.raise_for_status()

        try:
            data = response.json()
        except json.JSONDecodeError:
            raise RuntimeError(f"رد غير صالح من Ollama: {response.text[:200]}")

        result = data.get("response", "")
        if not result:
            raise RuntimeError("Ollama أرجع رداً فارغاً")
        return result
