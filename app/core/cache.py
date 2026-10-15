"""Simple cache with optional Redis backend and in-memory fallback."""

from __future__ import annotations

import json
import time
from typing import Any


class Cache:
    def __init__(self, redis_url: str | None = None, default_ttl: int = 300):
        self.default_ttl = default_ttl
        self._mem: dict[str, tuple[float, Any]] = {}
        self._redis = None
        if redis_url:
            try:
                import redis  # type: ignore[import-not-found]

                self._redis = redis.from_url(redis_url, socket_connect_timeout=2)
            except Exception:
                self._redis = None

    def get(self, key: str) -> Any | None:
        if self._redis is not None:
            try:
                raw = self._redis.get(key)
                if raw:
                    return json.loads(raw)
            except Exception:
                pass
        item = self._mem.get(key)
        if not item:
            return None
        exp, val = item
        if exp < time.time():
            self._mem.pop(key, None)
            return None
        return val

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        ttl = ttl if ttl is not None else self.default_ttl
        if self._redis is not None:
            try:
                self._redis.setex(key, ttl, json.dumps(value, default=str))
                return
            except Exception:
                pass
        self._mem[key] = (time.time() + ttl, value)


_cache: Cache | None = None


def get_cache() -> Cache:
    global _cache
    if _cache is None:
        try:
            from app.config import get_settings

            s = get_settings()
            _cache = Cache(redis_url=s.redis_url, default_ttl=s.cache.default_ttl_seconds)
        except Exception:
            _cache = Cache()
    return _cache
