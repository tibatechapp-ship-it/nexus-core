"""Redis Client - Cache, Pub/Sub, Streams."""
import asyncio
import json
import logging
import time
import hashlib
from typing import Optional, Dict, List, Any

try:
    import redis.asyncio as aioredis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

logger = logging.getLogger("RedisClient")


class RedisClient:
    """Wrapper لـ Redis مع fallback in-memory."""
    
    def __init__(self, url: str = "redis://localhost:6379"):
        self.url = url
        self.client = None
        self.available = False
        self.fallback_cache = {}  # in-memory fallback
    
    async def connect(self) -> bool:
        """يحاول الاتصال بـ Redis."""
        if not REDIS_AVAILABLE:
            logger.warning("redis package not installed, using fallback")
            return False
        
        try:
            self.client = aioredis.from_url(
                self.url,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=2,
            )
            await self.client.ping()
            self.available = True
            logger.info("Redis connected")
            return True
        except Exception as e:
            logger.warning(f"Redis not available: {e}")
            self.available = False
            return False
    
    async def close(self):
        if self.client:
            await self.client.close()
    
    def _hash(self, text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()[:16]
    
    async def get(self, key: str) -> Optional[str]:
        """يقرأ قيمة."""
        if self.available and self.client:
            try:
                return await self.client.get(key)
            except Exception:
                return self.fallback_cache.get(key)
        return self.fallback_cache.get(key)
    
    async def set(self, key: str, value: str, ttl: int = 3600):
        """يحفظ قيمة مع TTL."""
        if self.available and self.client:
            try:
                await self.client.setex(key, ttl, value)
                return
            except Exception:
                pass
        self.fallback_cache[key] = value
    
    async def cache_response(self, prompt: str, response: str, ttl: int = 86400):
        """يحفظ رد LLM."""
        key = f"llm:cache:{self._hash(prompt)}"
        await self.set(key, response, ttl)
    
    async def get_cached_response(self, prompt: str) -> Optional[str]:
        """يجلب رد LLM مخزّن."""
        key = f"llm:cache:{self._hash(prompt)}"
        return await self.get(key)
    
    async def publish(self, channel: str, message: Dict):
        """ينشر رسالة."""
        if self.available and self.client:
            try:
                await self.client.publish(channel, json.dumps(message))
            except Exception:
                pass
    
    async def push_mission(self, mission: Dict):
        """يضيف مهمة إلى queue."""
        if self.available and self.client:
            try:
                await self.client.xadd("novamind:missions", mission)
                return
            except Exception:
                pass
    
    async def get_stats(self) -> Dict[str, Any]:
        """إحصائيات Redis."""
        if not self.available or not self.client:
            return {"available": False, "fallback_size": len(self.fallback_cache)}
        
        try:
            info = await self.client.info("memory")
            return {
                "available": True,
                "used_memory_human": info.get("used_memory_human", "?"),
                "connected_clients": (await self.client.info("clients")).get("connected_clients", 0),
            }
        except Exception:
            return {"available": False}


# Singleton
_redis_client: Optional[RedisClient] = None


async def get_redis(url: str = "redis://localhost:6379") -> RedisClient:
    """يحصل على Redis client (singleton)."""
    global _redis_client
    if _redis_client is None:
        _redis_client = RedisClient(url)
        await _redis_client.connect()
    return _redis_client
