"""Health check endpoints."""

from typing import Any

from fastapi import APIRouter

from app.config import get_settings

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "healthy"}


@router.get("/health/detailed")
async def health_check() -> dict[str, Any]:
    settings = get_settings()
    return {
        "status": "healthy",
        "environment": settings.environment,
        "database": {
            "pool_size": settings.database.pool_size,
        },
        "paper_mode": settings.paper_mode,
        "live_trading": settings.live_trading,
    }
