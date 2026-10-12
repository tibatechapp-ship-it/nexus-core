"""Embeddings — Gemini multi-model fallback."""
import os, logging
from typing import List, Optional
import httpx

logger = logging.getLogger("Embeddings")
EMBEDDING_DIM = 768

GEMINI_API_TPL = (
    "https://generativelanguage.googleapis.com/v1beta/"
    "models/{model}:embedContent?key={key}"
)

# جرّب بالترتيب
GEMINI_MODELS = [
    "gemini-embedding-001",
    "text-embedding-005",
    "text-embedding-004",
    "embedding-001",
]

OLLAMA_API = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/") + "/api/embeddings"
OLLAMA_MODEL = "nomic-embed-text"


def _gemini_key():
    for i in range(1, 21):
        k = os.getenv(f"GEMINI_API_KEY_{i}", "").strip()
        if k.startswith("AIza") or k.startswith("AQ."):
            return k
    return os.getenv("GEMINI_API_KEY", "").strip() or None


async def embed(text: str):
    if not text or not text.strip():
        return None
    text = text[:8000]

    key = _gemini_key()
    if key:
        async with httpx.AsyncClient(timeout=20.0) as client:
            for model in GEMINI_MODELS:
                try:
                    url = GEMINI_API_TPL.format(model=model, key=key)
                    r = await client.post(url, json={
                        "content": {"parts": [{"text": text}]}
                    })
                    if r.status_code == 200:
                        vals = r.json().get("embedding", {}).get("values")
                        if vals:
                            logger.info(f"Gemini OK: {model} dim={len(vals)}")
                            return vals
                    elif r.status_code != 404:
                        logger.warning(f"{model} HTTP {r.status_code}: {r.text[:80]}")
                except Exception as e:
                    logger.debug(f"{model} err: {e}")

    # Ollama fallback
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(OLLAMA_API,
                json={"model": OLLAMA_MODEL, "prompt": text})
            if r.status_code == 200:
                return r.json().get("embedding")
    except Exception:
        pass

    return None


async def embed_batch(texts: List[str]):
    return [await embed(t) for t in texts]


def load_dotenv_manual():
    from pathlib import Path
    env_file = Path("/public/.env")
    if not env_file.exists():
        return 0
    loaded = 0
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v
                loaded += 1
    return loaded
