"""Integration: circuit-breaker audit trail persisted + served."""

from __future__ import annotations

import pytest

from app.core.database import DatabaseManager, get_session
from app.jobs.monitor import MonitorService
from app.main import app
from app.providers.market_data import MockMarketDataProvider
from app.repositories import CircuitEventRepository
from app.signals import SignalAction, SignalEvent


def _db(tmp_path) -> DatabaseManager:  # type: ignore[no-untyped-def]
    return DatabaseManager(database_url=f"sqlite+aiosqlite:///{tmp_path}/c.db")


@pytest.mark.asyncio
async def test_circuit_repository_roundtrip(tmp_path) -> None:
    db = _db(tmp_path)
    await db.create_tables()
    async with db.session() as session:
        repo = CircuitEventRepository(session)
        assert await repo.save_batch([]) == 0
        assert (
            await repo.save_batch(
                [
                    {"level": "symbol", "key": "AAA", "reason": "veto 24h"},
                    {"level": "portfolio", "key": "ALL", "reason": "kill"},
                ]
            )
            == 2
        )
        assert len(await repo.recent()) == 2
        assert len(await repo.recent(level="symbol")) == 1
        assert (await repo.recent(level="symbol"))[0].key == "AAA"
    await db.close()


def _buy(symbol: str, change: float) -> tuple[SignalEvent, dict]:
    return (
        SignalEvent(symbol=symbol, action=SignalAction.BUY, price=2.0, score=85, reasons=["setup"]),
        {
            "change_pct": change,
            "rvol": 5.0,
            "vwap_distance_pct": 1.0,
            "halted": False,
            "risk_flags": [],
            "catalyst": None,
            "returns_5m": None,
            "order_template": None,
        },
    )


@pytest.mark.asyncio
async def test_run_once_persists_symbol_trip(tmp_path, monkeypatch) -> None:
    db = _db(tmp_path)
    await db.create_tables()
    import app.jobs.monitor.persistence as persist_mod
    import app.jobs.monitor.service as svc_mod

    monkeypatch.setattr(persist_mod, "get_db_manager", lambda: db)
    monkeypatch.setattr(svc_mod, "get_db_manager", lambda: db)
    svc = MonitorService(market_data_provider=MockMarketDataProvider())
    canned = {"AAA": _buy("AAA", 1.0), "BBB": _buy("BBB", 1.0), "CCC": _buy("CCC", -9.0)}

    async def _fake(symbol: str):  # type: ignore[no-untyped-def]
        return canned[symbol]

    svc.evaluate_symbol = _fake  # type: ignore[method-assign]
    out = await svc.run_once(["AAA", "BBB", "CCC"])
    assert {e.symbol: e.action for e in out}["CCC"] == "hold"
    async with db.session() as session:
        rows = await CircuitEventRepository(session).recent()
        assert len(rows) == 1
        assert rows[0].level == "symbol" and rows[0].key == "CCC"
    await db.close()


@pytest.mark.asyncio
async def test_circuits_endpoint_reads_db(tmp_path) -> None:
    from fastapi.testclient import TestClient

    db = _db(tmp_path)
    await db.create_tables()
    async with db.session() as session:
        await CircuitEventRepository(session).save_batch(
            [{"level": "symbol", "key": "AAA", "reason": "veto"}]
        )

    async def _override():  # type: ignore[no-untyped-def]
        async with db.session() as session:
            yield session

    app.dependency_overrides[get_session] = _override
    try:
        c = TestClient(app, raise_server_exceptions=False)
        body = c.get("/api/v1/monitor/circuits").json()
        assert body["count"] == 1
        assert body["events"][0]["key"] == "AAA"
        assert c.get("/api/v1/monitor/circuits?level=portfolio").json()["count"] == 0
    finally:
        app.dependency_overrides.pop(get_session, None)
    await db.close()
