"""Market regime + correlation filters for the penny universe.

Regimes gate global aggressiveness; the correlation filter prevents
loading 5 positions on the same sectorial pump (basket manipulation).
"""

from __future__ import annotations

from enum import Enum

import numpy as np


class MarketRegime(str, Enum):
    RISK_ON = "risk_on"
    CHOP = "chop"
    RISK_OFF = "risk_off"
    HALT_STORM = "halt_storm"


def classify_regime(
    breadth_above_vwap_pct: float,
    median_change_pct: float,
    halts_today: int,
    halt_storm_threshold: int = 10,
) -> MarketRegime:
    """Classify the penny-universe regime from breadth stats."""
    if halts_today >= halt_storm_threshold:
        return MarketRegime.HALT_STORM
    if breadth_above_vwap_pct >= 60.0 and median_change_pct > 1.0:
        return MarketRegime.RISK_ON
    if breadth_above_vwap_pct <= 35.0 or median_change_pct < -1.5:
        return MarketRegime.RISK_OFF
    return MarketRegime.CHOP


def regime_buy_thresholds(regime: MarketRegime, cfg: object | None = None) -> dict[str, float]:
    """Stricter BUY gates in chop/risk-off; no new BUYs in halt storms.

    Thresholds for CHOP/RISK_OFF come from monitor config when provided
    (defaults preserve historical behavior).
    """
    if regime == MarketRegime.RISK_ON:
        return {"min_score": 70.0, "min_rvol": 2.0}
    if regime == MarketRegime.HALT_STORM:
        return {"min_score": 101.0, "min_rvol": 999.0}  # unreachable: exits only
    if regime == MarketRegime.CHOP:
        return {
            "min_score": float(getattr(cfg, "regime_chop_min_score", 80.0)),
            "min_rvol": float(getattr(cfg, "regime_chop_min_rvol", 4.0)),
        }
    return {
        "min_score": float(getattr(cfg, "regime_riskoff_min_score", 80.0)),
        "min_rvol": float(getattr(cfg, "regime_riskoff_min_rvol", 4.0)),
    }


def correlation_filter(
    candidates: list[dict],
    returns_5m: dict[str, np.ndarray],
    max_corr: float = 0.85,
) -> list[dict]:
    """Keep the highest-scored candidate per highly-correlated cluster.

    Each candidate needs `symbol` and `score` keys. Symbols without
    return series are kept (benefit of the doubt, flagged).
    """
    if len(candidates) <= 1:
        return candidates
    ranked = sorted(candidates, key=lambda c: c.get("score", 0), reverse=True)
    kept: list[dict] = []
    for cand in ranked:
        sym = cand["symbol"]
        series = returns_5m.get(sym)
        if series is None or len(series) < 10:
            kept.append({**cand, "corr_note": "sin serie 5m"})
            continue
        clash = False
        for other in kept:
            oseries = returns_5m.get(other["symbol"])
            if oseries is None or len(oseries) < 10:
                continue
            n = min(len(series), len(oseries))
            with np.errstate(invalid="ignore"):
                corr = np.corrcoef(series[-n:], oseries[-n:])[0, 1]
            if not np.isnan(corr) and abs(float(corr)) > max_corr:
                clash = True
                cand = {**cand, "corr_note": f"descartado: rho={corr:.2f} con {other['symbol']}"}
                break
        if not clash:
            kept.append(cand)
    return kept
