"""Stealth accumulation / distribution detection (Wyckoff, deterministic).

Institutions cannot hide volume, only intent. This module hunts the
footprints of quiet accumulation in low-float penny stocks using daily
OHLCV alone (no Level 2 / time&sales required):

- absorption: heavy volume with no price progress (churn, tight range)
- money flow persistence: volume consistently done higher in the range
- OBV-vs-price divergence: ledger rising while price flat/falling
- float rotation: full float turning over = stealth change of hands
- volatility contraction: coiled spring before markup
- climax: blow-off volume + weak close after a run = distribution top

Everything is rule-based and explainable. It detects footprints, not
certified institutional prints: without Level 2 / ATS data no system
can prove *who* is buying.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


def clv_series(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray) -> np.ndarray:
    """Close Location Value in [0,1]; flat bars yield 0.5 (neutral)."""
    out = np.full(len(closes), 0.5)
    rng = highs - lows
    tradable = rng > 0
    out[tradable] = (closes[tradable] - lows[tradable]) / rng[tradable]
    return np.asarray(np.clip(out, 0.0, 1.0))


def money_flow_ratio(
    highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, volumes: np.ndarray, window: int = 20
) -> float:
    """Signed volume share over window, in [-1,1]. Positive = accumulation."""
    if len(closes) < window or window <= 0:
        return 0.0
    clv = clv_series(highs[-window:], lows[-window:], closes[-window:])
    signed = (clv * 2.0 - 1.0) * volumes[-window:]
    total = float(volumes[-window:].sum())
    if total <= 0:
        return 0.0
    return float(np.clip(signed.sum() / total, -1.0, 1.0))


def lin_slope(values: np.ndarray) -> float:
    """Per-bar least-squares slope (0 for <2 points)."""
    n = len(values)
    if n < 2:
        return 0.0
    x = np.arange(n, dtype=float)
    with np.errstate(invalid="ignore"):
        slope = np.polyfit(x, values.astype(float), 1)[0]
    return float(slope) if not bool(np.isnan(slope)) else 0.0


def float_rotation(
    volumes: np.ndarray, float_shares: float | None, window: int = 20
) -> float | None:
    """Cumulative volume / float over window. >=1.0 = full turnover."""
    if not float_shares or float_shares <= 0 or len(volumes) < window:
        return None
    return float(volumes[-window:].sum() / float_shares)


def range_contraction(
    highs: np.ndarray, lows: np.ndarray, short: int = 5, long: int = 20
) -> float | None:
    """Recent mean intraday range / historical mean. <1 = contraction."""
    if len(highs) < long or long <= 0:
        return None
    ranges = (highs - lows) / np.maximum(np.abs(lows), 1e-9)
    recent = float(np.mean(ranges[-short:]))
    hist = float(np.mean(ranges[-long:]))
    if hist <= 0:
        return None
    return recent / hist


@dataclass
class AccumulationResult:
    score: int  # 0-100
    phase: str  # accumulation|markup_ready|distribution|neutral
    contributions: dict[str, int] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    metrics: dict[str, float | None] = field(default_factory=dict)


def detect_accumulation(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    volumes: np.ndarray,
    float_shares: float | None = None,
    window: int = 20,
) -> AccumulationResult:
    """Score stealth accumulation 0-100 with phase classification."""
    empty = AccumulationResult(score=0, phase="neutral")
    if len(closes) < window + 1 or len(volumes) < window:
        return empty

    mf = money_flow_ratio(highs, lows, closes, volumes, window)
    obv_vals = np.cumsum(np.sign(np.diff(closes, prepend=closes[0])) * volumes)
    obv_slope = lin_slope(obv_vals[-window:])
    price_slope = lin_slope(closes[-window:])
    contraction = range_contraction(highs, lows)
    rotation = float_rotation(volumes, float_shares, window)
    avg_rvol = float(volumes[-5:].mean() / max(volumes[-window:-5].mean(), 1e-9))

    # absorption: heavy volume, no progress (low price efficiency)
    path = float(np.sum(np.abs(np.diff(closes[-window:])))) or 1e-9
    drift = abs(float(closes[-1] - closes[-window]))
    efficiency = drift / path  # ~0 = churn, ~1 = trending
    absorption = min(avg_rvol / 3.0, 1.0) * (1.0 - min(efficiency * 3.0, 1.0))

    contrib = {
        "absorption": int(absorption * 30),
        "money_flow": int((mf + 1.0) / 2.0 * 25),
        "obv_divergence": 20
        if (obv_slope > 0 and price_slope <= 0)
        else int(max(0.0, min(1.0, obv_slope / (abs(price_slope) + 1e-9))) * 10),
        "rotation": int(min((rotation or 0.0) / 2.0, 1.0) * 15) if rotation is not None else 0,
        "contraction": int(max(0.0, min(1.0, 1.0 - (contraction or 1.0))) * 10)
        if contraction is not None
        else 0,
    }
    score = int(max(0, min(100, sum(contrib.values()))))

    reasons: list[str] = []
    if absorption >= 0.5:
        reasons.append(
            f"absorción: volumen {avg_rvol:.1f}x sin progreso (eficiencia {efficiency:.2f})"
        )
    if mf > 0.2:
        reasons.append(f"flujo positivo persistente ({mf:+.2f} en {window} sesiones)")
    if obv_slope > 0 >= price_slope:
        reasons.append("OBV sube con precio plano/bajista: compra oculta")
    if rotation is not None and rotation >= 1.0:
        reasons.append(f"rotación de float {rotation:.1f}x: cambio de manos sigiloso")
    if contraction is not None and contraction < 0.7:
        reasons.append(f"compresión de volatilidad ({contraction:.2f}): muelle cargado")

    phase = "neutral"
    if score >= 60:
        phase = "accumulation"
    elif score <= 25 and mf < -0.2:
        phase = "distribution"

    return AccumulationResult(
        score=score,
        phase=phase,
        contributions=contrib,
        reasons=reasons,
        metrics={
            "money_flow_ratio": round(mf, 3),
            "obv_slope": round(obv_slope, 1),
            "price_slope": round(price_slope, 4),
            "efficiency": round(efficiency, 3),
            "avg_rvol_5d": round(avg_rvol, 2),
            "float_rotation": round(rotation, 2) if rotation is not None else None,
            "range_contraction": round(contraction, 3) if contraction is not None else None,
        },
    )


def detect_climax(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    volumes: np.ndarray,
    runup_days: int = 5,
    min_runup_pct: float = 30.0,
) -> dict[str, object] | None:
    """Blow-off top: climactic volume + wide range + weak close after a run.

    Returns evidence dict, or None. A climax means distribution, not
    accumulation: do NOT chase it.
    """
    n = len(closes)
    if n < 25:
        return None
    avg_vol = float(volumes[-21:-1].mean())
    last_vol = float(volumes[-1])
    ranges = (highs - lows) / np.maximum(np.abs(lows), 1e-9)
    avg_range = float(ranges[-21:-1].mean())
    last_range = float(ranges[-1])
    base = abs(float(closes[-1 - runup_days])) or 1e-9
    runup = (float(closes[-1]) - float(closes[-1 - runup_days])) / base * 100
    clv_last = clv_series(highs[-1:], lows[-1:], closes[-1:])[0]
    if last_vol >= 3.0 * avg_vol and last_range >= 2.0 * avg_range and runup >= min_runup_pct:
        return {
            "type": "climax" if clv_last < 0.5 else "climax_churn",
            "volume_multiple": round(last_vol / max(avg_vol, 1e-9), 1),
            "runup_pct": round(runup, 1),
            "weak_close": bool(clv_last < 0.5),
        }
    return None


def detect_markup_readiness(
    closes: np.ndarray,
    volumes: np.ndarray,
    acc: AccumulationResult,
    lookback_high_days: int = 20,
) -> tuple[bool, list[str]]:
    """Accumulation base + fresh 20d breakout on expanding volume."""
    if acc.phase != "accumulation" or len(closes) < lookback_high_days + 1:
        return False, []
    prior_high = float(closes[-lookback_high_days - 1 : -1].max())
    if closes[-1] <= prior_high:
        return False, []
    if len(volumes) < 6:
        return False, []
    expanding = float(volumes[-3:].mean()) > float(volumes[-6:-3].mean())
    if not expanding:
        return False, []
    return True, [
        f"base de acumulación (score {acc.score}) + ruptura 20d con volumen en expansión",
    ]
