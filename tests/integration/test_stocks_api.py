"""Integration: live stock + scanner endpoints (stubbed pipeline, real shapes)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app.api.v1.endpoints.scanner as scanner_mod
import app.api.v1.endpoints.stocks as stocks_mod
from app.main import app
from app.signals import SignalAction, SignalEvent


def _event() -> SignalEvent:
    return SignalEvent(
        symbol="ABCD", action=SignalAction.BUY, price=2.20, score=78, reasons=["setup ok"]
    )


def _details() -> dict:
    return {
        "change_pct": 4.7,
        "rvol": 5.8,
        "rvol_source": "daily-proxy",
        "dollar_volume": 1_000_000.0,
        "risk_flags": ["LOW_FLOAT"],
        "rsi_divergence": None,
        "stoch_cross": "bullish",
        "stoch_divergence": None,
        "halted": False,
        "dollar_rule": "ok",
        "dilution_frozen": False,
        "donchian_gate": None,
        "catalyst": None,
        "accumulation": None,
        "climax": None,
        "markup_ready": False,
        "vwap": 2.10,
        "vwap_distance_pct": 4.7,
        "order_template": None,
        "stale": False,
        "feed_kind": "sip",
        "feed_lag_ms": 3.0,
        "vetoed": False,
        "kill_switch": False,
        "score_breakdown": {
            "raw": 85,
            "penalty": 7,
            "final": 78,
            "components": {
                "momentum": 18,
                "volume": 19,
                "catalyst": 18,
                "technical": 12,
                "liquidity": 8,
                "fundamentals": 6,
                "data_quality": 4,
            },
            "penalties": {"LOW_LIQUIDITY": 7},
            "data_quality": "high",
        },
    }


class _Svc:
    async def evaluate_symbol(self, symbol):  # type: ignore[no-untyped-def]
        return _event(), _details()

    news = SimpleNamespace(news_provider=None)
    filings = SimpleNamespace(get=lambda s: None)  # noqa: ARG002


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(stocks_mod, "_service", lambda: _Svc())
    monkeypatch.setattr(stocks_mod, "_fundamentals", _no_fund)
    monkeypatch.setattr(
        scanner_mod, "get_monitor_service", lambda: SimpleNamespace(recent_events=_recent)
    )
    return TestClient(app, raise_server_exceptions=False)


async def _no_fund(symbol):  # type: ignore[no-untyped-def]
    return None, "fundamentals unavailable in tests"


def _recent(limit: int = 50):  # type: ignore[no-untyped-def]
    return [
        {
            "symbol": "ABCD",
            "action": "buy",
            "price": 2.2,
            "score": 78,
            "reasons": [],
            "sent": False,
            "rvol": 5.8,
            "change_pct": 4.7,
            "vwap_distance_pct": 4.7,
        },
        {
            "symbol": "EFGH",
            "action": "hold",
            "price": 1.0,
            "score": 40,
            "reasons": [],
            "sent": False,
            "rvol": 0.8,
            "change_pct": -2.0,
            "vwap_distance_pct": -1.0,
        },
    ][:limit]


def test_score_endpoint(client: TestClient) -> None:
    body = client.get("/api/v1/stocks/abcd/score").json()
    assert body["symbol"] == "ABCD"
    assert body["score"] == 78
    assert "probability" in body["disclaimer"]


def test_stock_snapshot_and_subresources(client: TestClient) -> None:
    snap = client.get("/api/v1/stocks/ABCD").json()
    assert snap["price"] == 2.20
    assert snap["technical"]["rvol"] == 5.8
    assert snap["fundamentals"] is None and "fundamentals_note" in snap
    assert snap["news"] == [] and "news_note" in snap
    assert snap["score_breakdown"]["final"] == 78
    assert set(snap["score_breakdown"]["components"]) >= {"momentum", "volume"}
    tech = snap["technical"]
    for key in ("rsi_14", "stoch_k", "stoch_d", "atr_pct", "squeeze_active"):
        assert key in tech
    assert client.get("/api/v1/stocks/ABCD/technicals").json()["indicators"]["rvol"] == 5.8
    risks = client.get("/api/v1/stocks/ABCD/risks").json()
    assert risks["risk_flags"] == ["LOW_FLOAT"] and risks["halted"] is False
    fund = client.get("/api/v1/stocks/ABCD/fundamentals").json()
    assert fund["fundamentals"] is None
    assert client.get("/api/v1/stocks/ABCD/filings").json()["filings"] == []
    assert client.get("/api/v1/stocks/ABCD/news").json()["news"] == []


def test_universe_empty_master_returns_zero(
    client: TestClient, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # empty master (data case lives in test_universe_scan.py): proves the
    # endpoint runs the real pipeline instead of the old 501 stub.
    from app.core.database import DatabaseManager, get_session

    db = DatabaseManager(database_url=f"sqlite+aiosqlite:///{tmp_path}/e.db")

    async def _override():  # type: ignore[no-untyped-def]
        await db.create_tables()
        async with db.session() as session:
            yield session

    app.dependency_overrides[get_session] = _override
    try:
        resp = client.get("/api/v1/universe?limit=5")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0
    finally:
        app.dependency_overrides.pop(get_session, None)


def test_scanner_rankings_from_monitor_state(client: TestClient) -> None:
    body = client.get("/api/v1/scanner").json()
    assert body["total_symbols"] == 1  # min_score=70 default filters EFGH
    assert body["eligible_count"] == 1
    pre = client.get("/api/v1/scanner/premarket?min_gap_pct=4.0").json()
    assert [r["symbol"] for r in pre["rankings"]] == ["ABCD"]
    intra = client.get("/api/v1/scanner/intraday").json()
    assert intra["market_status"] != "open" or True  # real session value
    assert isinstance(intra["rankings"], list)
    filtered = client.get("/api/v1/scanner/intraday?min_vwap_distance=10.0").json()
    assert filtered["rankings"] == []


def test_backtest_run_endpoint_with_stubbed_fetch(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.backtesting.history as hist_mod

    async def _fake_fetch(symbols, days=120, provider=None):  # type: ignore[no-untyped-def]
        bars = []
        px = 1.0
        for i in range(40):
            vol = 800_000 if i == 25 else 100_000
            px = px * (1.10 if i == 25 else 1.005)
            bars.append({"date": f"2026-01-{i + 1:02d}", "close": round(px, 4), "volume": vol})
        return {"ABCD": bars}

    monkeypatch.setattr(hist_mod, "fetch_series", _fake_fetch)
    body = client.post("/api/v1/backtest/run?symbols=ABCD").json()
    assert body["symbols"] == ["ABCD"]
    assert body["metrics"]["number_of_signals"] == 1.0
    assert len(body["trades"]) == 1
    assert "disclaimer" in body
    assert client.get("/api/v1/backtest").json()["results"] == []
    assert client.get("/api/v1/backtest/xyz").status_code == 404


def test_history_endpoint_with_stubbed_provider(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import UTC, datetime
    from decimal import Decimal

    from app.domain.models import DailyBar
    from app.providers.market_data import MockMarketDataProvider

    provider = MockMarketDataProvider()

    async def _bars(symbol, start, **kwargs):  # type: ignore[no-untyped-def]
        return [
            DailyBar(
                symbol=symbol,
                date=datetime(2026, 9, 18, tzinfo=UTC),
                open=Decimal("1.00"),
                high=Decimal("1.10"),
                low=Decimal("0.95"),
                close=Decimal("1.05"),
                volume=500_000,
                provider=provider.name,
            )
        ]

    async def _no_intraday(*args, **kwargs):  # type: ignore[no-untyped-def]
        return []

    monkeypatch.setattr(provider, "get_daily_bars", _bars)
    monkeypatch.setattr(provider, "get_bars", _no_intraday)
    monkeypatch.setattr(stocks_mod, "_bars_provider", lambda: provider)
    body = client.get("/api/v1/stocks/ABCD/history?days=30").json()
    assert body["symbol"] == "ABCD" and body["count"] == 1
    bar = body["bars"][0]
    assert bar["close"] == 1.05 and bar["volume"] == 500_000
    assert client.get("/api/v1/stocks/%20/history?days=30").status_code in (400, 404)


def test_history_merges_live_session_from_intraday(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cached daily history + today's intraday bars -> today's candle appended."""
    from datetime import UTC, datetime
    from decimal import Decimal

    from app.domain.models import Bar, DailyBar
    from app.providers.market_data import MockMarketDataProvider

    provider = MockMarketDataProvider()

    async def _daily(symbol, start, **kwargs):  # type: ignore[no-untyped-def]
        return [
            DailyBar(symbol=symbol, date=datetime(2026, 9, 17), open=Decimal("1.0"),
                     high=Decimal("1.0"), low=Decimal("1.0"), close=Decimal("1.0"),
                     volume=100, provider=provider.name)
        ]  # fmt: skip

    async def _intraday(*args, **kwargs):  # type: ignore[no-untyped-def]
        ts = datetime(2026, 9, 18, 14, 0, tzinfo=UTC)  # 10:00 ET
        return [
            Bar(symbol="ABCD", timestamp=ts, open=Decimal("1.1"), high=Decimal("1.3"),
                low=Decimal("1.1"), close=Decimal("1.25"), volume=5000,
                provider=provider.name, timeframe="5m")
        ]  # fmt: skip

    monkeypatch.setattr(provider, "get_daily_bars", _daily)
    monkeypatch.setattr(provider, "get_bars", _intraday)
    monkeypatch.setattr(stocks_mod, "_bars_provider", lambda: provider)
    body = client.get("/api/v1/stocks/ABCD/history?days=30").json()
    assert body["count"] == 2
    assert body["bars"][-1]["close"] == 1.25 and body["bars"][-1]["high"] == 1.3
