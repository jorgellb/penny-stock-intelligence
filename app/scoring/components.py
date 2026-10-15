"""Composite 0-100 sub-scores feeding the weighted ScoringEngine.

Each function is pure, deterministic and returns the sub-score plus the
facts behind it, so every point in the final score stays explainable.

Design notes (penny/micro-cap momentum):
- Volume saturating at RVOL 2x made a sleepy 2x name tie with a 15x
  runner. RVOL is now log-scaled (2x≈30, 5x≈70, 10x+=100) and float
  rotation (session volume / float) adds conviction.
- A +8% day means nothing for a stock that moves 20% a day and a lot for
  one that moves 3%: momentum is measured in ATR units.
- "Technical" used to be the raw RSI value (RSI 95 = max score, i.e. it
  rewarded exhaustion). It is now trend structure + proximity to highs +
  RSI regime + MACD impulse + volatility contraction.
- Liquidity is about whether you can get out: dollar volume first,
  spread second (unknown spread is neutral, never a free pass).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from app.indicators import bb_width_percentile, ema, macd, pct_from_high, rsi


def _clip(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def volume_component(rvol: float | None, float_rotation: float | None = None) -> float:
    """0-100 from relative volume (log-scaled) + float rotation bonus."""
    if rvol is None or rvol <= 0:
        return 0.0
    base = 0.0 if rvol <= 1.0 else _clip(math.log(rvol) / math.log(10.0) * 100.0)
    if float_rotation is not None and float_rotation > 0:
        # 0.5x float traded today = +8, 1x = +15 (capped)
        base += _clip(float_rotation * 15.0, 0.0, 15.0)
    return round(_clip(base), 1)


def momentum_component(
    change_pct: float,
    atr_pct: float | None = None,
    roc_5: float | None = None,
    vwap_distance_pct: float | None = None,
) -> float:
    """0-100 momentum: day move in ATR units + multi-day drift + VWAP hold."""
    if change_pct <= 0:
        day = 0.0
    elif atr_pct and atr_pct > 0:
        day = _clip(change_pct / atr_pct / 2.0, 0.0, 1.0) * 65.0  # 2 ATR move = full
    else:
        day = _clip(change_pct / 15.0, 0.0, 1.0) * 65.0
    drift = 0.0
    if roc_5 is not None and roc_5 > 0:
        drift = _clip(roc_5 / 30.0, 0.0, 1.0) * 15.0
    hold = 0.0
    if vwap_distance_pct is None:
        hold = 10.0 if change_pct > 0 else 0.0  # unknown: half credit on green days
    elif vwap_distance_pct > 0:
        hold = 20.0
    return round(_clip(day + drift + hold), 1)


def liquidity_component(
    dollar_volume: float | None,
    spread_pct: float | None = None,
) -> float:
    """0-100: log-scaled dollar volume, multiplied by a spread quality factor."""
    dv = float(dollar_volume or 0.0)
    if dv <= 250_000:
        base = _clip(dv / 250_000 * 15.0)
    else:
        # $250k → 15, $1M → ~45, $5M → ~80, $20M+ → 100
        base = _clip(15.0 + math.log(dv / 250_000) / math.log(80.0) * 85.0)
    if spread_pct is None:
        factor = 0.9
    elif spread_pct <= 0.5:
        factor = 1.0
    elif spread_pct <= 1.0:
        factor = 0.95
    elif spread_pct <= 2.5:
        factor = 0.8
    elif spread_pct <= 5.0:
        factor = 0.6
    else:
        factor = 0.3
    return round(_clip(base * factor), 1)


@dataclass
class TechnicalView:
    score: float
    facts: dict[str, Any] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)


def technical_component(
    closes: np.ndarray,
    highs: np.ndarray | None = None,
    lows: np.ndarray | None = None,
) -> TechnicalView | None:
    """Composite technical score from daily bars (None if < 20 bars)."""
    closes = np.asarray(closes, dtype=float)
    n = len(closes)
    if n < 20:
        return None
    price = float(closes[-1])
    facts: dict[str, Any] = {}
    reasons: list[str] = []
    pts = 0.0

    # 1) Trend structure (30)
    e9 = ema(closes, 9)
    e20 = ema(closes, 20)
    e50 = ema(closes, 50) if n >= 50 else None
    trend = 0.0
    if price > e9[-1]:
        trend += 8
    if e9[-1] > e20[-1]:
        trend += 8
    if e50 is not None and price > e50[-1]:
        trend += 7
    elif e50 is None and price > e20[-1]:
        trend += 4
    if n >= 25 and e20[-1] > e20[-5]:
        trend += 7
    facts.update(
        ema_9=round(float(e9[-1]), 4),
        ema_20=round(float(e20[-1]), 4),
        ema_50=round(float(e50[-1]), 4) if e50 is not None else None,
    )
    if trend >= 23:
        reasons.append("tendencia alcista alineada (precio > EMA9 > EMA20, EMA20 subiendo)")
    pts += trend

    # 2) Proximity to highs / breakout (25)
    hi = highs if highs is not None else closes
    d20 = pct_from_high(closes, np.asarray(hi, dtype=float), 20)
    d252 = pct_from_high(closes, np.asarray(hi, dtype=float), min(252, n - 1)) if n > 60 else None
    prox = 0.0
    if d20 is not None:
        if d20 == 0:
            prox = 25
            reasons.append("ruptura del máximo de 20 días")
        elif d20 <= 5:
            prox = 18
        elif d20 <= 10:
            prox = 10
        elif d20 <= 20:
            prox = 4
    if d252 is not None and d252 <= 5 and prox < 25:
        prox = min(25.0, prox + 5)
    facts.update(pct_from_20d_high=d20, pct_from_52w_high=d252)
    pts += prox

    # 3) RSI regime (20): reward strength, not exhaustion
    r = rsi(closes, 14)
    rsi_last = float(r[-1]) if not np.isnan(r[-1]) else None
    regime = 0.0
    if rsi_last is not None:
        if 55 <= rsi_last <= 75:
            regime = 20
        elif 50 <= rsi_last < 55 or 75 < rsi_last <= 85:
            regime = 12
        elif rsi_last > 85:
            regime = 5
            reasons.append(f"RSI {rsi_last:.0f}: sobreextendido, riesgo de reversión")
        elif rsi_last >= 30:
            regime = 4
    facts["rsi_14"] = round(rsi_last, 1) if rsi_last is not None else None
    pts += regime

    # 4) MACD impulse (15)
    impulse = 0.0
    if n >= 35:
        _, _, hist = macd(closes)
        h1, h0 = float(hist[-1]), float(hist[-2])
        if not (np.isnan(h1) or np.isnan(h0)):
            if h1 > 0:
                impulse += 8
            if h1 > h0:
                impulse += 7
            facts["macd_hist"] = round(h1, 5)
    pts += impulse

    # 5) Volatility contraction (10): coiled spring before expansion
    bwp = bb_width_percentile(closes)
    coil = 5.0
    if bwp is not None:
        if bwp <= 20:
            coil = 10.0
            reasons.append("compresión de volatilidad (Bollinger estrecho)")
        elif bwp >= 90:
            coil = 3.0
    facts["bb_width_pctile"] = round(bwp, 1) if bwp is not None else None
    pts += coil

    return TechnicalView(score=round(_clip(pts), 1), facts=facts, reasons=reasons)


@dataclass
class ExtensionCheck:
    overextended: bool
    reasons: list[str] = field(default_factory=list)


def extension_check(
    price: float,
    vwap: float | None,
    atr: float | None,
    rsi_14: float | None,
    change_pct: float,
    max_vwap_atr: float = 1.0,
    max_vwap_pct: float = 15.0,
    max_rsi: float = 88.0,
    max_change_pct: float = 150.0,
) -> ExtensionCheck:
    """Chase guard: entering far above VWAP/ATR is where penny runners trap buyers."""
    reasons: list[str] = []
    if vwap and vwap > 0 and price > vwap:
        dist_pct = (price - vwap) / vwap * 100
        if atr and atr > 0 and (price - vwap) / atr > max_vwap_atr:
            reasons.append(
                f"precio {(price - vwap) / atr:.1f} ATR sobre VWAP (> {max_vwap_atr:.1f})"
            )
        elif dist_pct > max_vwap_pct:
            reasons.append(f"precio +{dist_pct:.1f}% sobre VWAP (> {max_vwap_pct:.0f}%)")
    if rsi_14 is not None and rsi_14 > max_rsi:
        reasons.append(f"RSI {rsi_14:.0f} > {max_rsi:.0f}")
    if change_pct > max_change_pct:
        reasons.append(f"día +{change_pct:.0f}% (> {max_change_pct:.0f}%)")
    return ExtensionCheck(overextended=bool(reasons), reasons=reasons)
