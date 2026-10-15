"""API auth, CORS helpers, and HTTP rate limiting."""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.config import Settings, get_settings

# Paths that never require an API key (health + OpenAPI UI).
PUBLIC_PATHS = frozenset(
    {
        "/health",
        "/docs",
        "/redoc",
        "/openapi.json",
    }
)

_PROD_ENVS = frozenset({"production", "prod", "staging"})

_monitor_run_limiter: SlidingWindowCounter | None = None


class SlidingWindowCounter:
    """In-process sliding-window counter. ``hit`` returns False when over limit."""

    def __init__(self, limit: int, window_seconds: int) -> None:
        self.limit = max(1, limit)
        self.window_seconds = max(1, window_seconds)
        self._hits: dict[str, list[float]] = defaultdict(list)

    def hit(self, key: str) -> bool:
        now = time.monotonic()
        window = [t for t in self._hits[key] if now - t < self.window_seconds]
        if len(window) >= self.limit:
            self._hits[key] = window
            return False
        window.append(now)
        self._hits[key] = window
        return True

    def reset(self) -> None:
        self._hits.clear()


def reset_monitor_run_limiter() -> None:
    """Test helper: drop the singleton counter."""
    global _monitor_run_limiter
    if _monitor_run_limiter is not None:
        _monitor_run_limiter.reset()
    _monitor_run_limiter = None


def get_monitor_run_limiter(settings: Settings | None = None) -> SlidingWindowCounter:
    global _monitor_run_limiter
    s = settings or get_settings()
    limit = s.security.monitor_run_rate_limit
    window = s.security.rate_limit_window_seconds
    if (
        _monitor_run_limiter is None
        or _monitor_run_limiter.limit != max(1, limit)
        or _monitor_run_limiter.window_seconds != max(1, window)
    ):
        _monitor_run_limiter = SlidingWindowCounter(limit=limit, window_seconds=window)
    return _monitor_run_limiter


def api_auth_required(settings: Settings) -> bool:
    """Whether requests to /api/* must present a valid API key."""
    explicit = settings.security.require_api_key
    if explicit is not None:
        return explicit
    return settings.environment.lower() in _PROD_ENVS


def resolve_cors_origins(settings: Settings) -> list[str]:
    """CORS allow-list. Production never permits ``*``."""
    origins = list(settings.security.cors_origins or [])
    if settings.environment.lower() in _PROD_ENVS:
        return [o for o in origins if o != "*"]
    if not origins:
        return ["*"]
    return origins


def _extract_client_key(request: Request, settings: Settings) -> str:
    header = settings.security.api_key_header
    presented = request.headers.get(header) or request.headers.get(header.lower())
    if presented:
        return f"key:{presented}"
    client = request.client.host if request.client else "unknown"
    return f"ip:{client}"


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Enforce ``X-API-Key`` on /api routes when auth is required."""

    async def dispatch(self, request: Request, call_next: Callable[[Request], Any]) -> Response:
        if request.method == "OPTIONS":
            return await call_next(request)  # type: ignore[no-any-return]

        path = request.url.path
        if path in PUBLIC_PATHS or not path.startswith("/api"):
            return await call_next(request)  # type: ignore[no-any-return]

        settings = get_settings()
        if not api_auth_required(settings):
            return await call_next(request)  # type: ignore[no-any-return]

        header = settings.security.api_key_header
        presented = request.headers.get(header) or request.headers.get(header.lower())
        expected = settings.api_key
        if not presented or presented != expected:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing API key"},
            )
        return await call_next(request)  # type: ignore[no-any-return]


async def enforce_monitor_run_rate_limit(request: Request) -> None:
    """FastAPI dependency: 429 when /monitor/run exceeds the window budget."""
    from fastapi import HTTPException

    settings = get_settings()
    limiter = get_monitor_run_limiter(settings)
    key = _extract_client_key(request, settings)
    if not limiter.hit(key):
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded for monitor/run",
        )
