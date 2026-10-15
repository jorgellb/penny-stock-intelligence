"""Integration: sync_universe persists Nasdaq Trader listings (offline)."""

import pytest

import app.jobs as jobs_mod
from app.core.database import DatabaseManager
from app.providers.market_data.nasdaq_listings import parse_nasdaq_file, parse_other_file
from app.repositories import SecurityRepository
from tests.unit.test_listings import NASDAQ_SAMPLE, OTHER_SAMPLE


def _db(tmp_path) -> DatabaseManager:  # type: ignore[no-untyped-def]
    return DatabaseManager(database_url=f"sqlite+aiosqlite:///{tmp_path}/u.db")


@pytest.mark.asyncio
async def test_sync_universe_persists_listings(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    rows = parse_nasdaq_file(NASDAQ_SAMPLE) + parse_other_file(OTHER_SAMPLE)

    async def _fake_fetch(client=None):  # type: ignore[no-untyped-def]
        return rows

    import app.providers.market_data.nasdaq_listings as listings_mod

    monkeypatch.setattr(listings_mod, "fetch_listings", _fake_fetch)
    db = _db(tmp_path)
    import app.core.database as db_mod

    monkeypatch.setattr(db_mod, "get_db_manager", lambda: db)

    out = await jobs_mod.sync_universe()
    assert out.get("saved", 0) >= 2
    async with db.session() as session:
        actives = await SecurityRepository(session).list_active(limit=5000)
        syms = sorted(s.symbol for s in actives)
        assert "AAPL" in syms and "AA" in syms
        assert "QQQ" not in syms  # ETF excluded by default config
        assert "ZZZT" not in syms  # test issue dropped
    # idempotent re-run (upsert, no duplicates)
    out2 = await jobs_mod.sync_universe()
    assert out2["saved"] == out["saved"]
    async with db.session() as session:
        assert len(await SecurityRepository(session).list_active(limit=5000)) == len(syms)
    await db.close()


@pytest.mark.asyncio
async def test_sync_universe_fail_soft(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.providers.market_data.nasdaq_listings as listings_mod

    async def _boom(client=None):  # type: ignore[no-untyped-def]
        raise RuntimeError("offline")

    monkeypatch.setattr(listings_mod, "fetch_listings", _boom)
    out = await jobs_mod.sync_universe()
    assert "saved" in out or "error" in out
