from .base import BaseConnector
import httpx

class DeepSeekConnector(BaseConnector):
    BASE_URL = "https://api.deepseek.com/v1"
    def default_model(self) -> str: return "deepseek-chat"

    async def generate(self, prompt: str, system_prompt: str = "") -> dict:
        if not self.api_key:
            return {"ok": False, "error": "Missing DeepSeek API Key"}
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        messages = [{"role": "system", "content": system_prompt}] if system_prompt else []
        messages.append({"role": "user", "content": prompt})
        payload = {"model": self.model, "messages": messages, "max_tokens": 2000}
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                r = await client.post(f"{self.BASE_URL}/chat/completions", json=payload, headers=headers)
                r.raise_for_status()
                return {"ok": True, "reply": r.json()["choices"][0]["message"]["content"]}
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}
