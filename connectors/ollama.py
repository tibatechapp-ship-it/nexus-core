from .base import BaseConnector
import httpx
import os

class OllamaConnector(BaseConnector):
    BASE_URL = "http://localhost:11434"

    def default_model(self) -> str: return "qwen2.5-coder:7b-instruct-q4_K_M"

    def _base_url(self) -> str:
        """Resolve the Ollama host at call time (no env read at import)."""
        return os.getenv("OLLAMA_HOST", self.BASE_URL)

    async def generate(self, prompt: str, system_prompt: str = "") -> dict:
        payload = {"model": self.model, "prompt": prompt, "stream": False,
                   "options": {"temperature": 0.7, "num_predict": 4000}}
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                r = await client.post(f"{self._base_url()}/api/generate", json=payload)
                r.raise_for_status()
                return {"ok": True, "reply": r.json().get("response", "")}
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}
