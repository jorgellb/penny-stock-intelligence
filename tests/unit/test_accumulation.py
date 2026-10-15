"""Tests for stealth accumulation / climax detection."""

import numpy as np
import pytest

from app.signals.accumulation import (
    clv_series,
    detect_accumulation,
    detect_climax,
    detect_markup_readiness,
    float_rotation,
    lin_slope,
    money_flow_ratio,
)


def _accumulation_tape() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Flat price, pinned upper-range closes, 4x volume tail, full turnover."""
    rng = np.random.default_rng(11)
    n = 30
    base = 2.0 + rng.normal(0, 0.004, n)
    highs = base + 0.03
    lows = base - 0.03
    closes = lows + 0.054 + rng.normal(0, 0.001, n)  # CLV ~0.9
    volumes = np.full(n, 500_000.0)
    volumes[-5:] = 2_000_000.0
    return highs, lows, closes, volumes


def test_clv_and_money_flow() -> None:
    highs = np.array([10.0, 10.0])
    lows = np.array([9.0, 9.0])
    closes = np.array([9.9, 9.9])  # upper range
    clv = clv_series(highs, lows, closes)
    assert all(abs(c - 0.9) < 1e-9 for c in clv)
    assert clv_series(np.array([5.0]), np.array([5.0]), np.array([5.0]))[0] == 0.5
    vols = np.ones(20)
    mf = money_flow_ratio(np.full(20, 10.0), np.full(20, 9.0), np.full(20, 9.9), vols, window=20)
    assert mf == pytest.approx(0.8)
    assert money_flow_ratio(highs, lows, closes, vols, window=20) == 0.0  # too short


def test_slope_and_rotation() -> None:
    assert lin_slope(np.array([1.0, 2.0, 3.0])) == pytest.approx(1.0)  # +1.0 per bar
    assert lin_slope(np.array([5.0])) == 0.0
    vols = np.full(20, 1_000_000.0)
    assert float_rotation(vols, 10_000_000.0) == 2.0
    assert float_rotation(vols, None) is None
    assert float_rotation(vols, 0.0) is None


def test_strong_accumulation_detected() -> None:
    h, low, c, v = _accumulation_tape()
    r = detect_accumulation(h, low, c, v, float_shares=10_000_000.0)
    assert r.score >= 60
    assert r.phase == "accumulation"
    assert any("absorción" in x for x in r.reasons)
    assert r.metrics["float_rotation"] >= 1.5


def test_random_tape_stays_neutral() -> None:
    rng = np.random.default_rng(3)
    n = 30
    w = 2.0 + np.cumsum(rng.normal(0, 0.05, n))
    r = detect_accumulation(w + 0.05, w - 0.05, w, np.full(n, 500_000.0))
    assert r.phase == "neutral"
    assert r.score < 60


def test_insufficient_data_neutral() -> None:
    r = detect_accumulation(np.ones(5), np.ones(5), np.ones(5), np.ones(5))
    assert r.phase == "neutral" and r.score == 0


def test_climax_detected() -> None:
    c = np.concatenate([1.0 + np.linspace(0, 0.08, 24), [1.5]])
    ch = c + 0.02
    cl = np.concatenate([(c[:-1] - 0.02), [1.15]])
    cv = np.full(25, 500_000.0)
    cv[-1] = 6_000_000.0
    out = detect_climax(ch, cl, c, cv)
    assert out is not None
    assert out["volume_multiple"] >= 3.0
    assert detect_climax(ch, cl, c, np.full(25, 500_000.0)) is None  # no blow-off


def test_markup_readiness() -> None:
    h, low, c, v = _accumulation_tape()
    r = detect_accumulation(h, low, c, v, float_shares=10_000_000.0)
    assert r.phase == "accumulation"
    # no breakout yet (flat tape)
    assert detect_markup_readiness(c, v, r) == (False, [])
    # breakout bar on expanding volume
    cb = np.concatenate([c, [c.max() + 0.10]])
    vb = np.concatenate([v, [4_000_000.0]])
    ok, reasons = detect_markup_readiness(cb, vb, r)
    assert ok is True and reasons
