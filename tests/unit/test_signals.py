"""Tests for buy/sell signal rules."""

from app.config import MonitorConfig
from app.signals import SignalAction, SignalInput, evaluate
from app.signals.regime import MarketRegime, regime_buy_thresholds


def _base(**overrides: object) -> SignalInput:
    data: dict = {
        "symbol": "ABCD",
        "price": 2.20,
        "score": 78,
        "rvol": 5.8,
        "change_pct": 14.7,
        "vwap_distance_pct": 0.5,
        "spread_pct": 1.2,
        "blocking_flags": [],
        "stale": False,
    }
    data.update(overrides)
    return SignalInput(**data)


def test_buy_signal_when_setup_matches() -> None:
    event = evaluate(_base())
    assert event.action == SignalAction.BUY
    assert event.is_actionable is True
    assert any("score" in r for r in event.reasons)
    assert "no es recomendación" in event.describe()


def test_buy_blocked_by_offering() -> None:
    event = evaluate(
        _base(blocking_flags=["RECENT_OFFERING"], prev_blocking_flags=["RECENT_OFFERING"])
    )
    assert event.action == SignalAction.HOLD


def test_buy_blocked_by_low_score() -> None:
    event = evaluate(_base(score=40))
    assert event.action == SignalAction.HOLD


def test_buy_blocked_by_low_rvol() -> None:
    event = evaluate(_base(rvol=0.8))
    assert event.action == SignalAction.HOLD


def test_buy_blocked_below_vwap() -> None:
    event = evaluate(_base(vwap_distance_pct=-1.5))
    assert event.action == SignalAction.HOLD


def test_buy_blocked_by_wide_spread() -> None:
    event = evaluate(_base(spread_pct=12.0))
    assert event.action == SignalAction.HOLD


def test_buy_blocked_by_stale_data() -> None:
    event = evaluate(_base(stale=True))
    assert event.action == SignalAction.HOLD


def test_sell_on_new_blocking_flag() -> None:
    event = evaluate(
        _base(score=40, rvol=0.5, prev_blocking_flags=[], blocking_flags=["ACTIVE_ATM"])
    )
    assert event.action == SignalAction.SELL
    assert any("ATM" in r for r in event.reasons)


def test_sell_on_score_collapse() -> None:
    event = evaluate(_base(score=50, rvol=0.5, prev_score=80))
    assert event.action == SignalAction.SELL
    assert any("score" in r for r in event.reasons)


def test_sell_on_vwap_loss() -> None:
    event = evaluate(_base(score=40, rvol=0.5, vwap_distance_pct=-4.0, prev_above_vwap=True))
    assert event.action == SignalAction.SELL


def test_hold_when_nothing_matches() -> None:
    event = evaluate(_base(score=40, rvol=0.5))
    assert event.action == SignalAction.HOLD
    assert event.is_actionable is False


def test_buy_takes_precedence_over_sell() -> None:
    event = evaluate(_base(prev_score=95))
    assert event.action == SignalAction.BUY


def test_halt_forces_hold_even_with_score_collapse() -> None:
    event = evaluate(_base(prev_score=95, halted=True))
    assert event.action == SignalAction.HOLD
    assert any("halt" in r for r in event.reasons)


def _cfg(**overrides: object) -> MonitorConfig:
    return MonitorConfig(**overrides)  # type: ignore[arg-type]


def test_buy_blocked_by_dollar_volume_gate() -> None:
    event = evaluate(_base(dollar_volume=100_000.0), _cfg(buy_min_dollar_volume=500_000.0))
    assert event.action == SignalAction.HOLD
    event = evaluate(_base(dollar_volume=2_000_000.0), _cfg(buy_min_dollar_volume=500_000.0))
    assert event.action == SignalAction.BUY


def test_buy_blocked_by_negative_day_gate() -> None:
    event = evaluate(_base(change_pct=-3.0), _cfg(buy_min_change_pct=2.0))
    assert event.action == SignalAction.HOLD
    assert evaluate(_base()).action == SignalAction.BUY  # gate off by default


def test_buy_requires_catalyst_when_enabled() -> None:
    assert evaluate(_base(), _cfg(buy_require_catalyst=True)).action == SignalAction.HOLD
    event = evaluate(_base(has_catalyst=True), _cfg(buy_require_catalyst=True))
    assert event.action == SignalAction.BUY


def test_regime_thresholds_use_config_overrides() -> None:
    assert regime_buy_thresholds(MarketRegime.CHOP) == {"min_score": 80.0, "min_rvol": 4.0}
    cfg = _cfg(
        regime_chop_min_score=90.0,
        regime_chop_min_rvol=6.0,
        regime_riskoff_min_score=85.0,
        regime_riskoff_min_rvol=5.0,
    )
    assert regime_buy_thresholds(MarketRegime.CHOP, cfg) == {
        "min_score": 90.0,
        "min_rvol": 6.0,
    }
    assert regime_buy_thresholds(MarketRegime.RISK_OFF, cfg) == {
        "min_score": 85.0,
        "min_rvol": 5.0,
    }
    assert regime_buy_thresholds(MarketRegime.RISK_ON, cfg) == {
        "min_score": 70.0,
        "min_rvol": 2.0,
    }


def test_momentum_and_liquidity_helpers() -> None:
    from app.jobs.monitor import liquidity_score, momentum_score

    assert momentum_score(20.0) == 100.0
    assert momentum_score(-50.0) == 0.0
    assert momentum_score(10.0) == 50.0
    assert liquidity_score(None) == 90.0
    assert liquidity_score(1.0) == 90.0
    assert liquidity_score(2.0) == 70.0
    assert liquidity_score(9.9) == 50.0
