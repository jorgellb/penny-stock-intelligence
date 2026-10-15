"""
Penny Stock Intelligence Engine - Main Application.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import router as api_router
from app.config import get_settings
from app.core.database import get_db_manager
from app.core.logging import get_logger, setup_logging
from app.core.security import APIKeyMiddleware, resolve_cors_origins

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan events."""
    settings = get_settings()
    logger.info("Starting Penny Stock Intelligence Engine")

    # Initialize database
    db_manager = get_db_manager()
    await db_manager.create_tables()
    logger.info("Database tables created/verified")

    # Initialize logging
    setup_logging()
    logger.info("Logging configured")

    logger.info(f"Environment: {settings.environment}")
    logger.info(f"Paper Mode: {settings.paper_mode}")
    logger.info(f"Live Trading: {settings.live_trading}")

    yield

    # Cleanup
    await db_manager.close()
    logger.info("Application shutdown complete")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()
    app = FastAPI(
        title="Penny Stock Intelligence Engine",
        description="""
        Professional scanner and analysis system for US penny stocks and micro-cap stocks.

        This is an analytical research tool. Scores are ranking metrics, not probability forecasts.
        Live trading is disabled. All operations are manual.
        """,
        version="0.1.0",
        lifespan=lifespan,
        debug=settings.debug,
    )

    origins = resolve_cors_origins(settings)
    # Wildcard + credentials is invalid per the CORS spec; drop credentials if needed.
    allow_credentials = settings.security.cors_allow_credentials and "*" not in origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(APIKeyMiddleware)

    # Include API routes
    app.include_router(api_router, prefix="/api/v1")

    # Health check endpoint
    @app.get("/health")
    async def health() -> dict[str, Any]:
        s = get_settings()
        return {
            "status": "healthy",
            "service": "penny-stock-intelligence",
            "version": "0.1.0",
            "environment": s.environment,
            "paper_mode": s.paper_mode,
            "live_trading": s.live_trading,
        }

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn  # type: ignore[import-not-found]

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
