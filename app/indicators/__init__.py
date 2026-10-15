"""
Technical indicators for financial analysis.
All calculations are deterministic using numpy/pandas.
"""

from typing import Any, Optional

import numpy as np
import pandas as pd  # type: ignore[import-untyped]


def ema(values: np.ndarray, period: int) -> np.ndarray:
    """Exponential Moving Average."""
    if len(values) < period:
        return np.full(len(values), np.nan)
    return np.asarray(pd.Series(values).ewm(span=period, adjust=False).mean().values)


def sma(values: np.ndarray, period: int) -> np.ndarray:
    """Simple Moving Average."""
    if len(values) < period:
        return np.full(len(values), np.nan)
    return np.asarray(pd.Series(values).rolling(window=period).mean().values)


def wilder_smooth(values: np.ndarray, period: int) -> np.ndarray:
    """Wilder's moving average (RMA), seeded with the first `period` SMA.

    This is the smoothing used by the reference RSI/ATR/ADX definitions
    (and by every charting platform), unlike a plain rolling mean.
    """
    values = np.asarray(values, dtype=float)
    out = np.full(len(values), np.nan)
    if len(values) < period:
        return out
    out[period - 1] = float(np.mean(values[:period]))
    for i in range(period, len(values)):
        out[i] = (out[i - 1] * (period - 1) + values[i]) / period
    return out


def rsi(values: np.ndarray, period: int = 14) -> np.ndarray:
    """Relative Strength Index (Wilder smoothing)."""
    if len(values) < period + 1:
        return np.full(len(values), np.nan)
    deltas = np.diff(np.asarray(values, dtype=float))
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = wilder_smooth(gains, period)
    avg_loss = wilder_smooth(losses, period)
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = avg_gain / avg_loss
        rsi_values = 100 - (100 / (1 + rs))
    # No losses in the window: RSI is 100 (or neutral 50 on a flat series).
    flat = (avg_loss == 0) & ~np.isnan(avg_loss)
    rsi_values = np.where(flat & (avg_gain > 0), 100.0, rsi_values)
    rsi_values = np.where(flat & (avg_gain == 0), 50.0, rsi_values)
    result = np.full(len(values), np.nan)
    result[1:] = rsi_values
    return result


