"""Radar job: promote ranked movers into the ``radar`` watchlist."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.logging import get_logger
from app.jobs.monitor import get_monitor_service
from app.repositories import WatchlistRepository
from app.scanners.opportunity import rank_opportunities

log = get_logger(__name__)


def _rows_from_monitor_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for e in events:
        price = float(e.get("price") or 0)
        dollar = float(e.get("dollar_volume") or 0)
        volume = float(e.get("volume") or 0)
        if volume <= 0 and price > 0 and dollar > 0:
            volume = dollar / price
        rows.append(
            {
                "symbol": e.get("symbol"),
                "price": price,
                "change_pct": e.get("change_pct"),
                "rvol": e.get("rvol"),
                "volume": volume,
                "score_proxy": e.get("score"),
            }
        )
    return rows


async def _rows_from_universe_seed(
    session: AsyncSession,
    *,
    limit: int,
    budget: int,
) -> list[dict[str, Any]]:
    """Cold-start discovery: eligible universe names ranked by dollar volume."""
    from app.providers.market_data import YFinanceMarketDataProvider
    from app.scanners.universe_scan import scan_universe

    scan = await scan_universe(
        session,
        YFinanceMarketDataProvider(),
        limit=max(limit * 3, 60),
        budget=budget,
    )
    eligible = list(scan.get("eligible") or [])
    eligible.sort(key=lambda r: float(r.get("dollar_volume") or 0), reverse=True)
    rows: list[dict[str, Any]] = []
    for r in eligible[:limit]:
        price = float(r.get("price") or 0)
        volume = float(r.get("volume") or 0)
        # Seed pass has no live RVOL/change — use soft proxies so liquid names
        # still clear radar gates and get monitored next round.
        rows.append(
            {
                "symbol": r.get("symbol"),
                "price": price,
                "change_pct": 3.0,
                "rvol": 2.0,
                "volume": volume,
                "score_proxy": 60.0,
            }
        )
    return rows


async def run_radar_pass(
    session: AsyncSession | None = None,
    user_id: str = "default",
    *,
    seed_universe: bool = True,
) -> dict[str, Any]:
    """Rank monitor events (and optionally universe seeds) into the radar list."""
    cfg = get_settings().monitor
    if not cfg.radar_enabled:
        return {"status": "disabled", "added": 0, "symbols": []}

    svc = get_monitor_service()
    events = svc.recent_events(limit=500)
    rows = _rows_from_monitor_events(events)
    seeded = 0

    if session is None:
        from app.core.database import get_db_manager

        db = get_db_manager()
        await db.create_tables()
        async with db.session() as own_session:
            return await _run_with_session(
                own_session,
                user_id,
                cfg,
                rows,
                seed_universe=seed_universe,
                seeded_hint=seeded,
            )

    return await _run_with_session(
        session,
        user_id,
        cfg,
        rows,
        seed_universe=seed_universe,
        seeded_hint=seeded,
    )


async def _run_with_session(
    session: AsyncSession,
    user_id: str,
    cfg: Any,
    rows: list[dict[str, Any]],
    *,
    seed_universe: bool,
    seeded_hint: int,
) -> dict[str, Any]:
    seeded = seeded_hint
    # Cold start / thin monitor cache: pull liquid eligibles from universe.
    if seed_universe and len(rows) < max(5, int(cfg.radar_max_symbols) // 4):
        try:
            uni_rows = await _rows_from_universe_seed(
                session,
                limit=int(cfg.radar_max_symbols),
                budget=min(400, int(cfg.radar_max_symbols) * 4),
            )
            seen = {str(r.get("symbol", "")).upper() for r in rows}
            for r in uni_rows:
                sym = str(r.get("symbol", "")).upper()
                if sym and sym not in seen:
                    rows.append(r)
                    seen.add(sym)
                    seeded += 1
        except Exception as exc:
            log.error("radar_universe_seed_failed", error=str(exc))

    ranked = rank_opportunities(
        rows,
        min_score=float(cfg.radar_min_score),
        min_rvol=float(cfg.radar_min_rvol),
        min_change_pct=float(cfg.radar_min_change_pct),
        max_results=int(cfg.radar_max_symbols),
    )
    symbols = [o.symbol for o in ranked]
    if not symbols:
        return {
            "status": "empty",
            "added": 0,
            "symbols": [],
            "ranked": 0,
            "seeded": seeded,
        }

    result = await _sync_list(session, user_id, cfg.radar_list_name, symbols, ranked)
    result["seeded"] = seeded
    return result


async def _sync_list(
    session: AsyncSession,
    user_id: str,
    list_name: str,
    symbols: list[str],
    ranked: list[Any],
) -> dict[str, Any]:
    repo = WatchlistRepository(session)
    # Replace-set semantics: keep list focused on current ranked set.
    existing = set(await repo.symbols(user_id, list_name))
    wanted = set(symbols)
    for stale in existing - wanted:
        await repo.remove(stale, user_id, list_name)
    added = 0
    for sym in symbols:
        _item, created = await repo.add(sym, user_id, list_name)
        if created:
            added += 1
    log.info(
        "radar_pass_complete",
        list=list_name,
        ranked=len(ranked),
        added=added,
        pruned=len(existing - wanted),
    )
    return {
        "status": "ok",
        "list": list_name,
        "ranked": len(ranked),
        "added": added,
        "pruned": len(existing - wanted),
        "symbols": symbols,
        "top": [
            {
                "symbol": o.symbol,
                "rank_score": o.rank_score,
                "setups_hint": o.setups_hint,
                "change_pct": o.change_pct,
                "rvol": o.rvol,
                "dollar_volume": o.dollar_volume,
            }
            for o in ranked[:15]
        ],
    }


async def radar_job() -> dict[str, Any]:
    """Scheduler entrypoint."""
    log.info("job_started", job="radar")
    try:
        result = await run_radar_pass()
        log.info(
            "job_completed",
            job="radar",
            **{k: result.get(k) for k in ("status", "added", "seeded", "pruned")},
        )
        return result
    except Exception as exc:
        log.error("job_failed", job="radar", error=str(exc))
        return {"status": "error", "error": str(exc)}
