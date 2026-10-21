#!/usr/bin/env python3
"""
Groq Rotator — uses GroqKeyPool for automatic key rotation.
Handles rate limits, errors, and retries with different keys.
"""
import os
import time
import json
import logging
import urllib.request
import urllib.error
from typing import Dict, Optional, List

logger = logging.getLogger("groq_rotator")

GROQ_API = "https://api.groq.com/openai/v1/chat/completions"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


class GroqRotator:
    """Rotates through 20 Groq keys automatically."""

    def __init__(self, pool=None):
        if pool is None:
            from groq_pool import get_pool
            pool = get_pool()
        self.pool = pool

    def chat(self, prompt: str, system: str = "",
             model: str = "openai/gpt-oss-120b",
             temperature: float = 0.2,
             max_tokens: int = 2048,
             max_attempts: int = 3) -> Dict:
        """
        Call Groq API with automatic key rotation.

        Returns:
            {"ok": True, "text": ..., "provider": "groq-NN", "latency_ms": ...}
            {"ok": False, "error": "..."}
        """
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        tried_keys = set()
        last_error = ""

        for attempt in range(max_attempts):
            key_info = self.pool.get_next_key()

            if not key_info:
                return {
                    "ok": False,
                    "error": "All Groq keys in cooldown",
                    "attempts": attempt,
                }

            if key_info["id"] in tried_keys:
                # Already tried this key, wait for another
                time.sleep(1)
                continue

            tried_keys.add(key_info["id"])

            t0 = time.time()
            try:
                result = self._call_groq(
                    key=key_info["key"],
                    messages=messages,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                latency = int((time.time() - t0) * 1000)

                if result.get("ok"):
                    self.pool.report_success(key_info["id"])
                    logger.info(f"✅ {key_info['id']} ({latency}ms)")
                    return {
                        "ok": True,
                        "text": result["text"],
                        "provider": f"groq-{key_info['id'].split('-')[1]}",
                        "key_id": key_info["id"],
                        "latency_ms": latency,
                        "attempts": attempt + 1,
                    }
                else:
                    err = result.get("error", "unknown")

                    # Rate limit?
                    if "429" in err or "rate" in err.lower():
                        self.pool.report_rate_limit(key_info["id"])
                        logger.warning(f"⏸️  {key_info['id']} rate limited")
                    else:
                        self.pool.report_error(key_info["id"], err, 60)
                        logger.error(f"❌ {key_info['id']}: {err[:80]}")

                    last_error = err
                    # Continue loop → try next key

            except Exception as e:
                last_error = str(e)
                self.pool.report_error(key_info["id"], str(e)[:200], 60)
                logger.error(f"❌ {key_info['id']} exception: {e}")

        return {
            "ok": False,
            "error": f"All attempts failed: {last_error[:100]}",
            "attempts": max_attempts,
        }

    def _call_groq(self, key: str, messages: List[Dict],
                   model: str, temperature: float,
                   max_tokens: int) -> Dict:
        """Raw Groq API call."""
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        req = urllib.request.Request(
            GROQ_API,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                return {"ok": True, "text": text}
        except urllib.error.HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode("utf-8")[:200]
            except Exception:
                pass
            return {"ok": False, "error": f"HTTP {e.code}: {err_body}"}
        except urllib.error.URLError as e:
            return {"ok": False, "error": f"URL: {str(e.reason)[:100]}"}
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}


# ═══ Singleton ═══
_rotator = None


def get_rotator() -> GroqRotator:
    global _rotator
    if _rotator is None:
        _rotator = GroqRotator()
    return _rotator


if __name__ == "__main__":
    import sys
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    try:
        from dotenv import load_dotenv
        load_dotenv("/public/.env")
    except ImportError:
        pass

    print("═" * 60)
    print("  🧪 Groq Rotator Test")
    print("═" * 60)
    print()

    rotator = get_rotator()

    print(f"📊 Pool: {len(rotator.pool.keys)} keys available")
    print()

    # اختبار: 3 استدعاءات متتالية
    for i in range(1, 4):
        print(f"🔍 Call #{i}...")
        result = rotator.chat(
            prompt="Reply with exactly: OK",
            system="You reply with one word only.",
            max_tokens=10,
        )

        if result.get("ok"):
            print(f"   ✅ {result['provider']} ({result['latency_ms']}ms)")
            print(f"   📝 Response: {result['text'][:50]}")
        else:
            print(f"   ❌ {result['error'][:100]}")
        print()

    # Stats
    print("═══ Pool Stats ═══")
    stats = rotator.pool.stats()
    print(f"  Total:      {stats['total_keys']}")
    print(f"  Available:  {stats['available']}")
    print(f"  Cooldown:   {stats['in_cooldown']}")
