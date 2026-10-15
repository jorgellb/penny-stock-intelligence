"""API v1 endpoints."""

from app.api.v1.endpoints.alerts import router as alerts_router
from app.api.v1.endpoints.backtest import router as backtest_router
from app.api.v1.endpoints.dashboard import router as dashboard_router
from app.api.v1.endpoints.health import router as health_router
from app.api.v1.endpoints.monitor import router as monitor_router
from app.api.v1.endpoints.scanner import router as scanner_router
from app.api.v1.endpoints.stocks import router as stocks_router
from app.api.v1.endpoints.watchlist import router as watchlist_router
