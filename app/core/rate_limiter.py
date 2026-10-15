"""Central rate limiter with retry/backoff helpers."""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict


class RateLimiter:
    def __init__(self, per_minute: int = 60):
        self.per_minute = per_minute
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def acquire(self, key: str = "default") -> None:
        async with self._lock:
            now = time.time()
            window = [t for t in self._hits[key] if now - t < 60]
            self._hits[key] = window
            if len(window) >= self.per_minute:
                sleep_for = 60 - (now - window[0]) + 0.05
                await asyncio.sleep(max(sleep_for, 0))
            self._hits[key].append(time.time())


REGISTRY: dict[str, RateLimiter] = {}


def get_limiter(name: str, per_minute: int = 60) -> RateLimiter:
    if name not in REGISTRY:
        REGISTRY[name] = RateLimiter(per_minute)
    return REGISTRY[name]
