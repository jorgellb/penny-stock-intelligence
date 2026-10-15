"""Integration: persistent lists + realtime monitor pass with mock data."""

import pytest

from app.core.database import DatabaseManager
from app.jobs.monitor import MonitorService
from app.providers.market_data import MockMarketDataProvider
from app.repositories import WatchlistRepository


@pytest.mark.asyncio
async def test_watchlist_repository_crud(tmp_path) -> None:
    db = DatabaseManager(database_url=f"sqlite+aiosqlite:///{tmp_path}/m.db")
    await db.create_tables()
    async with db.session() as session:
        repo = WatchlistRepository(session)
        item, created = await repo.add("abcd", "u1", "biotech")
        assert created is True
        assert item.symbol == "ABCD"
        _, created2 = await repo.add("ABCD", "u1", "biotech")
        assert created2 is False
        await repo.add("EFGH", "u1", "biotech")
        assert await repo.symbols("u1", "biotech") == ["ABCD", "EFGH"]
        lists = await repo.lists("u1")
        assert lists == [{"name": "biotech", "count": 2}]
        assert await repo.remove("abcd", "u1", "biotech") is True
        assert await repo.remove("abcd", "u1", "biotech") is False
        assert await repo.delete_list("u1", "biotech") == 1
        assert await repo.lists("u1") == []
        with pytest.raises(ValueError):
            await repo.add("   ", "u1", "biotech")
    await db.close()


@pytest.mark.asyncio
async def test_monitor_run_once_with_mock() -> None:
    provider = MockMarketDataProvider()
    provider.set_quote("ABCD", 2.20)
    svc = MonitorService(market_data_provider=provider)
    results = await svc.run_once(["ABCD"])
    assert len(results) == 1
    assert results[0].symbol == "ABCD"
    assert svc.last_stats["symbols"] == 1
    assert svc.status()["tracked_symbols"] == 1
    assert len(svc.recent_events()) == 1


@pytest.mark.asyncio
async def test_monitor_state_tracks_score_drops() -> None:
    provider = MockMarketDataProvider()
    provider.set_quote("ABCD", 2.20)
    svc = MonitorService(market_data_provider=provider)
    first = await svc.run_once(["ABCD"])
    second = await svc.run_once(["ABCD"])
    assert first[0].score == second[0].score  # deterministic same input
    assert svc.state["ABCD"].score == second[0].score


@pytest.mark.asyncio
async def test_monitor_never_crashes_on_bad_symbol() -> None:
    class BoomProvider(MockMarketDataProvider):
        async def get_quote(self, symbol: str):  # type: ignore[no-untyped-def]
            raise RuntimeError("boom")

    svc = MonitorService(market_data_provider=BoomProvider())
    assert await svc.run_once(["ZZZ"]) == []


@pytest.mark.asyncio
async def test_monitor_halt_freezes_signals() -> None:
    provider = MockMarketDataProvider()
    provider.set_quote("ABCD", 2.20)
    svc = MonitorService(market_data_provider=provider)
    svc.halts.report_halt("ABCD")
    results = await svc.run_once(["ABCD"])
    assert results[0].action == "hold"
    assert any("halt" in r for r in results[0].reasons)


@pytest.mark.asyncio
async def test_monitor_dollar_rule_blocks_buys() -> None:
    provider = MockMarketDataProvider()
    provider.set_quote("ABCD", 0.85)
    svc = MonitorService(market_data_provider=provider)
    for _ in range(150):
        svc.dollar_rule.update("ABCD", 0.85)
    results = await svc.run_once(["ABCD"])
    assert results[0].action == "hold"
    assert any("$1" in r for r in results[0].reasons)


class VwapProvider(MockMarketDataProvider):
    """Flat 5m session at VWAP 2.00; quote is set per round."""

    async def get_bars(self, symbol, timeframe, start, end=None, limit=None):  # type: ignore[no-untyped-def]
        from datetime import timedelta as _td
        from decimal import Decimal as _D

        from app.domain.models import Bar as _Bar

        now = __import__("datetime").datetime.now(__import__("datetime").UTC)
        return [
            _Bar(
                symbol=symbol,
                timestamp=now - _td(minutes=5 * i),
                open=_D("2.0"),
                high=_D("2.05"),
                low=_D("1.95"),
                close=_D("2.0"),
                volume=100_000,
                provider=self.name,
                timeframe="5m",
            )
            for i in range(30, 0, -1)
        ]


@pytest.mark.asyncio
async def test_monitor_vwap_loss_triggers_sell() -> None:
    provider = VwapProvider()
    provider.set_quote("ABCD", 2.10)  # +5% over VWAP 2.00
    svc = MonitorService(market_data_provider=provider)
    first, details = await svc.evaluate_symbol("ABCD")
    assert details["vwap"] == 2.0
    assert details["vwap_distance_pct"] == 5.0
    assert svc.state["ABCD"].above_vwap is True
    provider.set_quote("ABCD", 1.90)  # -5% under VWAP
    second, _ = await svc.evaluate_symbol("ABCD")
    assert second.action.value == "sell"
    assert any("VWAP" in r for r in second.reasons)


