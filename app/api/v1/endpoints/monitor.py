"""Realtime monitor endpoints."""

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.security import enforce_monitor_run_rate_limit
from app.jobs.monitor import get_monitor_service
from app.repositories import WatchlistRepository

router = APIRouter()


@router.get("/monitor/status")
async def monitor_status() -> dict[str, Any]:
    """Monitor loop status and last run stats."""
    return get_monitor_service().status()


@router.get("/monitor/events")
async def monitor_events(limit: int = Query(50, ge=1, le=200)) -> dict[str, Any]:
    """Recent signal events (buy/sell/hold) from the monitor."""
    svc = get_monitor_service()
    events = svc.recent_events(limit)
    return {"events": events, "count": len(events)}


@router.post("/monitor/run")
async def monitor_run(
    list_name: str = Query("default"),
    user_id: str = Query("default"),
    session: AsyncSession = Depends(get_session),
    _: None = Depends(enforce_monitor_run_rate_limit),
) -> dict[str, Any]:
    """Run one monitor pass over a list and return signals."""
    symbols = await WatchlistRepository(session).symbols(user_id, list_name)
    svc = get_monitor_service()
    results = await svc.run_once(symbols)
    return {
        "list": list_name,
        "symbols": len(symbols),
        "signals": [
            {
                "symbol": e.symbol,
                "action": e.action,
                "price": e.price,
                "score": e.score,
                "setup": e.setup,
                "matched_setups": list(e.matched_setups),
                "reasons": e.reasons,
                "sent": e.sent,
                "order_template": e.order_template,
                "timestamp": e.timestamp.isoformat(),
            }
            for e in results
        ],
    }


@router.get("/monitor/config")
async def monitor_config() -> dict[str, Any]:
    """Current monitor/signal thresholds."""
    from app.config import get_settings

    return get_settings().monitor.model_dump()


@router.get("/monitor/circuits")
async def monitor_circuits(
    level: str | None = Query(None, description="symbol|strategy|portfolio"),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Persisted circuit-breaker audit trail (newest first)."""
    from app.repositories import CircuitEventRepository

    rows = await CircuitEventRepository(session).recent(level=level, limit=limit)
    return {
        "events": [
            {
                "level": r.level,
                "key": r.key,
                "reason": r.reason,
                "timestamp": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
        "count": len(rows),
    }


@router.get("/monitor/paper")
async def monitor_paper() -> dict[str, Any]:
    """Live paper portfolio summary (positions in memory)."""
    return get_monitor_service().paper.summary()


@router.get("/monitor/paper/trades")
async def monitor_paper_trades(
    symbol: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Closed paper trades from the audit table (newest first)."""
    from app.repositories import PaperTradeRepository

    rows = await PaperTradeRepository(session).recent(symbol=symbol, limit=limit)
    return {
        "trades": [
            {
                "symbol": r.symbol,
                "shares": r.shares,
                "entry_price": r.entry_price,
                "exit_price": r.exit_price,
                "pnl_dollars": r.pnl_dollars,
                "pnl_pct": r.pnl_pct,
                "entry_time": r.entry_time.isoformat() if r.entry_time else None,
                "exit_time": r.exit_time.isoformat() if r.exit_time else None,
            }
            for r in rows
        ],
        "count": len(rows),
    }


@router.get("/monitor/snapshots")
async def monitor_snapshots(
    symbol: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Per-symbol evaluation history (features only, never future returns)."""
    from app.repositories import MonitorSnapshotRepository

    rows = await MonitorSnapshotRepository(session).recent(symbol=symbol, limit=limit)
    return {
        "snapshots": [
            {
                "symbol": r.symbol,
                "action": r.action,
                "score": r.score,
                "price": r.price,
                "change_pct": r.change_pct,
                "rvol": r.rvol,
                "vwap_distance_pct": r.vwap_distance_pct,
                "risk_flags": r.risk_flags,
                "regime": r.regime,
                "config_hash": r.config_hash,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
        "count": len(rows),
    }
