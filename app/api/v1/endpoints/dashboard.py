"""Dashboard endpoints."""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter

router = APIRouter()


@router.get("/dashboard/state")
async def get_dashboard_state() -> dict[str, Any]:
    """Get dashboard state."""
    return {
        "market_status": "open",
        "last_universe_refresh": datetime.now(UTC).isoformat(),
        "last_quote_update": datetime.now(UTC).isoformat(),
        "last_filing_update": datetime.now(UTC).isoformat(),
        "last_news_update": datetime.now(UTC).isoformat(),
        "eligible_stocks": 0,
        "high_score_stocks": 0,
        "risk_alerts": 0,
        "provider_status": {
            "market_data": "ok",
            "fundamentals": "ok",
            "news": "ok",
            "sec": "ok",
            "ai": "ok",
        },
    }
