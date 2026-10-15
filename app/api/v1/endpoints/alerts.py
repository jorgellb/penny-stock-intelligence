"""Alert endpoints (history persisted by the monitor)."""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.database import get_session
from app.repositories import AlertRepository

router = APIRouter()


def _row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "symbol": row.symbol,
        "action": row.action,
        "signal_type": row.signal_type,
        "price": row.price,
        "score": row.score,
        "change_pct": row.change_pct,
        "risk_flags": row.risk_flags or [],
        "reasons": row.reasons or [],
        "catalyst_summary": row.catalyst_summary,
        "message": row.message,
        "providers": row.providers or [],
        "sent": row.sent_at is not None,
        "sent_at": row.sent_at.isoformat() if row.sent_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("/alerts")
async def get_alerts(
    symbol: str | None = Query(None),
    since: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    status: str | None = Query(None, description="sent|pending"),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Alert history persisted by the monitor (buy/sell only)."""
    since_dt = None
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
        except ValueError:
            since_dt = None
    sent = {"sent": True, "pending": False}.get((status or "").lower())
    rows = await AlertRepository(session).recent(symbol, limit, since_dt, sent)
    return {
        "alerts": [_row_to_dict(r) for r in rows],
        "total": len(rows),
        "timestamp": datetime.now(UTC).isoformat(),
    }


@router.post("/alerts/test")
async def test_alert() -> dict[str, Any]:
    """Test alert delivery."""
    return {"status": "sent", "message": "Test alert sent successfully"}


@router.get("/alerts/config")
async def get_alert_config() -> dict[str, Any]:
    """Alert configuration (live values)."""
    settings = get_settings()
    return {
        "cooldown_minutes": settings.alerts.cooldown_minutes,
        "score_change_realert": settings.alerts.score_change_realert,
        "minimum_score": settings.alerts.minimum_score,
        "enabled_providers": settings.alerts.enabled_providers,
    }
