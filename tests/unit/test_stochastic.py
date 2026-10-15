"""Tests for the Stochastic oscillator (%K/%D, crosses, divergence)."""

import numpy as np

from app.indicators import (
    compute_all_indicators,
    detect_divergence,
    stoch_cross,
    stochastic,
)


def _trend(n: int = 40, step: float = 0.1) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    closes = np.array([10.0 + i * step for i in range(n)])
    highs = closes + 0.2
    lows = closes - 0.2
    return highs, lows, closes


def test_stochastic_range_and_d() -> None:
    highs, lows, closes = _trend()
    k, d = stochastic(highs, lows, closes)
    assert len(k) == len(closes) == len(d)
    assert np.all(np.isnan(k[:13]))
    assert np.all((k[13:] >= 0) & (k[13:] <= 100))
    # %D is the 3-period SMA of %K
    assert d[-1] == float(np.nanmean(k[-3:]))


def test_stochastic_flat_market_neutral() -> None:
    n = 20
    closes = np.full(n, 5.0)
    k, d = stochastic(closes, closes, closes)
    assert np.all(k[13:] == 50.0)


def test_stochastic_oversold_bounce() -> None:
    # crash then recovery: %K should be low at the bottom, high at recovery
    closes = np.array([10.0 - i * 0.5 for i in range(14)] + [3.0 + i * 0.8 for i in range(14)])
    highs = closes + 0.1
    lows = closes - 0.1
    k, _ = stochastic(highs, lows, closes)
    assert k[13] < 20.0  # deep oversold at the bottom
    assert k[-1] > 80.0  # overbought after the bounce


def test_stoch_cross_bullish_and_bearish() -> None:
    k = np.array([20.0, 25.0, 30.0])
    d = np.array([28.0, 27.0, 26.0])
    assert stoch_cross(k, d) == "bullish"
    assert stoch_cross(d, k) == "bearish"
    assert stoch_cross(np.array([50.0, 51.0]), np.array([40.0, 41.0])) is None
    assert stoch_cross(np.array([np.nan]), np.array([np.nan])) is None


def test_stochastic_divergence_via_d() -> None:
    # price higher high, %D lower high
    closes = np.full(20, 9.0)
    closes[5] = 10.0
    closes[6] = 9.0
    closes[15] = 11.0
    closes[16] = 10.0
    d = np.full(20, 50.0)
    d[5] = 80.0
    d[15] = 60.0
    out = detect_divergence(closes, d)
    assert out["bearish"] is not None
    assert out["bullish"] is None


def test_compute_all_includes_stochastic() -> None:
    highs, lows, closes = _trend(40)
    out = compute_all_indicators(closes, highs, lows)
    assert out["stoch_k"] is not None
    assert out["stoch_d"] is not None
    assert 0 <= out["stoch_k"] <= 100
    assert out["stoch_cross"] in ("bullish", "bearish", None)
    assert out["stoch_divergence"] in ("bullish", "bearish", None)
    short = compute_all_indicators(np.array([1.0, 2.0, 3.0]))
    assert short["stoch_k"] is None
    assert short["stoch_cross"] is None


def test_session_vwap_math() -> None:
    from app.indicators import session_vwap

    class B:
        def __init__(self, h: float, low: float, c: float, v: int) -> None:
            self.high = h
            self.low = low
            self.close = c
            self.volume = v

    bars = [B(2.05, 1.95, 2.0, 100_000), B(2.10, 2.00, 2.08, 300_000)]
    # typical: 2.0 and 2.06 -> (2.0*100k + 2.06*300k) / 400k = 2.045
    assert session_vwap(bars) == 2.045
    assert session_vwap([]) is None
    assert session_vwap([B(2.0, 2.0, 2.0, 0)]) is None
