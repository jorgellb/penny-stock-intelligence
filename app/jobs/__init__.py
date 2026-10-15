"""APScheduler jobs: each runnable manually for debugging."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.logging import get_logger

log = get_logger(__name__)

#: Retention for research tables (alerts, snapshots, paper trades).
DATA_RETENTION_DAYS = 90


def _market_provider() -> Any:
    from app.providers.market_data import YFinanceMarketDataProvider

    return YFinanceMarketDataProvider()


def _fundamentals_provider() -> Any:
    from app.providers.fundamentals import YFinanceFundamentalsProvider

    return YFinanceFundamentalsProvider()


async def _watchlist_symbols() -> list[str]:
    """Union of symbols across all users/lists (empty when none)."""
    from app.core.database import get_db_manager
    from app.repositories import WatchlistRepository

    db = get_db_manager()
    await db.create_tables()
    out: set[str] = set()
    async with db.session() as session:
        repo = WatchlistRepository(session)
        for user in await repo.user_ids():
            for lst in await repo.lists(user):
                name = str(lst.get("name", "default"))
                out.update(await repo.symbols(user, name))
    return sorted(out)


async def sync_universe() -> dict:
    """Refresh the securities master from the free Nasdaq Trader directory."""
    from app.config import get_settings
    from app.core.database import get_db_manager
    from app.providers.market_data.nasdaq_listings import fetch_listings, to_securities
    from app.repositories import SecurityRepository

    log.info("job_started", job="sync_universe")
    try:
        uni = get_settings().universe
        rows = await fetch_listings()
        secs = to_securities(
            rows,
            exclude_etfs=uni.exclude_etfs,
            exclude_warrants=uni.exclude_warrants,
            exclude_units=uni.exclude_spac_units,
            exclude_preferred=uni.exclude_preferred,
            include_tests=False,
        )
        allowed = {e.upper() for e in uni.exchanges}
        if uni.include_otc is False:
            # domain Security uses use_enum_values: exchange may be a plain str
            secs = [
                s for s in secs if str(getattr(s.exchange, "value", s.exchange)).upper() in allowed
            ]
        db = get_db_manager()
        await db.create_tables()
        saved = 0
        async with db.session() as session:
            repo = SecurityRepository(session)
            for s in secs:
                exch = str(getattr(s.exchange, "value", s.exchange)).upper()
                await repo.upsert(
                    s.symbol,
                    exch,
                    s.name,
                    is_etf=s.is_etf,
                    is_preferred=s.is_preferred,
                    is_warrant=s.is_warrant,
                    is_spac_unit=s.is_spac_unit,
                    is_active=s.is_active,
                )
                saved += 1
        out = {"job": "sync_universe", "at": datetime.now(UTC).isoformat(), "saved": saved}
        log.info("job_completed", **out)
        return out
    except Exception as exc:
        log.error("job_failed", job="sync_universe", error=str(exc))
        return {"job": "sync_universe", "error": str(exc)}


async def sync_daily_history(days: int = 90) -> dict:
    """Fetch daily bars for watchlist symbols (yfinance, idempotent)."""
    from app.core.database import get_db_manager
    from app.repositories import DailyBarRepository

    log.info("job_started", job="sync_daily_history")
    try:
        symbols = await _watchlist_symbols()
        provider = _market_provider()
        start = datetime.now(UTC) - timedelta(days=days * 2)
        sem = asyncio.Semaphore(3)
        fetched: dict[str, list] = {}
        failed: list[str] = []

        async def _one(sym: str) -> None:
            async with sem:
                try:
                    fetched[sym] = list(await provider.get_daily_bars(sym, start=start) or [])
                except Exception as exc:
                    failed.append(sym)
                    log.error("daily_sync_failed", symbol=sym, error=str(exc))

        db = get_db_manager()
        await db.create_tables()
        await asyncio.gather(*(_one(s) for s in symbols))
        # Sequential persistence: sqlite cannot take concurrent writers.
        saved = 0
        async with db.session() as session:
            repo = DailyBarRepository(session)
            for sym, bars in fetched.items():
                try:
                    saved += await repo.upsert_batch(sym, bars)
                except Exception as exc:
                    failed.append(sym)
                    log.error("daily_persist_failed", symbol=sym, error=str(exc))
        out = {
            "job": "sync_daily_history",
            "at": datetime.now(UTC).isoformat(),
            "symbols": len(symbols),
            "saved": saved,
            "failed": failed,
        }
        log.info("job_completed", **out)
        return out
    except Exception as exc:
        log.error("job_failed", job="sync_daily_history", error=str(exc))
        return {"job": "sync_daily_history", "error": str(exc)}


async def sync_fundamentals() -> dict:
    """Fetch fundamental snapshots for watchlist symbols (yfinance)."""
    from app.core.database import get_db_manager
    from app.repositories import FundamentalsRepository

    log.info("job_started", job="sync_fundamentals")
    try:
        symbols = await _watchlist_symbols()
        provider = _fundamentals_provider()
        sem = asyncio.Semaphore(3)
        fetched: dict[str, Any] = {}
        failed: list[str] = []

        async def _one(sym: str) -> None:
            async with sem:
                try:
                    fund = await provider.get_fundamentals(sym)
                    if fund is None:
                        failed.append(sym)
                        return
                    fetched[sym] = fund
                except Exception as exc:
                    failed.append(sym)
                    log.error("fundamentals_sync_failed", symbol=sym, error=str(exc))

        db = get_db_manager()
        await db.create_tables()
        await asyncio.gather(*(_one(s) for s in symbols))
        # Sequential persistence: sqlite cannot take concurrent writers.
        saved = 0
        async with db.session() as session:
            repo = FundamentalsRepository(session)
            for sym, fund in fetched.items():
                try:
                    await repo.save_snapshot(fund)
                    saved += 1
                except Exception as exc:
                    failed.append(sym)
                    log.error("fundamentals_persist_failed", symbol=sym, error=str(exc))
        out = {
            "job": "sync_fundamentals",
            "at": datetime.now(UTC).isoformat(),
            "symbols": len(symbols),
            "saved": saved,
            "failed": failed,
        }
        log.info("job_completed", **out)
        return out
    except Exception as exc:
        log.error("job_failed", job="sync_fundamentals", error=str(exc))
        return {"job": "sync_fundamentals", "error": str(exc)}


async def sync_filings() -> dict:
    """30-day backfill over watchlists (the fast job covers the last 48h)."""
    from app.jobs.filings import sync_lists

    log.info("job_started", job="sync_filings")
    try:
        return await sync_lists(hours=24 * 30, job="sync_filings")
    except Exception as exc:
        log.error("job_failed", job="sync_filings", error=str(exc))
        return {"job": "sync_filings", "error": str(exc)}


async def sync_filings_fast() -> dict:
    """Poll recent SEC filings for watchlisted symbols (dilution freeze)."""
    from app.jobs.filings import sync_lists

    log.info("job_started", job="sync_filings_fast")
    try:
        return await sync_lists()
    except Exception as exc:
        log.error("job_failed", job="sync_filings_fast", error=str(exc))
        return {"job": "sync_filings_fast", "error": str(exc)}


async def sync_news() -> dict:
    log.info("job_started", job="sync_news")
    return {
        "job": "sync_news",
        "at": datetime.now(UTC).isoformat(),
        "status": "noop",
        "reason": "needs FINNHUB_API_KEY (or alpha_vantage); set it to enable",
    }


async def _monitor_round(mode: str) -> dict:
    from app.jobs.monitor import get_monitor_service

    log.info("job_started", job=f"{mode}_scan")
    try:
        symbols = await _watchlist_symbols()
        if not symbols:
            return {"job": f"{mode}_scan", "status": "empty", "reason": "no watchlists"}
        svc = get_monitor_service()
        # Keep feed fresh on the shared singleton (jobs may outlive provider state).
        svc.provider = _market_provider()
        if svc.fundamentals is None:
            svc.fundamentals = _fundamentals_provider()
        results = await svc.run_once(symbols)
        out = {
            "job": f"{mode}_scan",
            "at": datetime.now(UTC).isoformat(),
            "symbols": len(results),
            "signals": sum(1 for e in results if e.action != "hold"),
            "sent": sum(1 for e in results if e.sent),
            "regime": svc.last_regime,
        }
        log.info("job_completed", **out)
        return out
    except Exception as exc:
        log.error("job_failed", job=f"{mode}_scan", error=str(exc))
        return {"job": f"{mode}_scan", "error": str(exc)}


async def premarket_scan() -> dict:
    return await _monitor_round("premarket")


async def intraday_scan() -> dict:
    return await _monitor_round("intraday")


async def radar_job_entry() -> dict:
    """Promote ranked movers into the radar watchlist."""
    from app.jobs.radar import radar_job

    return await radar_job()


async def risk_refresh() -> dict:
    """Refresh dilution-freeze decisions from recent SEC filings."""
    from app.jobs.filings import sync_lists

    log.info("job_started", job="risk_refresh")
    try:
        return await sync_lists()
    except Exception as exc:
        log.error("job_failed", job="risk_refresh", error=str(exc))
        return {"job": "risk_refresh", "error": str(exc)}


async def alert_dispatch() -> dict:
    log.info("job_started", job="alert_dispatch")
    return {
        "job": "alert_dispatch",
        "at": datetime.now(UTC).isoformat(),
        "status": "noop",
        "reason": "alerts dispatch inline inside monitor run_once; no queue pending",
    }


async def data_cleanup(retention_days: int = DATA_RETENTION_DAYS) -> dict:
    """Delete research rows older than retention (alerts, snapshots, paper)."""
    from sqlalchemy import delete

    from app.core.database import get_db_manager
    from app.models import Alerts, MonitorSnapshots, PaperTrades

    log.info("job_started", job="data_cleanup")
    try:
        cutoff = datetime.now(UTC) - timedelta(days=retention_days)
        db = get_db_manager()
        await db.create_tables()
        removed: dict[str, int] = {}
        async with db.session() as session:
            for model, name in (
                (Alerts, "alerts"),
                (MonitorSnapshots, "monitor_snapshots"),
                (PaperTrades, "paper_trades"),
            ):
                res = await session.execute(
                    delete(model).where(model.created_at < cutoff)
                    if hasattr(model, "created_at")
                    else delete(model).where(model.exit_time < cutoff)
                )
                removed[name] = int(getattr(res, "rowcount", 0) or 0)
        out = {"job": "data_cleanup", "at": datetime.now(UTC).isoformat(), **removed}
        log.info("job_completed", **out)
        return out
    except Exception as exc:
        log.error("job_failed", job="data_cleanup", error=str(exc))
        return {"job": "data_cleanup", "error": str(exc)}


JOBS = {
    "sync_universe": sync_universe,
    "sync_daily_history": sync_daily_history,
    "sync_fundamentals": sync_fundamentals,
    "sync_filings": sync_filings,
    "sync_filings_fast": sync_filings_fast,
    "sync_news": sync_news,
    "premarket_scan": premarket_scan,
    "intraday_scan": intraday_scan,
    "radar": radar_job_entry,
    "risk_refresh": risk_refresh,
    "alert_dispatch": alert_dispatch,
    "data_cleanup": data_cleanup,
}


async def run_job(name: str) -> dict:
    if name not in JOBS:
        raise ValueError(f"unknown job {name}")
    return await JOBS[name]()


def parse_cron(expr: str) -> dict[str, str]:
    """Parse a 5-field cron (minute hour dom month dow) into trigger kwargs.

    Raises ValueError on malformed expressions instead of silently
    scheduling at the wrong time.
    """
    parts = expr.strip().split()
    if len(parts) != 5:
        raise ValueError(f"cron needs 5 fields, got {len(parts)}: {expr!r}")
    minute, hour, dom, month, dow = parts
    return {
        "minute": minute,
        "hour": hour,
        "day": dom,
        "month": month,
        "day_of_week": dow,
    }


def _run_job_isolated(name: str) -> dict:
    """Run one job in a fresh event loop and release loop-bound resources.

    APScheduler executes each job in a worker thread and every
    ``asyncio.run`` creates a new event loop. A pooled asyncpg connection
    from a previous loop cannot be reused ("attached to a different
    loop"), so the engine is disposed inside the job's own loop.
    """

    async def _main() -> dict:
        try:
            return await run_job(name)
        finally:
            from app.core.database import get_db_manager

            await get_db_manager().close()

    return asyncio.run(_main())


def run_scheduler() -> None:
    from apscheduler.schedulers.blocking import BlockingScheduler  # type: ignore[import-not-found]

    from app.config import get_settings

    s = get_settings()
    sched = BlockingScheduler()
    for name, cron in s.scheduler.jobs.model_dump().items():
        if name in JOBS:
            sched.add_job(
                lambda n=name: _run_job_isolated(n),
                "cron",
                **parse_cron(str(cron)),
                id=name,
            )
    log.info("scheduler_started")
    sched.start()
