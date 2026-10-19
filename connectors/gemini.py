from .base import BaseConnector
import httpx

class GeminiConnector(BaseConnector):
    def default_model(self) -> str: return "gemini-2.0-flash-exp"

    async def generate(self, prompt: str, system_prompt: str = "") -> dict:
        if not self.api_key:
            return {"ok": False, "error": "Missing Gemini API Key"}
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                r = await client.post(url, json=payload, headers={"Content-Type": "application/json"})
                r.raise_for_status()
                return {"ok": True, "reply": r.json()["candidates"][0]["content"]["parts"][0]["text"]}
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}
