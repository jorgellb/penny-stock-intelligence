"""Integration: paper-trade audit trail persisted + served."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.core.database import DatabaseManager, get_session
from app.jobs.monitor import MonitorService
from app.main import app
from app.providers.market_data import MockMarketDataProvider
from app.repositories import PaperPositionRepository, PaperTradeRepository
from app.risk.paper import PaperTracker, PaperTrade
from app.signals import SignalAction, SignalEvent


def _db(tmp_path) -> DatabaseManager:  # type: ignore[no-untyped-def]
    return DatabaseManager(database_url=f"sqlite+aiosqlite:///{tmp_path}/p.db")


def _trade() -> PaperTrade:
    now = datetime.now(UTC)
    return PaperTrade(
        symbol="ABCD",
        shares=100,
        entry_price=2.02,
        exit_price=2.18,
        entry_time=now,
        exit_time=now,
        pnl_dollars=16.0,
        pnl_pct=7.9,
    )


@pytest.mark.asyncio
async def test_paper_repository_roundtrip(tmp_path) -> None:
    db = _db(tmp_path)
    await db.create_tables()
    async with db.session() as session:
        repo = PaperTradeRepository(session)
        await repo.save(_trade())
        rows = await repo.recent()
        assert len(rows) == 1
        assert rows[0].symbol == "ABCD" and rows[0].pnl_dollars == 16.0
        assert await repo.recent(symbol="abcd") == rows
        assert await repo.recent(symbol="ZZZ") == []
    await db.close()


def _buy(symbol: str) -> tuple[SignalEvent, dict]:
    return (
        SignalEvent(symbol=symbol, action=SignalAction.BUY, price=2.0, score=85, reasons=["s"]),
        {
            "change_pct": 2.0,
            "rvol": 5.0,
            "vwap_distance_pct": 1.0,
            "halted": False,
            "risk_flags": [],
            "catalyst": None,
            "returns_5m": None,
            "order_template": None,
            "spread_pct": 1.0,
        },
    )


def _sell(symbol: str) -> tuple[SignalEvent, dict]:
    ev, det = _buy(symbol)
    ev.action = SignalAction.SELL
    ev.score = 40
    det["change_pct"] = -9.0
    det["vwap_distance_pct"] = -5.0
    return ev, det


@pytest.mark.asyncio
async def test_run_once_persists_close(tmp_path, monkeypatch) -> None:
    db = _db(tmp_path)
    await db.create_tables()
    import app.jobs.monitor.persistence as persist_mod
    import app.jobs.monitor.service as svc_mod

    monkeypatch.setattr(persist_mod, "get_db_manager", lambda: db)
    monkeypatch.setattr(svc_mod, "get_db_manager", lambda: db)
    svc = MonitorService(market_data_provider=MockMarketDataProvider())

    async def _fake_buy(symbol: str):  # type: ignore[no-untyped-def]
        return _buy(symbol)

    svc.evaluate_symbol = _fake_buy  # type: ignore[method-assign]
    out = await svc.run_once(["AAA"])
    assert out[0].action == "buy"
    assert svc.paper.summary()["open_positions"] == 1

    async def _fake_sell(symbol: str):  # type: ignore[no-untyped-def]
        return _sell(symbol)

    svc.evaluate_symbol = _fake_sell  # type: ignore[method-assign]
    out2 = await svc.run_once(["AAA"])
    assert out2[0].action == "sell"
    async with db.session() as session:
        rows = await PaperTradeRepository(session).recent()
        assert len(rows) == 1
        assert rows[0].symbol == "AAA" and rows[0].shares > 0
    await db.close()


@pytest.mark.asyncio
async def test_paper_endpoints(tmp_path) -> None:
    c = TestClient(app, raise_server_exceptions=False)
    db = _db(tmp_path)
    await db.create_tables()
    async with db.session() as session:
        await PaperTradeRepository(session).save(_trade())

    async def _override():  # type: ignore[no-untyped-def]
        async with db.session() as session:
            yield session

    app.dependency_overrides[get_session] = _override
    try:
        body = c.get("/api/v1/monitor/paper/trades").json()
        assert body["count"] == 1
        assert body["trades"][0]["pnl_dollars"] == 16.0
        assert c.get("/api/v1/monitor/paper/trades?symbol=zzz").json()["count"] == 0
        live = c.get("/api/v1/monitor/paper").json()
        assert "equity" in live and "open_positions" in live
    finally:
        app.dependency_overrides.pop(get_session, None)
    await db.close()


def test_tracker_summary_not_shared_between_instances() -> None:
    assert PaperTracker().summary()["open_positions"] == 0


@pytest.mark.asyncio
async def test_position_repository_upsert_remove(tmp_path) -> None:
    from datetime import UTC as _UTC
    from datetime import datetime as _dt

    db = _db(tmp_path)
    await db.create_tables()
    async with db.session() as session:
        repo = PaperPositionRepository(session)
        await repo.upsert("abcd", 100, 2.02, _dt.now(_UTC))
        await repo.upsert("ABCD", 50, 2.10, _dt.now(_UTC))  # same row updated
        rows = await repo.list_all()
        assert len(rows) == 1 and rows[0].shares == 50
        assert await repo.remove("abcd") is True
        assert await repo.remove("abcd") is False
        assert await repo.list_all() == []
    await db.close()


@pytest.mark.asyncio
async def test_open_position_survives_service_restart(tmp_path, monkeypatch) -> None:
    db = _db(tmp_path)
    await db.create_tables()
    import app.jobs.monitor.persistence as persist_mod
    import app.jobs.monitor.service as svc_mod

    monkeypatch.setattr(persist_mod, "get_db_manager", lambda: db)
    monkeypatch.setattr(svc_mod, "get_db_manager", lambda: db)

    async def _fake_buy(symbol):  # type: ignore[no-untyped-def]
        return _buy(symbol)

    svc = MonitorService(market_data_provider=MockMarketDataProvider())
    svc.evaluate_symbol = _fake_buy  # type: ignore[method-assign]
    out = await svc.run_once(["AAA"])
    assert out[0].action == "buy"
    async with db.session() as session:
        assert len(await PaperPositionRepository(session).list_all()) == 1

    # fresh service (restart): position restored, SELL closes original entry
    svc2 = MonitorService(market_data_provider=MockMarketDataProvider())
    assert svc2.paper.positions == {}

    async def _fake_sell(symbol):  # type: ignore[no-untyped-def]
        return _sell(symbol)

    svc2.evaluate_symbol = _fake_sell  # type: ignore[method-assign]
    out2 = await svc2.run_once(["AAA"])
    assert out2[0].action == "sell"
    assert "paper: cierra" in " ".join(out2[0].reasons)
    async with db.session() as session:
        assert await PaperPositionRepository(session).list_all() == []
        assert len(await PaperTradeRepository(session).recent()) == 1
    await db.close()
