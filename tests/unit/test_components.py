"""Composite sub-scores, chase guard, trade plan and live session merge."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import numpy as np

from app.indicators import adx, atr, rsi
from app.jobs.monitor.live import build_live_session
from app.risk.sizing import PositionSizer, SizingInput
from app.scoring import ScoringEngine
from app.scoring.components import (
    extension_check,
    liquidity_component,
    momentum_component,
    technical_component,
    volume_component,
)
from app.signals.trade_plan import build_trade_plan, grade_signal

# --- indicators -------------------------------------------------------------


def test_rsi_wilder_reference_values() -> None:
    # Classic Wilder example series: RSI(14) on bar 15 is ~70.5.
    closes = np.array(
        [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08,
         45.89, 46.03, 45.61, 46.28, 46.28, 46.00, 46.03, 46.41, 46.22, 45.64],
    )  # fmt: skip
    r = rsi(closes, 14)
    assert abs(r[14] - 70.46) < 0.5
    assert np.isnan(r[:14]).all()


def test_rsi_flat_series_is_neutral() -> None:
    assert rsi(np.full(30, 5.0), 14)[-1] == 50.0


def test_atr_and_adx_are_aligned_and_finite() -> None:
    rng = np.random.default_rng(1)
    c = np.cumsum(rng.normal(0, 1, 120)) + 100
    h, low = c + 1.0, c - 1.0
    a = atr(h, low, c)
    d = adx(h, low, c)
    assert len(a) == len(d) == len(c)
    assert np.isfinite(a[-1]) and 0 <= d[-1] <= 100
    # Strong steady uptrend should show a trending ADX.
    up = np.linspace(1, 3, 120)
    assert adx(up + 0.02, up - 0.02, up)[-1] > 40


# --- sub-scores --------------------------------------------------------------


def test_volume_component_is_log_scaled_not_saturated() -> None:
    assert volume_component(1.0) == 0
    v2, v5, v10 = volume_component(2.0), volume_component(5.0), volume_component(10.0)
    assert 25 < v2 < v5 < v10 == 100
    assert volume_component(3.0, float_rotation=1.0) > volume_component(3.0)


def test_momentum_component_normalizes_by_atr() -> None:
    quiet = momentum_component(8.0, atr_pct=3.0)  # 2.7 ATR move
    wild = momentum_component(8.0, atr_pct=20.0)  # 0.4 ATR move
    assert quiet > wild
    assert momentum_component(-5.0, atr_pct=5.0, vwap_distance_pct=-1) == 0
    assert momentum_component(5.0, 5.0, vwap_distance_pct=2.0) > momentum_component(
        5.0, 5.0, vwap_distance_pct=-2.0
    )


def test_liquidity_component_prefers_dollar_volume_and_tight_spread() -> None:
    assert liquidity_component(100_000) < liquidity_component(1_000_000)
    assert liquidity_component(20_000_000, 0.3) == 100
    assert liquidity_component(5_000_000, 8.0) < liquidity_component(5_000_000, None)


def test_technical_component_rewards_uptrend_over_downtrend() -> None:
    up = np.linspace(1.0, 2.0, 80) + np.sin(np.arange(80)) * 0.01
    down = up[::-1]
    tv_up = technical_component(up, up * 1.01, up * 0.99)
    tv_down = technical_component(down, down * 1.01, down * 0.99)
    assert tv_up is not None and tv_down is not None
    assert tv_up.score > 60 > tv_down.score
    assert technical_component(up[:10]) is None


def test_unknown_catalyst_renormalizes_but_checked_none_does_not() -> None:
    engine = ScoringEngine()
    kwargs = dict(
        rvol=10.0,
        momentum_score=100.0,
        technical_score=100.0,
        liquidity_score=100.0,
        fundamentals_score=100.0,
        data_quality_score=100.0,
    )
    unknown = engine.score_security(**kwargs, renormalize_unknown_catalyst=True)
    absent = engine.score_security(**kwargs, catalyst_strength="none")
    assert unknown.final_score == 100
    assert absent.final_score == 80


# --- chase guard / trade plan -------------------------------------------------


def test_extension_check_flags_chasing() -> None:
    assert extension_check(1.30, vwap=1.0, atr=0.2, rsi_14=70, change_pct=40).overextended
    assert not extension_check(1.05, vwap=1.0, atr=0.2, rsi_14=70, change_pct=20).overextended
    assert extension_check(1.0, None, None, rsi_14=93, change_pct=10).overextended


def test_trade_plan_uses_tightest_valid_structure() -> None:
    plan = build_trade_plan(
        2.00, atr=0.30, vwap=1.90, day_low=1.70, opening_range_low=1.80, min_stop_pct=3.0
    )
    assert plan is not None
    assert plan.stop_basis == "VWAP"
    assert abs(plan.stop - 1.90 * 0.995) < 1e-9
    assert plan.targets[1] - plan.entry == 2 * plan.risk_per_share
    assert abs(plan.reward_risk - 2.0) < 1e-9


def test_trade_plan_ignores_noise_stops_and_caps_wide_ones() -> None:
    tight = build_trade_plan(2.00, atr=0.15, vwap=1.99, min_stop_pct=3.0)
    assert tight is not None and tight.stop_basis == "1 ATR diario"
    wide = build_trade_plan(2.00, atr=1.50, max_stop_pct=12.0)
    assert wide is not None and abs(wide.risk_pct - 12.0) < 1e-9


def test_trade_plan_resistance_caps_reward_and_grade() -> None:
    plan = build_trade_plan(2.00, atr=0.2, vwap=1.90, resistance=2.10)
    assert plan is not None and plan.reward_risk < 2.0
    grade_signal(plan, score=85, matched_setups=2, has_catalyst=True, trend_aligned=True)
    assert plan.grade == "A"
    weak = build_trade_plan(2.00, atr=0.2, vwap=1.90)
    assert weak is not None
    grade_signal(weak, score=65, matched_setups=1, has_catalyst=False, trend_aligned=False)
    assert weak.grade == "C"


def test_sizing_uses_plan_stop_distance() -> None:
    sizer = PositionSizer(risk_per_trade_pct=0.01)
    res = sizer.compute(
        SizingInput(equity=10_000, score=70, atr=0.0, price=2.0, stop_distance=0.10)
    )
    assert res.shares == 1000  # $100 risk / $0.10 per share (dollar cap 2k)


# --- live session --------------------------------------------------------------


def _daily(d: datetime, close: float, vol: int = 1_000_000) -> SimpleNamespace:
    px = Decimal(str(close))
    return SimpleNamespace(date=d, open=px, high=px, low=px, close=px, volume=vol)


def _bar(ts: datetime, px: float, vol: int = 1000) -> SimpleNamespace:
    p = Decimal(str(px))
    return SimpleNamespace(symbol="ABCD", timestamp=ts, open=p, high=p, low=p, close=p,
                           volume=vol)  # fmt: skip


def test_live_session_premarket_measures_gap_vs_prior_close() -> None:
    day1 = datetime(2026, 10, 13)
    day2 = datetime(2026, 10, 14)
    daily = [_daily(day1, 1.00), _daily(day2, 1.10)]
    pre_ts = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)  # 08:00 ET
    bars = [_bar(pre_ts, 1.30, 5000), _bar(pre_ts + timedelta(minutes=5), 1.32, 7000)]
    live = build_live_session(daily, bars, 1.32)
    assert live.phase == "premarket"
    assert live.prev_close == 1.10
    assert abs(live.change_pct - 20.0) < 1e-6
    assert live.premarket_high == 1.32 and live.premarket_volume == 12000
    assert len(live.bars) == 2  # no fake daily bar before the open


def test_live_session_regular_merges_today_bar() -> None:
    daily = [_daily(datetime(2026, 10, 13), 1.00), _daily(datetime(2026, 10, 14), 1.10)]
    open_ts = datetime(2026, 10, 15, 13, 30, tzinfo=UTC)  # 09:30 ET
    bars = [_bar(open_ts + timedelta(minutes=5 * i), 1.20 + 0.01 * i, 10_000) for i in range(6)]
    live = build_live_session(daily, bars, 1.25)
    assert live.phase == "regular"
    assert len(live.bars) == 3
    assert float(live.bars[-1].close) == 1.25
    assert live.session_volume == 60_000
    assert live.opening_range_high == 1.22  # first 15 minutes
    assert abs(live.change_pct - (1.25 / 1.10 - 1) * 100) < 1e-6


def test_live_session_without_intraday_keeps_last_day_change() -> None:
    daily = [_daily(datetime(2026, 10, 13), 1.00), _daily(datetime(2026, 10, 14), 1.10)]
    live = build_live_session(daily, [], 1.10)
    assert abs(live.change_pct - 10.0) < 1e-6