def _fake_hold(symbol: str):  # type: ignore[no-untyped-def]
    """Deterministic HOLD evaluation isolating round-level overlays."""
    from app.signals import SignalEvent

    async def _eval(sym: str):  # type: ignore[no-untyped-def]
        from app.signals import SignalAction

        ev = SignalEvent(
            symbol=sym, action=SignalAction.HOLD, price=2.60, score=50, reasons=["flat"]
        )
        details = {
            "change_pct": 5.0,
            "rvol": 1.0,
            "halted": False,
            "returns_5m": None,
            "vwap_distance_pct": 1.0,
            "spread_pct": 1.0,
            "order_template": None,
            "risk_flags": [],
        }
        return ev, details

    return _eval


@pytest.mark.asyncio
async def test_monitor_take_profit_exit() -> None:
    from app.config import get_settings

    provider = MockMarketDataProvider()
    svc = MonitorService(market_data_provider=provider)
    assert svc.paper.on_buy("ABCD", 2.00, shares=100) is not None
    svc.evaluate_symbol = _fake_hold("ABCD")  # type: ignore[method-assign]
    settings = get_settings()
    old = settings.monitor.sell_take_profit_pct
    settings.monitor.sell_take_profit_pct = 15.0
    try:
        results = await svc.run_once(["ABCD"])
    finally:
        settings.monitor.sell_take_profit_pct = old
    assert results[0].action == "sell"
    assert any("take-profit" in r for r in results[0].reasons)


@pytest.mark.asyncio
async def test_monitor_stop_loss_exit() -> None:
    from app.config import get_settings

    provider = MockMarketDataProvider()
    svc = MonitorService(market_data_provider=provider)
    assert svc.paper.on_buy("ABCD", 2.00, shares=100) is not None

    async def _eval(sym: str):  # type: ignore[no-untyped-def]
        from app.signals import SignalAction, SignalEvent

        ev = SignalEvent(
            symbol=sym, action=SignalAction.HOLD, price=1.80, score=50, reasons=["flat"]
        )
        details = {
            "change_pct": -10.0,
            "rvol": 1.0,
            "halted": False,
            "returns_5m": None,
            "vwap_distance_pct": -1.0,
            "spread_pct": 1.0,
            "order_template": None,
            "risk_flags": [],
        }
        return ev, details

    svc.evaluate_symbol = _eval  # type: ignore[method-assign]
    settings = get_settings()
    old = settings.monitor.sell_stop_loss_pct
    settings.monitor.sell_stop_loss_pct = 8.0
    try:
        results = await svc.run_once(["ABCD"])
    finally:
        settings.monitor.sell_stop_loss_pct = old
    assert results[0].action == "sell"
    assert any("stop-loss" in r for r in results[0].reasons)


@pytest.mark.asyncio
async def test_monitor_max_buys_per_round_cap() -> None:
    from app.config import get_settings

    async def _eval(sym: str):  # type: ignore[no-untyped-def]
        from app.signals import SignalAction, SignalEvent

        scores = {"A1": 90, "A2": 80, "A3": 70}
        ev = SignalEvent(
            symbol=sym,
            action=SignalAction.BUY,
            price=2.00,
            score=scores[sym],
            reasons=["setup"],
        )
        details = {
            "change_pct": 5.0,
            "rvol": 5.0,
            "halted": False,
            "returns_5m": None,
            "vwap_distance_pct": 1.0,
            "spread_pct": 1.0,
            "order_template": None,
            "risk_flags": [],
        }
        return ev, details

    provider = MockMarketDataProvider()
    svc = MonitorService(market_data_provider=provider)
    svc.evaluate_symbol = _eval  # type: ignore[method-assign]
    settings = get_settings()
    old = settings.monitor.max_buys_per_round
    settings.monitor.max_buys_per_round = 2
    try:
        results = await svc.run_once(["A1", "A2", "A3"])
    finally:
        settings.monitor.max_buys_per_round = old
    by_sym = {r.symbol: r for r in results}
    assert by_sym["A1"].action == "buy"
    assert by_sym["A2"].action == "buy"
    assert by_sym["A3"].action == "hold"
    assert any("límite" in r for r in by_sym["A3"].reasons)
    assert svc.last_stats["buys_capped"] == 1


@pytest.mark.asyncio
async def test_fetch_market_requests_history_window() -> None:
    """Regression: live indicators need months of daily bars, not today only."""
    from datetime import UTC, datetime

    captured: dict = {}

    class CaptureProvider(MockMarketDataProvider):
        async def get_daily_bars(  # type: ignore[no-untyped-def]
            self, symbol, start, end=None, limit=None, adjusted=True
        ):
            captured["start"] = start
            return await super().get_daily_bars(symbol, start, end, limit, adjusted)

    svc = MonitorService(market_data_provider=CaptureProvider())
    await svc.evaluate_symbol("ABCD")
    assert (datetime.now(UTC) - captured["start"]).days >= 200
