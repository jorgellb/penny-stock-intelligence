"""Integration: batched universe scan (seeded master + stub provider)."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.core.database import DatabaseManager, get_session
from app.domain.models import DataProvider
from app.main import app
from app.repositories import SecurityRepository
from app.scanners.universe_scan import fetch_market, load_candidates, scan_universe


def _db(tmp_path) -> DatabaseManager:  # type: ignore[no-untyped-def]
    return DatabaseManager(database_url=f"sqlite+aiosqlite:///{tmp_path}/s.db")


async def _seed(db: DatabaseManager) -> None:
    await db.create_tables()
    async with db.session() as session:
        repo = SecurityRepository(session)
        await repo.upsert("ABCD", "NASDAQ", "A B C", is_etf=False)
        await repo.upsert("EFGH", "NYSE", "E F G", is_etf=False)
        await repo.upsert("QQQ", "NASDAQ", "ETF", is_etf=True)


class _StubProvider:
    name = DataProvider.YFINANCE

    async def get_quote(self, symbol):  # type: ignore[no-untyped-def]
        from app.domain.models import Quote

        price = {"ABCD": 2.0, "EFGH": 50.0}.get(symbol, 1.0)
        return Quote(
            symbol=symbol,
            bid=Decimal(str(price - 0.01)),
            ask=Decimal(str(price + 0.01)),
            last=Decimal(str(price)),
            timestamp=datetime.now(UTC),
            provider=self.name,
        )

    async def get_daily_bars(self, symbol, start, **kw):  # type: ignore[no-untyped-def]
        from app.domain.models import DailyBar

        return [
            DailyBar(
                symbol=symbol,
                date=datetime.now(UTC),
                open=Decimal("1.9"),
                high=Decimal("2.1"),
                low=Decimal("1.8"),
                close=Decimal("2.0"),
                volume=1_000_000,
                provider=self.name,
            )
        ]


@pytest.mark.asyncio
async def test_load_and_scan(tmp_path) -> None:
    db = _db(tmp_path)
    await _seed(db)
    async with db.session() as session:
        cands = await load_candidates(session, limit=10)
        assert [c["symbol"] for c in cands] == ["ABCD", "EFGH"]  # ETF out
        out = await scan_universe(session, _StubProvider(), limit=10)
    assert out["total"] == 2
    assert out["eligible_count"] == 1  # EFGH $50 out of range
    assert out["eligible"][0]["symbol"] == "ABCD"
    assert out["eligible"][0]["dollar_volume"] == 2.0 * 1_000_000
    excluded = {e["symbol"]: e["reasons"] for e in out["excluded"]}
    assert "above_max_price" in excluded["EFGH"]
    assert out["stats"]["fetched"] == 2
    await db.close()


@pytest.mark.asyncio
async def test_budget_caps_requests(tmp_path) -> None:
    db = _db(tmp_path)
    await _seed(db)
    async with db.session() as session:
        cands = await load_candidates(session, limit=10)
        quotes, stats = await fetch_market(_StubProvider(), [c["symbol"] for c in cands], budget=1)
    assert stats["spent"] <= 2  # budget=1: quote for first symbol, no bars
    assert len(quotes) <= 1
    await db.close()


@pytest.mark.asyncio
async def test_universe_endpoint(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = _db(tmp_path)
    await _seed(db)

    import app.providers.market_data as md_mod

    monkeypatch.setattr(md_mod, "YFinanceMarketDataProvider", lambda: _StubProvider())

    async def _override():  # type: ignore[no-untyped-def]
        async with db.session() as session:
            yield session

    app.dependency_overrides[get_session] = _override
    try:
        c = TestClient(app, raise_server_exceptions=False)
        body = c.get("/api/v1/universe?limit=10").json()
        assert body["eligible_count"] == 1
        assert body["eligible"][0]["symbol"] == "ABCD"
    finally:
        app.dependency_overrides.pop(get_session, None)
    await db.close()
