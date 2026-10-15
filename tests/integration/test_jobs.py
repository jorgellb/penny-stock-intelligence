"""Integration: keyless jobs do real work (stub providers + sqlite)."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

import app.jobs as jobs_mod
from app.core.database import DatabaseManager
from app.domain.models import DailyBar, DataProvider, Fundamentals
from app.repositories import DailyBarRepository, FundamentalsRepository, WatchlistRepository


def _db(tmp_path) -> DatabaseManager:  # type: ignore[no-untyped-def]
    return DatabaseManager(database_url=f"sqlite+aiosqlite:///{tmp_path}/j.db")


async def _seed(db: DatabaseManager) -> None:
    await db.create_tables()
    async with db.session() as session:
        repo = WatchlistRepository(session)
        await repo.add("ABCD", "u1", "bio")
        await repo.add("EFGH", "u1", "bio")


class _Bars:
    async def get_daily_bars(self, symbol, start, **kw):  # type: ignore[no-untyped-def]
        return [
            DailyBar(
                symbol=symbol,
                date=datetime(2026, 9, 18, tzinfo=UTC),
                open=Decimal("1.9"),
                high=Decimal("2.1"),
                low=Decimal("1.8"),
                close=Decimal("2.0"),
                volume=500_000,
                provider=DataProvider.YFINANCE,
            )
        ]


class _Funds:
    async def get_fundamentals(self, symbol, period_type="ttm"):  # type: ignore[no-untyped-def]
        return Fundamentals(
            symbol=symbol,
            period_end=datetime.now(UTC),
            period_type=period_type,
            market_cap=100_000_000,
            cash=5_000_000,
            total_debt=1_000_000,
            data_quality_score=0.6,
            provider=DataProvider.YFINANCE,
        )


@pytest.mark.asyncio
async def test_sync_daily_history(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = _db(tmp_path)
    await _seed(db)
    import app.core.database as db_mod

    monkeypatch.setattr(db_mod, "get_db_manager", lambda: db)
    monkeypatch.setattr(jobs_mod, "_market_provider", lambda: _Bars())
    out = await jobs_mod.sync_daily_history()
    assert out["symbols"] == 2 and out["saved"] == 2 and out["failed"] == []
    async with db.session() as session:
        assert await DailyBarRepository(session).count("ABCD") == 1
    # idempotent: second run saves nothing new
    out2 = await jobs_mod.sync_daily_history()
    assert out2["saved"] == 0
    await db.close()


@pytest.mark.asyncio
async def test_sync_fundamentals(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = _db(tmp_path)
    await _seed(db)
    import app.core.database as db_mod

    monkeypatch.setattr(db_mod, "get_db_manager", lambda: db)
    monkeypatch.setattr(jobs_mod, "_fundamentals_provider", lambda: _Funds())
    out = await jobs_mod.sync_fundamentals()
    assert out["saved"] == 2
    async with db.session() as session:
        row = await FundamentalsRepository(session).latest("abcd")
        assert row is not None and row.market_cap == 100_000_000
    await db.close()


@pytest.mark.asyncio
async def test_scans_run_monitor_over_lists(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.providers.market_data import MockMarketDataProvider

    db = _db(tmp_path)
    await _seed(db)
    import app.core.database as db_mod

    monkeypatch.setattr(db_mod, "get_db_manager", lambda: db)
    monkeypatch.setattr(jobs_mod, "_market_provider", MockMarketDataProvider)
    for job in (jobs_mod.premarket_scan, jobs_mod.intraday_scan):
        out = await job()
        assert out["symbols"] == 2 and "regime" in out
    await db.close()


@pytest.mark.asyncio
async def test_noop_jobs_are_honest() -> None:
    news = await jobs_mod.sync_news()
    assert news["status"] == "noop" and "FINNHUB" in news["reason"]
    disp = await jobs_mod.alert_dispatch()
    assert disp["status"] == "noop"


@pytest.mark.asyncio
async def test_sync_filings_backfill(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import timedelta

    from app.domain.models import DataProvider, Filing, FilingType
    from app.jobs.filings import get_filings_cache

    db = _db(tmp_path)
    await _seed(db)
    import app.jobs.filings as filings_mod

    monkeypatch.setattr(filings_mod, "get_db_manager", lambda: db)

    now = datetime.now(UTC)

    class _Sec:
        async def get_recent_filings(self, symbols=None, hours: int = 48):  # type: ignore[no-untyped-def]
            assert hours == 24 * 30  # backfill window reaches the job
            filing = Filing(
                symbol="ABCD",
                cik="0001234567",
                accession_number="0001",
                filing_type=FilingType.S_1,
                filing_date=now - timedelta(days=10),
                accepted_at=now - timedelta(days=10),
                url="https://example.com",
                provider=DataProvider.SEC_EDGAR,
            )
            return [filing] if symbols is None or "ABCD" in symbols else []

    cache = get_filings_cache()
    old_sec, old_hours = cache.sec, cache.hours
    cache.sec, cache.hours = _Sec(), 48
    cache._cache.clear()  # singleton shared across tests: start cold
    try:
        out = await jobs_mod.sync_filings()
        assert out["job"] == "sync_filings" and out["hours"] == 720
        assert out["frozen"] == ["ABCD"]
    finally:
        cache.sec, cache.hours = old_sec, old_hours
        cache._cache.clear()
    await db.close()


@pytest.mark.asyncio
async def test_data_cleanup_retention(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = _db(tmp_path)
    await db.create_tables()
    import app.core.database as db_mod

    monkeypatch.setattr(db_mod, "get_db_manager", lambda: db)
    out = await jobs_mod.data_cleanup()
    assert out["alerts"] == 0 and out["monitor_snapshots"] == 0
    await db.close()


def test_scheduler_job_disposes_engine_per_loop(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each scheduler run gets a fresh loop: engine must be disposed
    inside it, or pooled asyncpg connections poison the next run."""
    db = _db(tmp_path)
    import app.core.database as db_mod

    monkeypatch.setattr(db_mod, "get_db_manager", lambda: db)

    first = jobs_mod._run_job_isolated("data_cleanup")
    assert first["job"] == "data_cleanup"
    assert db._engine is None

    second = jobs_mod._run_job_isolated("data_cleanup")
    assert second["job"] == "data_cleanup"
    assert db._engine is None
