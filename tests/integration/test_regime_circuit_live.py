"""Integration: regime gate + correlation filter + circuit breakers in run_once.

Uses a stubbed evaluate_symbol (deterministic BUY candidates) so the
round-level gates are tested in isolation from scoring randomness.
"""

from __future__ import annotations

import pytest

from app.config import get_settings
from app.jobs.monitor import MonitorService
from app.providers.market_data import MockMarketDataProvider
from app.signals import SignalAction, SignalEvent


def _buy(symbol: str, score: int, rvol: float, **over: object) -> tuple[SignalEvent, dict]:
    event = SignalEvent(
        symbol=symbol, action=SignalAction.BUY, price=2.0, score=score, reasons=["setup ok"]
    )
    details: dict = {
        "change_pct": 0.0,
        "rvol": rvol,
        "vwap_distance_pct": 1.0,
        "halted": False,
        "risk_flags": [],
        "catalyst": None,
        "returns_5m": None,
        "order_template": None,
    }
    details.update(over)
    return event, details


def _stub(svc: MonitorService, canned: dict[str, tuple[SignalEvent, dict]]) -> None:
    async def _fake(symbol: str):  # type: ignore[no-untyped-def]
        return canned[symbol]

    svc.evaluate_symbol = _fake  # type: ignore[method-assign]


@pytest.mark.asyncio
async def test_regime_chop_demotes_weak_buy_keeps_strong() -> None:
    svc = MonitorService(market_data_provider=MockMarketDataProvider())
    # breadth 50% (one above, one below VWAP) + flat median -> CHOP (80/4.0)
    canned = {
        "AAA": _buy("AAA", 72, 2.5, vwap_distance_pct=1.0),
        "BBB": _buy("BBB", 85, 5.0, vwap_distance_pct=-1.0),
    }
    _stub(svc, canned)
    out = await svc.run_once(["AAA", "BBB"])
    assert svc.last_regime == "chop"
    by_sym = {e.symbol: e for e in out}
    assert by_sym["AAA"].action == "hold"
    assert any("régimen chop" in r for r in by_sym["AAA"].reasons)
    assert by_sym["BBB"].action == "buy"


