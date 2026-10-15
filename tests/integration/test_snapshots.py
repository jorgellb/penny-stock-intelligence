"""Integration: monitor snapshots + run rows persisted + served."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import config_fingerprint, get_settings
from app.core.database import DatabaseManager, get_session
from app.jobs.monitor import MonitorService
from app.main import app
from app.providers.market_data import MockMarketDataProvider
from app.repositories import MonitorSnapshotRepository
from app.signals import SignalAction, SignalEvent


def _db(tmp_path) -> DatabaseManager:  # type: ignore[no-untyped-def]
    return DatabaseManager(database_url=f"sqlite+aiosqlite:///{tmp_path}/n.db")


def test_fingerprint_stable_and_sensitive() -> None:
    assert config_fingerprint() == config_fingerprint()
    assert len(config_fingerprint()) == 64
    s = get_settings()
    before = config_fingerprint(s)
    old = s.monitor.buy_min_score
    s.monitor.buy_min_score = old + 1
    try:
        assert config_fingerprint(s) != before
    finally:
        s.monitor.buy_min_score = old


def _canned(symbol: str) -> tuple[SignalEvent, dict]:
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


@pytest.mark.asyncio
async def test_run_once_persists_snapshots_and_run(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = _db(tmp_path)
    await db.create_tables()
    import app.jobs.monitor.persistence as persist_mod
    import app.jobs.monitor.service as svc_mod

    monkeypatch.setattr(persist_mod, "get_db_manager", lambda: db)
    monkeypatch.setattr(svc_mod, "get_db_manager", lambda: db)
    svc = MonitorService(market_data_provider=MockMarketDataProvider())

    async def _fake(symbol: str):  # type: ignore[no-untyped-def]
        return _canned(symbol)

    svc.evaluate_symbol = _fake  # type: ignore[method-assign]
    out = await svc.run_once(["AAA", "BBB"])
    assert len(out) == 2
    async with db.session() as session:
        snaps = await MonitorSnapshotRepository(session).recent()
        assert len(snaps) == 2
        assert snaps[0].regime == svc.last_regime
        assert snaps[0].config_hash == config_fingerprint()
        assert (await MonitorSnapshotRepository(session).recent(symbol="aaa")) != []
        from app.models import ScannerSnapshots

        runs = (await session.execute(select(ScannerSnapshots))).scalars().all()
        assert len(runs) == 1
        assert runs[0].run_type == "monitor" and runs[0].symbols_scanned == 2
    await db.close()


@pytest.mark.asyncio
async def test_snapshots_endpoint(tmp_path) -> None:
    c = TestClient(app, raise_server_exceptions=False)
    db = _db(tmp_path)
    await db.create_tables()
    async with db.session() as session:
        await MonitorSnapshotRepository(session).save_batch(
            [
                {
                    "symbol": "AAA",
                    "action": "buy",
                    "score": 80,
                    "price": 2.0,
                    "change_pct": 2.0,
                    "rvol": 5.0,
                    "vwap_distance_pct": 1.0,
                    "risk_flags": [],
                    "regime": "risk_on",
                    "config_hash": "abc",
                }
            ]
        )

    async def _override():  # type: ignore[no-untyped-def]
        async with db.session() as session:
            yield session

    app.dependency_overrides[get_session] = _override
    try:
        body = c.get("/api/v1/monitor/snapshots").json()
        assert body["count"] == 1
        assert body["snapshots"][0]["config_hash"] == "abc"
        assert "return" not in body["snapshots"][0]  # no future targets, ever
        assert c.get("/api/v1/monitor/snapshots?symbol=zzz").json()["count"] == 0
    finally:
        app.dependency_overrides.pop(get_session, None)
    await db.close()
