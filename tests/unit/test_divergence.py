"""Tests for pivot + RSI/MACD divergence detection."""

import numpy as np

from app.indicators import (
    compute_all_indicators,
    detect_divergence,
    pivot_highs,
    pivot_lows,
)


def _bearish_series() -> tuple[np.ndarray, np.ndarray]:
    closes = np.full(20, 9.0)
    closes[3] = 8.0
    closes[4] = 9.0
    closes[5] = 10.0  # pivot high 1
    closes[6] = 9.0
    closes[7] = 8.5
    closes[13] = 9.5
    closes[14] = 10.0
    closes[15] = 11.0  # pivot high 2 (higher)
    closes[16] = 10.0
    closes[17] = 9.5
    osc = np.full(20, 50.0)
    osc[5] = 70.0
    osc[15] = 60.0  # lower high -> bearish
    return closes, osc


def _bullish_series() -> tuple[np.ndarray, np.ndarray]:
    closes = np.full(20, 10.0)
    closes[3] = 11.0
    closes[4] = 10.5
    closes[5] = 10.0  # pivot low 1
    closes[6] = 10.5
    closes[7] = 11.0
    closes[13] = 10.0
    closes[14] = 9.5
    closes[15] = 9.0  # pivot low 2 (lower)
    closes[16] = 9.5
    closes[17] = 10.0
    osc = np.full(20, 50.0)
    osc[5] = 30.0
    osc[15] = 40.0  # higher low -> bullish
    return closes, osc


def test_pivot_detection() -> None:
    closes, _ = _bearish_series()
    highs = pivot_highs(closes)
    assert 5 in highs
    assert 15 in highs
    lows = pivot_lows(closes)
    assert 5 not in lows


def test_bearish_divergence() -> None:
    closes, osc = _bearish_series()
    out = detect_divergence(closes, osc)
    assert out["bearish"] is not None
    assert out["bearish"]["price_2"] > out["bearish"]["price_1"]
    assert out["bearish"]["osc_2"] < out["bearish"]["osc_1"]
    assert out["bullish"] is None


def test_bullish_divergence() -> None:
    closes, osc = _bullish_series()
    out = detect_divergence(closes, osc)
    assert out["bullish"] is not None
    assert out["bullish"]["price_2"] < out["bullish"]["price_1"]
    assert out["bullish"]["osc_2"] > out["bullish"]["osc_1"]
    assert out["bearish"] is None


def test_no_divergence_in_aligned_trend() -> None:
    closes = np.array([10.0 + i * 0.5 for i in range(30)])
    osc = np.array([40.0 + i for i in range(30)])
    out = detect_divergence(closes, osc)
    assert out["bearish"] is None
    assert out["bullish"] is None


def test_insufficient_or_mismatched_data() -> None:
    out = detect_divergence(np.array([1.0, 2.0]), np.array([1.0, 2.0]))
    assert out == {"bullish": None, "bearish": None}
    out = detect_divergence(np.ones(30), np.ones(10))
    assert out == {"bullish": None, "bearish": None}


def test_nan_oscillator_ignored() -> None:
    closes, osc = _bearish_series()
    osc[15] = np.nan
    out = detect_divergence(closes, osc)
    assert out["bearish"] is None


def test_compute_all_includes_divergence_keys() -> None:
    closes = np.array([10.0 + (i % 5) * 0.3 + i * 0.02 for i in range(40)])
    out = compute_all_indicators(closes)
    assert "rsi_divergence" in out
    assert "macd_divergence" in out
    assert out["rsi_divergence"] in ("bullish", "bearish", None)
    short = compute_all_indicators(np.array([1.0, 2.0, 3.0]))
    assert short["rsi_divergence"] is None
