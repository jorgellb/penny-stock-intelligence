"""Unit tests for technical indicators."""

import numpy as np
import pytest

from app.indicators import (
    atr,
    breakout_detection,
    compute_all_indicators,
    dollar_volume,
    ema,
    gap_percent,
    macd,
    relative_volume,
    roc,
    rsi,
    sma,
)


class TestEMA:
    """Tests for Exponential Moving Average."""

    def test_ema_basic(self):
        """Test basic EMA calculation."""
        values = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        result = ema(values, 3)
        assert result is not None
        assert len(result) == len(values)
        assert not np.all(np.isnan(result))

    def test_ema_insufficient_data(self):
        """Test EMA with insufficient data."""
        values = np.array([1.0, 2.0])
        result = ema(values, 5)
        assert np.all(np.isnan(result))

    def test_ema_properties(self):
        """Test EMA mathematical properties."""
        values = np.ones(20) * 10.0
        result = ema(values, 10)
        assert np.allclose(result[~np.isnan(result)], 10.0, atol=0.01)


class TestSMA:
    """Tests for Simple Moving Average."""

    def test_sma_basic(self):
        """Test basic SMA calculation."""
        values = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        result = sma(values, 3)
        assert result is not None
        assert len(result) == len(values)

    def test_sma_insufficient_data(self):
        """Test SMA with insufficient data."""
        values = np.array([1.0])
        result = sma(values, 5)
        assert np.all(np.isnan(result))


class TestRSI:
    """Tests for RSI."""

    def test_rsi_basic(self):
        """Test basic RSI calculation."""
        # Create data with upward trend
        values = np.array([10 + i for i in range(30)], dtype=float)
        result = rsi(values, 14)
        assert result is not None
        assert len(result) == len(values)

    def test_rsi_overbought(self):
        """Test RSI identifies overbought conditions."""
        values = np.array([10 + i * 0.5 for i in range(50)], dtype=float)
        result = rsi(values, 14)
        last_rsi = result[-1]
        if not np.isnan(last_rsi):
            assert last_rsi > 50  # Should be > 50 for upward trend

    def test_rsi_insufficient_data(self):
        """Test RSI with insufficient data."""
        values = np.array([1.0, 2.0])
        result = rsi(values, 14)
        assert np.all(np.isnan(result))


class TestMACD:
    """Tests for MACD."""

    def test_macd_basic(self):
        """Test basic MACD calculation."""
        values = np.array([10 + i * 0.1 for i in range(50)], dtype=float)
        macd_line, signal_line, histogram = macd(values)
        assert len(macd_line) == len(values)
        assert len(signal_line) == len(values)
        assert len(histogram) == len(values)

    def test_macd_insufficient_data(self):
        """Test MACD with insufficient data."""
        values = np.array([1.0, 2.0])
        macd_line, signal_line, histogram = macd(values)
        assert np.all(np.isnan(macd_line))


class TestATR:
    """Tests for ATR."""

    def test_atr_basic(self):
        """Test basic ATR calculation."""
        highs = np.array([10 + i * 0.1 for i in range(30)], dtype=float)
        lows = np.array([10 + i * 0.1 - 0.5 for i in range(30)], dtype=float)
        closes = np.array([10 + i * 0.1 for i in range(30)], dtype=float)
        result = atr(highs, lows, closes, 14)
        assert result is not None
        assert len(result) == len(highs)

    def test_atr_insufficient_data(self):
        """Test ATR with insufficient data."""
        highs = np.array([10.0])
        lows = np.array([9.5])
        closes = np.array([10.0])
        result = atr(highs, lows, closes)
        assert np.all(np.isnan(result))


class TestROC:
    """Tests for Rate of Change."""

    def test_roc_basic(self):
        """Test basic ROC calculation."""
        values = np.array([10 + i for i in range(20)], dtype=float)
        result = roc(values, 10)
        assert result is not None
        assert len(result) == len(values)

    def test_roc_positive(self):
        """Test ROC is positive for upward trend."""
        values = np.array([10 + i * 2 for i in range(20)], dtype=float)
        result = roc(values, 5)
        last_val = result[-1]
        assert last_val > 0 or np.isnan(last_val)


class TestRelativeVolume:
    """Tests for relative volume."""

    def test_rvol_basic(self):
        """Test basic RVOL."""
        current = 1000000
        historical = np.array([500000] * 20)
        result = relative_volume(current, historical, window=20)
        assert result == 2.0

    def test_rvol_low(self):
        """Test RVOL with low volume."""
        current = 250000
        historical = np.array([500000] * 20)
        result = relative_volume(current, historical, window=20)
        assert result == 0.5

    def test_rvol_zero_current(self):
        """Test RVOL with zero current volume."""
        result = relative_volume(0, np.array([500000] * 20))
        assert result == 0.0


class TestDollarVolume:
    """Tests for dollar volume."""

    def test_dollar_volume_basic(self):
        """Test basic dollar volume."""
        result = dollar_volume(2.50, 1000000)
        assert result == 2500000.0

    def test_dollar_volume_zero(self):
        """Test dollar volume with zero price."""
        result = dollar_volume(0, 1000000)
        assert result == 0.0


class TestGapPercent:
    """Tests for gap percentage."""

    def test_gap_up(self):
        """Test gap up."""
        result = gap_percent(1.00, 1.10)
        assert result == pytest.approx(10.0)

    def test_gap_down(self):
        """Test gap down."""
        result = gap_percent(1.00, 0.90)
        assert result == pytest.approx(-10.0)

    def test_no_gap(self):
        """Test no gap."""
        result = gap_percent(1.00, 1.00)
        assert result == 0.0


class TestBreakoutDetection:
    """Tests for breakout detection."""

    def test_breakout_detected(self):
        """Test breakout detection."""
        highs = np.array([1.0 + i * 0.05 for i in range(20)], dtype=float)
        result = breakout_detection(2.0, highs, 10)
        assert result

    def test_no_breakout(self):
        """Test no breakout."""
        highs = np.array([2.0 + i * 0.01 for i in range(20)], dtype=float)
        result = breakout_detection(2.0, highs, 10)
        assert not result

    def test_insufficient_data(self):
        """Test with insufficient data."""
        highs = np.array([1.0, 2.0])
        result = breakout_detection(2.0, highs, 10)
        assert not result


class TestComputeAllIndicators:
    """Tests for compute_all_indicators."""

    def test_basic_computation(self):
        """Test basic indicator computation."""
        closes = np.array([1.0 + i * 0.02 for i in range(30)], dtype=float)
        highs = closes + 0.1
        lows = closes - 0.1
        volumes = np.array([1000000] * 30)

        result = compute_all_indicators(closes, highs, lows, volumes)
        assert "ema_5" in result
        assert "rsi_14" in result
        assert "atr_14" in result
        assert "macd" in result
        assert "rvol_daily" in result

    def test_minimal_data(self):
        """Test with minimal data."""
        closes = np.array([1.0, 2.0, 3.0])
        result = compute_all_indicators(closes)
        assert result is not None
        assert isinstance(result, dict)
