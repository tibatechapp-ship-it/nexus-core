from abc import ABC, abstractmethod
from typing import Dict, Any, Optional

class BaseConnector(ABC):
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None) -> None:
        self.api_key = api_key
        self.model = model or self.default_model()

    @abstractmethod
    def default_model(self) -> str:
        pass

    @abstractmethod
    async def generate(self, prompt: str, system_prompt: str = "") -> Dict[str, Any]:
        pass

    async def test_connection(self) -> Dict[str, Any]:
        try:
            res = await self.generate("Reply with one word: OK")
            return {"ok": res.get("ok", False), "message": res.get("reply", res.get("error", ""))[:100]}
        except Exception as e:
            return {"ok": False, "message": str(e)}
