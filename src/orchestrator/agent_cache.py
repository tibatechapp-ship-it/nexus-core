"""Simple agent result cache."""
import os
import hashlib
import json
import time


_CACHE_DIR = os.path.expanduser("~/.nexus/data/agent_cache")
os.makedirs(_CACHE_DIR, exist_ok=True)
_TTL = 21600  # ساعة


def _key(agent: str, prompt: str) -> str:
    h = hashlib.md5(f"{agent}::{prompt[:200]}".encode()).hexdigest()[:16]
    return f"{agent}_{h}"


def get(agent: str, prompt: str):
    """جلب من الكاش."""
    path = os.path.join(_CACHE_DIR, _key(agent, prompt) + ".json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if time.time() - data.get("ts", 0) > _TTL:
            os.remove(path)
            return None
        return data.get("result")
    except Exception:
        return None


def set(agent: str, prompt: str, result):
    """حفظ في الكاش."""
    path = os.path.join(_CACHE_DIR, _key(agent, prompt) + ".json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"ts": time.time(), "result": result},
                      f, ensure_ascii=False, default=str)
    except Exception:
        pass
