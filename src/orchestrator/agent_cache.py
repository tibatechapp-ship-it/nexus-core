"""Simple, private and collision-resistant agent result cache."""
import hashlib
import json
import os
import tempfile
import time
from typing import Any


_CACHE_DIR = os.path.expanduser("~/.nexus/data/agent_cache")
os.makedirs(_CACHE_DIR, mode=0o700, exist_ok=True)
_TTL = 21600  # 6 hours


def _key(agent: str, prompt: str) -> str:
    """Return a path-safe key over the complete, unambiguous cache identity."""
    identity = json.dumps(
        [agent, prompt], ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(identity).hexdigest()


def _path(agent: str, prompt: str) -> str:
    return os.path.join(_CACHE_DIR, _key(agent, prompt) + ".json")


def get(agent: str, prompt: str) -> Any:
    """Fetch a cache entry; malformed, expired, or symlinked entries are misses."""
    path = _path(agent, prompt)
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
        with os.fdopen(fd, encoding="utf-8") as stream:
            data = json.load(stream)
        if not isinstance(data, dict):
            return None
        timestamp = data.get("ts")
        if not isinstance(timestamp, (int, float)):
            return None
        if time.time() - timestamp > _TTL:
            os.remove(path)
            return None
        return data.get("result")
    except Exception:
        return None


def set(agent: str, prompt: str, result: Any) -> None:
    """Atomically persist a cache entry with owner-only file permissions."""
    path = _path(agent, prompt)
    temporary_path: str | None = None
    try:
        os.makedirs(_CACHE_DIR, mode=0o700, exist_ok=True)
        fd, temporary_path = tempfile.mkstemp(
            prefix=".cache-", suffix=".tmp", dir=_CACHE_DIR
        )
        # mkstemp creates mode 0600 on POSIX; keep that private mode explicit.
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(
                {"ts": time.time(), "result": result},
                stream,
                ensure_ascii=False,
                default=str,
            )
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    except Exception:
        # Cache failures must never break agent execution.
        pass
    finally:
        if temporary_path is not None:
            try:
                os.unlink(temporary_path)
            except OSError:
                pass
