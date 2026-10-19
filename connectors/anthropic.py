from .base import BaseConnector
import httpx

class AnthropicConnector(BaseConnector):
    BASE_URL = "https://api.anthropic.com/v1"
    def default_model(self) -> str: return "claude-3-5-haiku-latest"

    async def generate(self, prompt: str, system_prompt: str = "") -> dict:
        if not self.api_key:
            return {"ok": False, "error": "Missing Anthropic API Key"}
        headers = {"x-api-key": self.api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"}
        payload = {"model": self.model, "max_tokens": 2000, "messages": [{"role": "user", "content": prompt}]}
        if system_prompt:
            payload["system"] = system_prompt
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                r = await client.post(f"{self.BASE_URL}/messages", json=payload, headers=headers)
                r.raise_for_status()
                return {"ok": True, "reply": r.json()["content"][0]["text"]}
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}
