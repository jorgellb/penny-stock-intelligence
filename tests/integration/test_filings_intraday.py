"""Integration: SEC fast filings + intraday same-time RVOL live in monitor."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.domain.models import Bar, DataProvider, Filing, FilingType
from app.jobs.filings import FilingsCache, get_filings_cache
from app.jobs.monitor import MonitorService
from app.providers.market_data import MockMarketDataProvider


def _s1(days_ago: int = 1) -> Filing:
    now = datetime.now(UTC)
    return Filing(
        symbol="ABCD",
        cik="0001234567",
        accession_number=f"0001-{days_ago}",
        filing_type=FilingType.S_1,
        filing_date=now - timedelta(days=days_ago),
        accepted_at=now - timedelta(days=days_ago),
        url="https://example.com",
        provider=DataProvider.SEC_EDGAR,
    )


class StubSec:
    def __init__(self, filings: list) -> None:
        self.filings = filings
        self.calls = 0

    async def get_recent_filings(self, symbols=None, hours: int = 48):  # type: ignore[no-untyped-def]
        self.calls += 1
        return [f for f in self.filings if symbols is None or f.symbol in symbols]


@pytest.mark.asyncio
async def test_filings_cache_ttl_and_freeze() -> None:
    cache = FilingsCache(sec_provider=StubSec([_s1()]), ttl_seconds=300)
    decisions = await cache.refresh(["ABCD"])
    assert decisions["ABCD"].freeze_buys is True
    assert cache.get("ABCD") is not None
    assert cache.frozen_symbols() == ["ABCD"]
    # second refresh hits cache: no new SEC call
    stub = cache.sec
    assert isinstance(stub, StubSec)
    await cache.refresh(["ABCD"])
    assert stub.calls == 1


@pytest.mark.asyncio
async def test_filings_cache_expired_refetches() -> None:
    cache = FilingsCache(sec_provider=StubSec([_s1()]), ttl_seconds=0)
    await cache.refresh(["ABCD"])
    assert cache.get("ABCD") is None  # instantly stale
    assert cache.frozen_symbols() == []


@pytest.mark.asyncio
async def test_monitor_freezes_buys_on_live_s1() -> None:
    provider = MockMarketDataProvider()
    provider.set_quote("ABCD", 4.50)
    svc = MonitorService(market_data_provider=provider, sec_provider=StubSec([_s1()]))
    results = await svc.run_once(["ABCD"])
    assert results[0].action == "hold"
    assert any("S-1" in r for r in results[0].reasons)


@pytest.mark.asyncio
async def test_sync_filings_fast_job(tmp_path) -> None:
    from app.core.database import DatabaseManager
    from app.jobs.filings import sync_lists
    from app.repositories import WatchlistRepository

    db = DatabaseManager(database_url=f"sqlite+aiosqlite:///{tmp_path}/f.db")
    await db.create_tables()
    # point the global manager at our in-memory DB for the job
    import app.jobs.filings as filings_mod

    orig_manager = filings_mod.get_db_manager
    filings_mod.get_db_manager = lambda: db  # type: ignore[assignment]
    cache = get_filings_cache()
    orig_sec = cache.sec
    cache.sec = StubSec([_s1()])  # type: ignore[assignment]
    try:
        async with db.session() as session:
            await WatchlistRepository(session).add("ABCD", "u1", "l1")
        summary = await sync_lists()
        assert summary["symbols"] == 1
        assert summary["frozen"] == ["ABCD"]
    finally:
        filings_mod.get_db_manager = orig_manager
        cache.sec = orig_sec
        cache._cache.clear()
        await db.close()


class IntradayProvider(MockMarketDataProvider):
    """6 sessions x 30 bars ending now; latest runs 3x hotter."""

    async def get_bars(self, symbol, timeframe, start, end=None, limit=None):  # type: ignore[no-untyped-def]
        from datetime import timedelta as _td

        bars = []
        now = datetime.now(UTC)
        for d in range(5, -1, -1):
            end_ts = now - _td(days=d)
            hot = d == 0
            for i in range(30):
                ts = end_ts - _td(minutes=5 * (29 - i))
                vol = 300_000 if hot else 100_000
                bars.append(
                    Bar(
                        symbol=symbol,
                        timestamp=ts,
                        open=Decimal("2.0"),
                        high=Decimal("2.05"),
                        low=Decimal("1.95"),
                        close=Decimal("2.0"),
                        volume=vol,
                        provider=self.name,
                        timeframe="5m",
                    )
                )
        return bars


@pytest.mark.asyncio
async def test_same_time_rvol_uses_intraday() -> None:
    svc = MonitorService(market_data_provider=IntradayProvider())
    rvol, source = await svc._same_time_rvol("ABCD")
    assert source == "intraday-5m"
    assert rvol is not None and rvol == pytest.approx(3.0, rel=0.2)


@pytest.mark.asyncio
async def test_mock_get_bars_deterministic() -> None:
    p = MockMarketDataProvider()
    start = datetime.now(UTC) - timedelta(days=7)
    bars = await p.get_bars("ABCD", "5m", start=start)
    assert len(bars) == 150
    again = await p.get_bars("ABCD", "5m", start=start)
    assert [b.volume for b in bars] == [b.volume for b in again]
    limited = await p.get_bars("ABCD", "5m", start=start, limit=10)
    assert len(limited) == 10