@pytest.mark.asyncio
async def test_halt_storm_blocks_all_buys(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = MonitorService(market_data_provider=MockMarketDataProvider())
    settings = get_settings()
    monkeypatch.setattr(settings.monitor, "halt_storm_threshold", 1)
    svc.halts.report_halt("AAA")
    canned = {"AAA": _buy("AAA", 95, 9.0)}
    _stub(svc, canned)
    out = await svc.run_once(["AAA"])
    assert svc.last_regime == "halt_storm"
    assert out[0].action == "hold"
    assert any("HALT_STORM" in r for r in out[0].reasons)


@pytest.mark.asyncio
async def test_correlation_drops_clone_keeps_best() -> None:
    svc = MonitorService(market_data_provider=MockMarketDataProvider())
    series = [float(i) * 0.01 for i in range(30)]
    canned = {
        "AAA": _buy("AAA", 90, 5.0, returns_5m=list(series)),
        "BBB": _buy("BBB", 80, 5.0, returns_5m=[v + 0.0001 for v in series]),
        "CCC": _buy("CCC", 70, 5.0, returns_5m=None),  # no series: kept
    }
    _stub(svc, canned)
    # force RISK_ON so the regime gate does not interfere (all above VWAP)
    out = await svc.run_once(["AAA", "BBB", "CCC"])
    by_sym = {e.symbol: e for e in out}
    assert by_sym["AAA"].action == "buy"
    assert by_sym["BBB"].action == "hold"
    assert any("correlación" in r for r in by_sym["BBB"].reasons)
    assert by_sym["CCC"].action in ("buy", "hold")  # kept by filter; regime may demote 70
    assert "BBB" in svc.last_corr_dropped


@pytest.mark.asyncio
async def test_circuit_symbol_trip_demotes_buy() -> None:
    svc = MonitorService(market_data_provider=MockMarketDataProvider())
    # median +1% -> no portfolio kill; CCC -9% trips its own symbol breaker.
    canned = {
        "AAA": _buy("AAA", 85, 5.0, change_pct=1.0),
        "BBB": _buy("BBB", 85, 5.0, change_pct=1.0),
        "CCC": _buy("CCC", 85, 5.0, change_pct=-9.0),
    }
    _stub(svc, canned)
    out = await svc.run_once(["AAA", "BBB", "CCC"])
    by_sym = {e.symbol: e for e in out}
    assert by_sym["AAA"].action == "buy"
    assert by_sym["CCC"].action == "hold"
    assert any("circuito" in r for r in by_sym["CCC"].reasons)
    assert svc.breaker.is_vetoed("CCC") is True


@pytest.mark.asyncio
async def test_circuit_veto_freezes_real_evaluation() -> None:
    provider = MockMarketDataProvider()
    provider.set_quote("ABCD", 2.20)
    svc = MonitorService(market_data_provider=provider)
    svc.breaker.check_symbol("ABCD", -9.0)
    event, _ = await svc.evaluate_symbol("ABCD")
    assert event.action == SignalAction.HOLD
    assert any("vetado" in r or "kill" in r or "circuito" in r for r in event.reasons)


@pytest.mark.asyncio
async def test_status_exposes_regime_and_breaker() -> None:
    svc = MonitorService(market_data_provider=MockMarketDataProvider())
    _stub(svc, {"AAA": _buy("AAA", 85, 5.0)})
    await svc.run_once(["AAA"])
    st = svc.status()
    assert st["regime"] in ("risk_on", "chop", "risk_off", "halt_storm")
    assert "kill_switch" in st
    assert "vetoed_symbols" in st
    assert "circuit_events" in st


@pytest.mark.asyncio
async def test_kill_switch_critical_sent_once_per_transition() -> None:
    svc = MonitorService(market_data_provider=MockMarketDataProvider())
    calls: list[str] = []

    async def _crit(message: str) -> bool:  # type: ignore[no-untyped-def]
        calls.append(message)
        return True

    svc.alerts.send_critical = _crit  # type: ignore[method-assign]
    # median -8% -> portfolio kill on every round; critical only on transition
    canned = {
        "AAA": _buy("AAA", 85, 5.0, change_pct=-8.0),
        "BBB": _buy("BBB", 85, 5.0, change_pct=-8.0),
        "CCC": _buy("CCC", 85, 5.0, change_pct=-8.0),
    }
    _stub(svc, canned)
    first = await svc.run_once(["AAA", "BBB", "CCC"])
    assert svc.breaker.killed is True
    assert len(calls) == 1 and "kill switch" in calls[0]
    assert all(e.action == "hold" for e in first)
    await svc.run_once(["AAA", "BBB", "CCC"])
    assert len(calls) == 1  # no repeat while condition persists


@pytest.mark.asyncio
async def test_paper_opens_on_buy_and_closes_on_sell() -> None:
    from app.signals import SignalAction as _A

    svc = MonitorService(market_data_provider=MockMarketDataProvider())
    buy_ev, buy_det = _buy("AAA", 85, 5.0, change_pct=2.0, vwap_distance_pct=1.0)
    buy_ev.action = _A.BUY  # RISK_ON single-symbol round: survives all gates
    _stub(svc, {"AAA": (buy_ev, buy_det)})
    out = await svc.run_once(["AAA"])
    assert out[0].action == "buy"
    assert svc.paper.summary()["open_positions"] == 1
    assert any("paper: abre" in r for r in out[0].reasons)

    sell_ev, sell_det = _buy("AAA", 40, 0.5, change_pct=-9.0, vwap_distance_pct=-5.0)
    sell_ev.action = _A.SELL
    _stub(svc, {"AAA": (sell_ev, sell_det)})
    out2 = await svc.run_once(["AAA"])
    assert out2[0].action == "sell"
    assert svc.paper.summary()["open_positions"] == 0
    assert svc.paper.summary()["closed_trades"] == 1
    assert any("paper: cierra" in r for r in out2[0].reasons)


@pytest.mark.asyncio
async def test_paper_symbol_trip_uses_position_pnl() -> None:
    svc = MonitorService(market_data_provider=MockMarketDataProvider())
    # open a paper position 10% underwater -> symbol breaker trips on real PnL
    pos = svc.paper.on_buy("AAA", 2.00, shares=100)
    assert pos is not None
    ev, det = _buy("AAA", 85, 5.0, change_pct=0.5)
    ev.price = 1.70  # round price marks MtM ≈ -16% all-in (proxy change is +0.5)
    _stub(svc, {"AAA": (ev, det)})
    out = await svc.run_once(["AAA"])
    assert out[0].action == "hold"
    assert any("circuito" in r for r in out[0].reasons)
    assert svc.breaker.is_vetoed("AAA") is True


@pytest.mark.asyncio
async def test_status_includes_paper_summary() -> None:
    svc = MonitorService(market_data_provider=MockMarketDataProvider())
    _stub(svc, {"AAA": _buy("AAA", 85, 5.0)})
    await svc.run_once(["AAA"])
    paper = svc.status()["paper"]
    assert paper["starting_equity"] == 10_000.0
    assert "equity" in paper and "daily_pnl_pct" in paper
