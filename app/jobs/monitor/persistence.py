"""Fail-soft persistence helpers for the monitor loop."""

from __future__ import annotations

from typing import Any

from app.config import config_fingerprint
from app.core.database import get_db_manager
from app.core.logging import get_logger
from app.domain.models import SignalType
from app.risk.paper import PaperPosition

from .types import MonitoredEvent

log = get_logger(__name__)


async def persist_events(events: list[MonitoredEvent]) -> int:
    """Persist actionable (buy/sell) events to the alerts table."""
    actionable = [e for e in events if e.action in ("buy", "sell")]
    if not actionable:
        return 0
    from app.repositories import AlertRepository

    saved = 0
    try:
        db = get_db_manager()
        async with db.session() as session:
            repo = AlertRepository(session)
            for e in actionable:
                await repo.save(
                    symbol=e.symbol,
                    action=e.action,
                    signal_type=(
                        SignalType.MOMENTUM.value
                        if e.action == "buy"
                        else SignalType.REVERSAL.value
                    ),
                    price=e.price,
                    score=e.score,
                    change_pct=e.change_pct,
                    message=f"POSIBLE {e.action.upper()} (revisar): {e.symbol} @ "
                    f"${e.price:.2f} [score {e.score}]\n"
                    + "\n".join(f"- {r}" for r in e.reasons),
                    risk_flags=e.risk_flags,
                    reasons=e.reasons,
                    catalyst_summary=e.catalyst_summary,
                    sent=e.sent,
                    providers=e.providers,
                )
                saved += 1
    except Exception as exc:
        log.error("alerts_persist_failed", error=str(exc))
    return saved


async def persist_circuits(events: list) -> int:
    """Persist this round's breaker trips. Never breaks monitoring."""
    if not events:
        return 0
    from app.repositories import CircuitEventRepository

    try:
        db = get_db_manager()
        async with db.session() as session:
            repo = CircuitEventRepository(session)
            return await repo.save_batch(
                [
                    {
                        "level": e.level,
                        "key": e.key,
                        "reason": e.reason,
                        "timestamp": e.timestamp,
                    }
                    for e in events
                ]
            )
    except Exception as exc:
        log.error("circuits_persist_failed", error=str(exc))
        return 0


async def load_positions(paper: Any) -> int:
    """Restore open paper positions into ``paper``. Fail-soft."""
    from app.repositories import PaperPositionRepository

    try:
        db = get_db_manager()
        async with db.session() as session:
            rows = await PaperPositionRepository(session).list_all()
    except Exception as exc:
        log.error("paper_positions_load_failed", error=str(exc))
        return 0
    for r in rows:
        paper.positions[r.symbol] = PaperPosition(
            symbol=r.symbol,
            shares=r.shares,
            entry_price=r.entry_price,
            entry_time=r.entry_time,
            last_price=r.entry_price,
        )
    return len(rows)


async def store_position(pos: Any) -> None:
    from app.repositories import PaperPositionRepository

    try:
        db = get_db_manager()
        async with db.session() as session:
            await PaperPositionRepository(session).upsert(
                pos.symbol, pos.shares, pos.entry_price, pos.entry_time
            )
    except Exception as exc:
        log.error("paper_position_store_failed", error=str(exc))


async def drop_position(symbol: str) -> None:
    from app.repositories import PaperPositionRepository

    try:
        db = get_db_manager()
        async with db.session() as session:
            await PaperPositionRepository(session).remove(symbol)
    except Exception as exc:
        log.error("paper_position_drop_failed", error=str(exc))


async def persist_paper(trades: list) -> int:
    """Persist this round's closed paper trades. Never breaks monitoring."""
    if not trades:
        return 0
    from app.repositories import PaperTradeRepository

    try:
        db = get_db_manager()
        async with db.session() as session:
            repo = PaperTradeRepository(session)
            for t in trades:
                await repo.save(t)
            return len(trades)
    except Exception as exc:
        log.error("paper_persist_failed", error=str(exc))
        return 0


async def persist_snapshots(events: list[MonitoredEvent], last_regime: str) -> int:
    """Persist per-symbol round rows + the round summary (fail-soft)."""
    from app.repositories import MonitorSnapshotRepository, ScannerRunRepository

    if not events:
        return 0
    try:
        fingerprint = config_fingerprint()
        db = get_db_manager()
        async with db.session() as session:
            snap_repo = MonitorSnapshotRepository(session)
            await snap_repo.save_batch(
                [
                    {
                        "symbol": e.symbol,
                        "action": e.action,
                        "score": e.score,
                        "price": e.price,
                        "change_pct": e.change_pct,
                        "rvol": e.rvol,
                        "vwap_distance_pct": e.vwap_distance_pct,
                        "risk_flags": e.risk_flags,
                        "regime": last_regime,
                        "config_hash": fingerprint,
                    }
                    for e in events
                ]
            )
            await ScannerRunRepository(session).save_run(
                run_type="monitor",
                symbols_scanned=len(events),
                eligible_count=sum(1 for e in events if e.action == "buy"),
                alerts_generated=sum(1 for e in events if e.sent),
                duration_ms=0,
                config_hash=fingerprint,
            )
            return len(events)
    except Exception as exc:
        log.error("snapshots_persist_failed", error=str(exc))
        return 0
