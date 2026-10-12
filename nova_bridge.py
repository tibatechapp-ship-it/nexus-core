"""
NovaBridge — يربط FastAPI بـ nova.py الموجود.
يستدعي nova.py كخدمة، ويعيد الردود.
"""
import sys
import asyncio
import logging
from pathlib import Path
from typing import Dict, Optional
import os

logger = logging.getLogger("platform.nova_bridge")

# Add nova.py directory to path
NOVA_DIR = Path(os.environ.get("NOVAMIND_HOME", str(Path(__file__).resolve().parent.parent)))
if str(NOVA_DIR) not in sys.path:
    sys.path.insert(0, str(NOVA_DIR))


class NovaBridge:
    """Bridge between FastAPI and NovaMind agent."""
    
    def __init__(self):
        self.available = False
        self._check()
    
    def _check(self):
        """Check if nova components are importable."""
        try:
            from core.providers.orchestrator import orchestrator
            self.available = True
            logger.info("✅ NovaMind orchestrator available")
        except ImportError:
            logger.warning("⚠️  NovaMind not available, using mock")
            self.available = False
    
    async def chat(self, message: str, history: Optional[list] = None) -> Dict:
        """Send chat message to NovaMind."""
        if not self.available:
            return {
                "ok": True,
                "response": f"[Demo Mode] أنت قلت: {message}",
                "provider": "mock",
            }
        
        try:
            from core.providers.orchestrator import orchestrator
            
            system = """أنت NovaMind — وكيل ذكي.
تحدث بالعربية بأسلوب ودود ومهني."""
            
            # Run in executor to avoid blocking
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: orchestrator.call(
                    message, task="smart", system=system, max_tokens=1500,
                )
            )
            
            if result.get("ok"):
                return {
                    "ok": True,
                    "response": result["text"],
                    "provider": result.get("provider", ""),
                }
            return {
                "ok": False,
                "error": result.get("error", "LLM failed")[:200],
            }
        except Exception as e:
            logger.error(f"chat error: {e}")
            return {"ok": False, "error": str(e)[:200]}
    
    async def get_status(self) -> Dict:
        """Get NovaMind status."""
        status = {
            "available": self.available,
            "tools": 0,
            "repos": 0,
            "learning": 0,
        }
        if not self.available:
            return status
        try:
            from tools import registry
            status["tools"] = len(registry.list_tools())
        except Exception:
            pass
        try:
            from core.repo_manager import repo_manager
            st = repo_manager.stats()
            status["repos"] = st.get("enabled_repos", 0)
        except Exception:
            pass
        try:
            from core.learning_loop import learning_loop
            st = learning_loop.stats()
            status["learning"] = st.get("total_learned", 0)
        except Exception:
            pass
        return status


nova_bridge = NovaBridge()
