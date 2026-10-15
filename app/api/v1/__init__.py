"""Penny Stock Intelligence Engine API Router."""

from fastapi import APIRouter

from app.api.v1.endpoints.alerts import router as alerts_router
from app.api.v1.endpoints.backtest import router as backtest_router
from app.api.v1.endpoints.dashboard import router as dashboard_router
from app.api.v1.endpoints.health import router as health_router
from app.api.v1.endpoints.monitor import router as monitor_router
from app.api.v1.endpoints.opportunities import router as opportunities_router
from app.api.v1.endpoints.scanner import router as scanner_router
from app.api.v1.endpoints.stocks import router as stocks_router
from app.api.v1.endpoints.watchlist import router as watchlist_router

router = APIRouter()

router.include_router(health_router, tags=["Health"])
router.include_router(monitor_router, tags=["Monitor"])
router.include_router(opportunities_router, tags=["Opportunities"])
router.include_router(scanner_router, tags=["Scanner"])
router.include_router(stocks_router, tags=["Stocks"])
router.include_router(alerts_router, tags=["Alerts"])
router.include_router(dashboard_router, tags=["Dashboard"])
router.include_router(watchlist_router, tags=["Watchlist"])
router.include_router(backtest_router, tags=["Backtest"])


@router.get("/")
async def root() -> dict[str, str]:
    return {
        "name": "Penny Stock Intelligence Engine",
        "version": "0.1.0",
        "documentation": "/docs",
        "openapi_json": "/openapi.json",
    }