def macd(
    values: np.ndarray, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[Any, Any, Any]:
    """MACD indicator."""
    if len(values) < slow:
        return (
            np.full(len(values), np.nan),
            np.full(len(values), np.nan),
            np.full(len(values), np.nan),
        )
    ema_fast = ema(values, fast)
    ema_slow = ema(values, slow)
    assert ema_fast is not None and ema_slow is not None
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    assert signal_line is not None
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def true_range(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray) -> np.ndarray:
    """True range per bar (first bar uses its own high-low)."""
    highs = np.asarray(highs, dtype=float)
    lows = np.asarray(lows, dtype=float)
    closes = np.asarray(closes, dtype=float)
    prev_close = np.roll(closes, 1)
    if len(closes):
        prev_close[0] = closes[0]
    return np.asarray(
        np.maximum.reduce([highs - lows, np.abs(highs - prev_close), np.abs(lows - prev_close)])
    )


def atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> np.ndarray:
    """Average True Range (Wilder smoothing)."""
    if len(closes) < period + 1:
        return np.full(len(closes), np.nan)
    return wilder_smooth(true_range(highs, lows, closes), period)


def vwap(bars: pd.DataFrame) -> pd.Series | None:
    """Volume Weighted Average Price."""
    if "volume" not in bars.columns or "high" not in bars.columns:
        return None
    typical_price = (bars["high"] + bars["low"] + bars["close"]) / 3
    vwap = (typical_price * bars["volume"]).cumsum() / bars["volume"].cumsum()
    return vwap


def session_vwap(bars: list[Any]) -> float | None:
    """Session VWAP from intraday bars (typical price x volume).

    Accepts any objects with high/low/close/volume attributes
    (domain Bar, ORM DailyBars...). None when no volume.
    """
    num = 0.0
    den = 0.0
    for b in bars:
        vol = float(b.volume or 0)
        if vol <= 0:
            continue
        typical = (float(b.high) + float(b.low) + float(b.close)) / 3.0
        num += typical * vol
        den += vol
    if den <= 0:
        return None
    return num / den


def bollinger_bands(
    values: np.ndarray, period: int = 20, num_std: float = 2.0
) -> tuple[Any, Any, Any]:
    """Bollinger Bands."""
    if len(values) < period:
        return (
            np.full(len(values), np.nan),
            np.full(len(values), np.nan),
            np.full(len(values), np.nan),
        )
    sma_values = pd.Series(values).rolling(window=period).mean().values
    std_values = pd.Series(values).rolling(window=period).std().values
    upper = sma_values + num_std * std_values
    lower = sma_values - num_std * std_values
    bandwidth = (upper - lower) / sma_values * 100
    return upper, lower, bandwidth


def adx(
    highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14
) -> np.ndarray | None:
    """Average Directional Index (Wilder), aligned bar-for-bar with closes."""
    n = len(closes)
    if n < period * 2 + 1:
        return np.full(n, np.nan)
    highs = np.asarray(highs, dtype=float)
    lows = np.asarray(lows, dtype=float)
    up = np.diff(highs)
    down = -np.diff(lows)
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    tr = true_range(highs, lows, closes)[1:]  # same length/alignment as the DMs
    tr_s = wilder_smooth(tr, period)
    with np.errstate(divide="ignore", invalid="ignore"):
        plus_di = 100 * wilder_smooth(plus_dm, period) / tr_s
        minus_di = 100 * wilder_smooth(minus_dm, period) / tr_s
        denom = plus_di + minus_di
        dx = np.where(denom > 0, 100 * np.abs(plus_di - minus_di) / denom, 0.0)
    first = period - 1
    adx_core = np.full(len(dx), np.nan)
    adx_core[first:] = wilder_smooth(dx[first:], period)
    result = np.full(n, np.nan)
    result[1:] = adx_core
    return result


def obv(closes: np.ndarray, volumes: np.ndarray) -> np.ndarray:
    """On-Balance Volume."""
    direction = np.sign(np.diff(closes))
    direction = np.insert(direction, 0, 0)
    return np.cumsum(volumes * direction)


def relative_volume(
    current_volume: int,
    historical_volumes: np.ndarray,
    window: int = 20,
) -> float:
    """Calculate relative volume."""
    if len(historical_volumes) < window or current_volume == 0:
        return 0.0
    avg_vol = historical_volumes[-window:].mean()
    if avg_vol == 0:
        return 0.0
    return float(current_volume / avg_vol)


def dollar_volume(price: float, volume: int) -> float:
    """Calculate dollar volume."""
    return price * volume


def roc(values: np.ndarray, period: int = 10) -> np.ndarray:
    """Rate of Change."""
    if len(values) < period + 1:
        return np.full(len(values), np.nan)
    values = np.asarray(values, dtype=float)
    out = np.full(len(values), np.nan)
    base = values[:-period]
    with np.errstate(divide="ignore", invalid="ignore"):
        out[period:] = np.where(base != 0, (values[period:] - base) / base * 100, np.nan)
    return out


def pct_from_high(closes: np.ndarray, highs: np.ndarray, window: int) -> float | None:
    """% distance of the last close below the highest high of the prior window.

    0 means at/above the high (breakout territory); 25 means 25% below.
    """
    if len(highs) < window + 1 or len(closes) == 0:
        return None
    ref = float(np.nanmax(highs[-window - 1 : -1]))
    if ref <= 0:
        return None
    return max(0.0, (ref - float(closes[-1])) / ref * 100)


def bb_width_percentile(values: np.ndarray, period: int = 20, lookback: int = 120) -> float | None:
    """Percentile (0-100) of today's Bollinger bandwidth vs its own history.

    Low values = volatility contraction (coiled spring before expansion).
    """
    if len(values) < period + 10:
        return None
    _, _, bw = bollinger_bands(values, period)
    bw = np.asarray(bw, dtype=float)
    hist = bw[~np.isnan(bw)][-lookback:]
    if len(hist) < 10:
        return None
    return float((hist < hist[-1]).mean() * 100)


def gap_percent(previous_close: float, current_price: float) -> float:
    """Calculate gap percentage."""
    if previous_close == 0:
        return 0.0
    return ((current_price - previous_close) / previous_close) * 100


def vwap_distance(vwap_value: float | None, current_price: float) -> float | None:
    """Calculate percentage distance from VWAP."""
    if vwap_value is None or vwap_value == 0:
        return None
    return ((current_price - vwap_value) / vwap_value) * 100


def intraday_range(high: float, low: float) -> float:
    """Calculate intraday range percentage."""
    if low == 0:
        return 0.0
    return ((high - low) / low) * 100


def realized_volatility(returns: np.ndarray, period: int = 20) -> float | None:
    """Calculate realized volatility (annualized)."""
    if len(returns) < period:
        return None
    recent = returns[-period:]
    return float(np.std(recent) * np.sqrt(252) * 100)


def atr_percent(atr_value: float, price: float) -> float:
    """Calculate ATR as percentage of price."""
    if price == 0 or atr_value is None:
        return 0.0
    return float((atr_value / price) * 100)


def volume_acceleration(volumes: np.ndarray, window: int = 5) -> float | None:
    """Calculate volume acceleration."""
    if len(volumes) < window * 2:
        return None
    recent_avg = volumes[-window:].mean()
    prev_avg = volumes[-window * 2 : -window].mean()
    if prev_avg == 0:
        return None
    return float((recent_avg - prev_avg) / prev_avg)


def breakout_detection(
    current_price: float,
    highs: np.ndarray,
    period: int,
    threshold_pct: float = 0.5,
) -> bool:
    """Detect if current price breaks above recent highs."""
    if len(highs) < period:
        return False
    recent_high = highs[-period:].max()
    if recent_high == 0:
        return False
    return bool(current_price > recent_high * (1 + threshold_pct / 100))


def stochastic(
    highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, k_period: int = 14, d_period: int = 3
) -> tuple[np.ndarray, np.ndarray]:
    """Stochastic oscillator %K (fast) and %D (SMA of %K), 0-100.

    Flat ranges (highest == lowest) yield a neutral 50.0 to avoid
    false extremes.
    """
    n = len(closes)
    k = np.full(n, np.nan)
    if n >= k_period:
        for i in range(k_period - 1, n):
            hh = float(highs[i - k_period + 1 : i + 1].max())
            ll = float(lows[i - k_period + 1 : i + 1].min())
            if hh == ll:
                k[i] = 50.0
            else:
                k[i] = 100.0 * (float(closes[i]) - ll) / (hh - ll)
    d = np.asarray(pd.Series(k).rolling(window=d_period).mean().values)
    return np.asarray(k), d


def stoch_cross(k: np.ndarray, d: np.ndarray) -> str | None:
    """Last %K/%D cross: 'bullish' (K crosses above D), 'bearish', or None."""
    valid = [i for i in range(len(k)) if not bool(np.isnan(k[i])) and not bool(np.isnan(d[i]))]
    if len(valid) < 2:
        return None
    i1, i2 = valid[-2], valid[-1]
    if k[i1] <= d[i1] and k[i2] > d[i2]:
        return "bullish"
    if k[i1] >= d[i1] and k[i2] < d[i2]:
        return "bearish"
    return None


def pivot_highs(values: np.ndarray, left: int = 2, right: int = 2) -> list[int]:
    """Indices of fractal pivot highs (strictly highest in [i-left, i+right])."""
    out: list[int] = []
    n = len(values)
    for i in range(left, n - right):
        window = values[i - left : i + right + 1]
        if values[i] >= float(np.nanmax(window)) and int(np.sum(window == values[i])) == 1:
            out.append(i)
    return out


def pivot_lows(values: np.ndarray, left: int = 2, right: int = 2) -> list[int]:
    """Indices of fractal pivot lows (strictly lowest in [i-left, i+right])."""
    out: list[int] = []
    n = len(values)
    for i in range(left, n - right):
        window = values[i - left : i + right + 1]
        if values[i] <= float(np.nanmin(window)) and int(np.sum(window == values[i])) == 1:
            out.append(i)
    return out


def detect_divergence(
    closes: np.ndarray,
    oscillator: np.ndarray,
    lookback: int = 60,
    left: int = 2,
    right: int = 2,
    min_bars: int = 5,
) -> dict[str, dict[str, float] | None]:
    """Detect bullish/bearish divergences between price and an oscillator.

    Bearish: price makes a higher pivot high while the oscillator makes
    a lower high. Bullish: price makes a lower pivot low while the
    oscillator makes a higher low. Returns pivot metadata or None.
    """
    result: dict[str, dict[str, float] | None] = {"bullish": None, "bearish": None}
    n = len(closes)
    if n < left + right + 3 or len(oscillator) != n:
        return result
    start = max(0, n - lookback)
    seg_c = closes[start:]
    seg_o = oscillator[start:]

    def _valid(i: int) -> bool:
        return not bool(np.isnan(seg_o[i]))

    highs = pivot_highs(seg_c, left, right)
    highs = [i for i in highs if _valid(i)]
    if len(highs) >= 2:
        i1, i2 = highs[-2], highs[-1]
        if i2 - i1 >= min_bars and seg_c[i2] > seg_c[i1] and seg_o[i2] < seg_o[i1]:
            result["bearish"] = {
                "price_1": float(seg_c[i1]),
                "price_2": float(seg_c[i2]),
                "osc_1": float(seg_o[i1]),
                "osc_2": float(seg_o[i2]),
                "bars_between": float(i2 - i1),
            }
    lows = pivot_lows(seg_c, left, right)
    lows = [i for i in lows if _valid(i)]
    if len(lows) >= 2:
        i1, i2 = lows[-2], lows[-1]
        if i2 - i1 >= min_bars and seg_c[i2] < seg_c[i1] and seg_o[i2] > seg_o[i1]:
            result["bullish"] = {
                "price_1": float(seg_c[i1]),
                "price_2": float(seg_c[i2]),
                "osc_1": float(seg_o[i1]),
                "osc_2": float(seg_o[i2]),
                "bars_between": float(i2 - i1),
            }
    return result


def compute_all_indicators(
    closes: np.ndarray,
    highs: np.ndarray | None = None,
    lows: np.ndarray | None = None,
    volumes: np.ndarray | None = None,
    opens: np.ndarray | None = None,
) -> dict:
    """Compute all technical indicators at once."""
    result = {}

    if len(closes) >= 5:
        result["ema_5"] = ema(closes, 5)[-1] if len(closes) >= 5 else None
        result["ema_9"] = ema(closes, 9)[-1] if len(closes) >= 9 else None

    if len(closes) >= 20:
        result["ema_20"] = ema(closes, 20)[-1] if len(closes) >= 20 else None
        result["sma_20"] = sma(closes, 20)[-1] if len(closes) >= 20 else None
        result["rsi_14"] = rsi(closes, 14)[-1] if len(closes) >= 15 else None

    if len(closes) >= 50:
        result["ema_50"] = ema(closes, 50)[-1] if len(closes) >= 50 else None
        result["sma_50"] = sma(closes, 50)[-1] if len(closes) >= 50 else None

    if len(closes) >= 200:
        result["ema_200"] = ema(closes, 200)[-1] if len(closes) >= 200 else None
        result["sma_200"] = sma(closes, 200)[-1] if len(closes) >= 200 else None

    macd_result = macd(closes)
    result["macd"] = macd_result[0][-1] if len(macd_result[0]) > 0 else None
    result["macd_signal"] = macd_result[1][-1] if len(macd_result[1]) > 0 else None
    result["macd_histogram"] = macd_result[2][-1] if len(macd_result[2]) > 0 else None

    if len(closes) >= 11:
        result["roc_10"] = roc(closes, 10)[-1] if len(closes) >= 11 else None

    if highs is not None and lows is not None and closes is not None:
        atr_result = atr(highs, lows, closes)
        result["atr_14"] = atr_result[-1] if len(atr_result) > 0 else None

    if closes is not None:
        result["bollinger_upper"], result["bollinger_lower"], result["bollinger_bandwidth"] = (
            bollinger_bands(closes)
        )
        result["bollinger_upper"] = (
            result["bollinger_upper"][-1] if result["bollinger_upper"] is not None else None
        )
        result["bollinger_lower"] = (
            result["bollinger_lower"][-1] if result["bollinger_lower"] is not None else None
        )
        result["bollinger_bandwidth"] = (
            result["bollinger_bandwidth"][-1] if result["bollinger_bandwidth"] is not None else None
        )

    if highs is not None and lows is not None and closes is not None:
        result["adx_14"] = adx(highs, lows, closes)
        result["adx_14"] = result["adx_14"][-1] if result["adx_14"] is not None else None

    if volumes is not None and len(volumes) > 0:
        result["volume"] = int(volumes[-1])
        result["avg_volume_20"] = float(volumes[-20:].mean()) if len(volumes) >= 5 else None
        result["rvol_daily"] = relative_volume(
            int(volumes[-1]), volumes[:-1] if len(volumes) > 1 else volumes
        )
        if len(closes) > 0:
            result["dollar_volume"] = dollar_volume(float(closes[-1]), int(volumes[-1]))
    if volumes is not None and closes is not None:
        result["obv"] = obv(closes, volumes)[-1] if len(closes) > 0 else None

    if len(closes) >= 30:
        rsi_vals = rsi(closes, 14)
        rsi_div = detect_divergence(closes, rsi_vals)
        result["rsi_divergence"] = (
            "bearish" if rsi_div["bearish"] else ("bullish" if rsi_div["bullish"] else None)
        )
        _macd_line, _macd_sig, _macd_hist = macd(closes)
        hist = np.nan_to_num(_macd_hist, nan=0.0)
        macd_div = detect_divergence(closes, hist)
        result["macd_divergence"] = (
            "bearish" if macd_div["bearish"] else ("bullish" if macd_div["bullish"] else None)
        )
    else:
        result["rsi_divergence"] = None
        result["macd_divergence"] = None

    if highs is not None and lows is not None and len(closes) >= 20:
        stoch_k, stoch_d = stochastic(highs, lows, closes)
        result["stoch_k"] = float(stoch_k[-1]) if not bool(np.isnan(stoch_k[-1])) else None
        result["stoch_d"] = float(stoch_d[-1]) if not bool(np.isnan(stoch_d[-1])) else None
        result["stoch_cross"] = stoch_cross(stoch_k, stoch_d)
        stoch_div = detect_divergence(closes, np.nan_to_num(stoch_d, nan=50.0))
        result["stoch_divergence"] = (
            "bearish" if stoch_div["bearish"] else ("bullish" if stoch_div["bullish"] else None)
        )
    else:
        result["stoch_k"] = None
        result["stoch_d"] = None
        result["stoch_cross"] = None
        result["stoch_divergence"] = None

    return result
