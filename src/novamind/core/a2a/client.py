"""A2A Client — call remote NovaMind agents."""
import logging
from typing import Dict, Optional

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

logger = logging.getLogger("core.a2a.client")


class A2AClient:
    """A2A client for calling remote agents."""

    def __init__(self, base_url: str = "http://localhost:8000", timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def get_agent_card(self) -> Dict:
        """Fetch remote agent card."""
        if not REQUESTS_AVAILABLE:
            return {"error": "requests not installed"}
        try:
            r = requests.get(f"{self.base_url}/.well-known/agent.json", timeout=self.timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            return {"error": str(e)}

    def send_task(self, skill: str, text: str,
                  filename: str = "code.py") -> Dict:
        """Send a task to remote agent."""
        if not REQUESTS_AVAILABLE:
            return {"error": "requests not installed"}
        try:
            r = requests.post(
                f"{self.base_url}/tasks/send",
                json={"skill": skill, "text": text, "filename": filename},
                timeout=self.timeout,
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            return {"error": str(e)}

    def get_task(self, task_id: str) -> Dict:
        """Get task result by ID."""
        if not REQUESTS_AVAILABLE:
            return {"error": "requests not installed"}
        try:
            r = requests.get(f"{self.base_url}/tasks/{task_id}", timeout=self.timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            return {"error": str(e)}

    def health(self) -> Dict:
        """Check server health."""
        if not REQUESTS_AVAILABLE:
            return {"error": "requests not installed"}
        try:
            r = requests.get(f"{self.base_url}/health", timeout=self.timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            return {"error": str(e)}


__all__ = ["A2AClient"]
