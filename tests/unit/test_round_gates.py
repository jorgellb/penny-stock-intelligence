"""Unit tests for round-level monitor gates."""

from __future__ import annotations

from types import SimpleNamespace

from app.jobs.monitor.round_gates import (
    apply_breadth_cap,
    apply_exit_rules,
    apply_regime_gate,
    compute_regime,
)
from app.signals import SignalAction, SignalEvent
from app.signals.regime import MarketRegime


def _buy(symbol: str, score: int = 75, rvol: float = 3.0) -> tuple[SignalEvent, dict]:
    return (
        SignalEvent(
            symbol=symbol,
            action=SignalAction.BUY,
            price=1.5,
            score=score,
            reasons=["setup"],
        ),
        {"rvol": rvol, "vwap_distance_pct": 2.0, "change_pct": 3.0, "halted": False},
    )


def test_compute_regime_halt_storm() -> None:
    evaluated = [_buy("AAA"), _buy("BBB")]
    cfg = SimpleNamespace(
        regime_enabled=True,
        buy_min_score=70,
        buy_min_rvol=2.0,
        halt_storm_threshold=2,
        regime_chop_min_score=80.0,
        regime_chop_min_rvol=4.0,
        regime_riskoff_min_score=80.0,
        regime_riskoff_min_rvol=4.0,
    )
    for _, d in evaluated:
        d["halted"] = True
    regime, thr = compute_regime(evaluated, cfg, lambda _s: 0)
    assert regime == MarketRegime.HALT_STORM
    assert thr["min_score"] >= 70


def test_apply_regime_gate_demotes_in_halt_storm() -> None:
    evaluated = [_buy("AAA")]
    apply_regime_gate(evaluated, MarketRegime.HALT_STORM, {"min_score": 70, "min_rvol": 2}, True)
    assert evaluated[0][0].action == SignalAction.HOLD
    assert "HALT_STORM" in evaluated[0][0].reasons[0]


def test_apply_breadth_cap_keeps_best_scores() -> None:
    evaluated = [_buy("A", 90), _buy("B", 80), _buy("C", 70)]
    capped = apply_breadth_cap(evaluated, 1)
    assert capped == 2
    actions = {e.symbol: e.action for e, _ in evaluated}
    assert actions["A"] == SignalAction.BUY
    assert actions["B"] == SignalAction.HOLD
    assert actions["C"] == SignalAction.HOLD


def test_apply_exit_rules_take_profit() -> None:
    event = SignalEvent(symbol="AAA", action=SignalAction.HOLD, price=2.0, score=50, reasons=[])
    evaluated = [(event, {})]
    cfg = SimpleNamespace(sell_take_profit_pct=10.0, sell_stop_loss_pct=None)
    apply_exit_rules(evaluated, cfg, lambda _s: 12.0)
    assert event.action == SignalAction.SELL
    assert "take-profit" in event.reasons[0]
