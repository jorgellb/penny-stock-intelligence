"""Scanner endpoints (rankings over live monitor evaluations)."""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.core.market_calendar import market_session
from app.jobs.monitor import get_monitor_service

router = APIRouter()


class ScanResponse(BaseModel):
    timestamp: datetime
    total_symbols: int
    eligible_count: int
    excluded_count: int
    results: list
    duration_ms: int | None = None


class PremarketScanResponse(BaseModel):
    rankings: list
    timestamp: datetime


class IntradayScanResponse(BaseModel):
    rankings: list
    timestamp: datetime
    market_status: str


def _ranked(min_score: int = 0, min_rvol: float = 0.0, limit: int = 100) -> list[dict[str, Any]]:
    """Monitor evaluations ranked by score (only what was actually evaluated)."""
    events = get_monitor_service().recent_events(limit=500)
    rows = [
        e for e in events if e.get("score", 0) >= min_score and (e.get("rvol") or 0) >= min_rvol
    ]
    rows.sort(key=lambda e: (e.get("score", 0), e.get("rvol") or 0), reverse=True)
    return rows[:limit]


@router.get("/scanner", response_model=ScanResponse)
async def scan(
    exchange: str | None = Query(None),
    min_score: int = Query(70, ge=0, le=100),
    min_rvol: float = Query(1.0, ge=0),
) -> ScanResponse:
    """Rank recent monitor evaluations (run POST /monitor/run first)."""
    _ = exchange  # ranking is over evaluated symbols, not a listing scan
    rows = _ranked(min_score=min_score, min_rvol=min_rvol)
    return ScanResponse(
        timestamp=datetime.now(UTC),
        total_symbols=len(rows),
        eligible_count=sum(1 for r in rows if r.get("action") == "buy"),
        excluded_count=sum(1 for r in rows if r.get("action") != "buy"),
        results=rows,
    )


@router.get("/scanner/premarket", response_model=PremarketScanResponse)
async def premarket_scan(
    exchange: str | None = Query(None),
    min_gap_pct: float = Query(0.0, ge=-100),
    min_rvol: float = Query(1.0, ge=0),
) -> PremarketScanResponse:
    """Premarket ranking over recent evaluations (gap via change %)."""
    _ = exchange
    rows = [r for r in _ranked(min_rvol=min_rvol) if abs(r.get("change_pct") or 0) >= min_gap_pct]
    return PremarketScanResponse(rankings=rows, timestamp=datetime.now(UTC))


@router.get("/scanner/intraday", response_model=IntradayScanResponse)
async def intraday_scan(
    exchange: str | None = Query(None),
    min_vwap_distance: float | None = Query(None),
) -> IntradayScanResponse:
    """Intraday ranking over recent evaluations with market session."""
    _ = exchange
    try:
        session = market_session().value
    except Exception:
        session = "unknown"
    rows = _ranked()
    if min_vwap_distance is not None:
        rows = [r for r in rows if (r.get("vwap_distance_pct") or 0) >= min_vwap_distance]
    return IntradayScanResponse(rankings=rows, timestamp=datetime.now(UTC), market_status=session)
