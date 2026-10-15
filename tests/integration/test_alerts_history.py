"""Integration: alert history persisted by the monitor, served by /alerts."""

import pytest

from app.core.database import DatabaseManager, get_session
from app.jobs.monitor import MonitoredEvent, MonitorService
from app.main import app
from app.providers.market_data import MockMarketDataProvider
from app.repositories import AlertRepository


def _db(tmp_path) -> DatabaseManager:  # type: ignore[no-untyped-def]
    return DatabaseManager(database_url=f"sqlite+aiosqlite:///{tmp_path}/t.db")


@pytest.mark.asyncio
async def test_repository_save_and_filters(tmp_path) -> None:
    db = _db(tmp_path)
    await db.create_tables()
    async with db.session() as session:
        repo = AlertRepository(session)
        await repo.save(
            symbol="abcd",
            action="buy",
            signal_type="momentum",
            price=2.20,
            score=80,
            message="buy",
            risk_flags=["LOW_FLOAT"],
            sent=True,
            providers=["console"],
        )
        await repo.save(
            symbol="ABCD",
            action="sell",
            signal_type="reversal",
            price=1.90,
            score=40,
            message="sell",
            sent=False,
        )
        assert len(await repo.recent()) == 2
        assert len(await repo.recent(symbol="abcd")) == 2  # normalized
        assert len(await repo.recent(sent=True)) == 1
        assert len(await repo.recent(sent=False)) == 1
        assert (await repo.recent(sent=True))[0].action == "buy"
    await db.close()


@pytest.mark.asyncio
async def test_monitor_persists_actionable_events(tmp_path, monkeypatch) -> None:
    db = _db(tmp_path)
    await db.create_tables()
    import app.jobs.monitor.persistence as persist_mod
    import app.jobs.monitor.service as svc_mod

    monkeypatch.setattr(persist_mod, "get_db_manager", lambda: db)
    monkeypatch.setattr(svc_mod, "get_db_manager", lambda: db)
    svc = MonitorService(market_data_provider=MockMarketDataProvider())
    await svc._persist_events(
        [
            MonitoredEvent(
                symbol="ABCD",
                action="buy",
                price=2.2,
                score=80,
                reasons=["r1"],
                sent=True,
                risk_flags=["LOW_FLOAT"],
            ),
            MonitoredEvent(
                symbol="EFGH", action="hold", price=1.0, score=20, reasons=["x"], sent=False
            ),
        ]
    )
    async with db.session() as session:
        rows = await AlertRepository(session).recent()
        assert [r.symbol for r in rows] == ["ABCD"]  # hold stays in memory only
        assert rows[0].action == "buy" and rows[0].reasons == ["r1"]
    await db.close()


@pytest.mark.asyncio
async def test_alerts_endpoint_reads_db(tmp_path) -> None:
    from fastapi.testclient import TestClient

    db = _db(tmp_path)
    await db.create_tables()
    async with db.session() as session:
        await AlertRepository(session).save(
            symbol="ABCD",
            action="buy",
            signal_type="momentum",
            price=2.2,
            score=80,
            message="buy",
            sent=True,
        )

    async def _override():  # type: ignore[no-untyped-def]
        async with db.session() as session:
            yield session

    app.dependency_overrides[get_session] = _override
    try:
        c = TestClient(app, raise_server_exceptions=False)
        assert c.get("/api/v1/alerts").status_code == 200
        body = c.get("/api/v1/alerts").json()
        assert body["total"] == 1
        assert body["alerts"][0]["action"] == "buy"
        assert body["alerts"][0]["sent"] is True
        assert c.get("/api/v1/alerts?symbol=abcd").json()["total"] == 1
        assert c.get("/api/v1/alerts?symbol=ZZZ").json()["total"] == 0
        assert c.get("/api/v1/alerts?status=pending").json()["total"] == 0
        assert c.get("/api/v1/alerts?status=sent").json()["total"] == 1
    finally:
        app.dependency_overrides.pop(get_session, None)
    await db.close()
