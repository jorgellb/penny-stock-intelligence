"""Round-level gates applied after per-symbol evaluation.

Mutates SignalEvent actions/reasons in place. SELLs are never blocked.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from app.signals import SignalAction, SignalEvent
from app.signals.regime import (
    MarketRegime,
    classify_regime,
    correlation_filter,
    regime_buy_thresholds,
)


@dataclass
class RoundGateState:
    regime: MarketRegime = MarketRegime.RISK_ON
    thresholds: dict[str, float] = field(default_factory=dict)
    corr_dropped: list[str] = field(default_factory=list)
    buys_capped: int = 0


def compute_regime(
    evaluated: list[tuple[SignalEvent, dict[str, Any]]],
    monitor_cfg: Any,
    halts_today_fn: Any,
) -> tuple[MarketRegime, dict[str, float]]:
    """Breadth stats → market regime + buy thresholds for this round."""
    thresholds: dict[str, float] = {
        "min_score": float(monitor_cfg.buy_min_score),
        "min_rvol": float(monitor_cfg.buy_min_rvol),
    }
    if not monitor_cfg.regime_enabled or not evaluated:
        return MarketRegime.RISK_ON, thresholds

    above = sum(
        1
        for _, d in evaluated
        if d.get("vwap_distance_pct") is not None and d["vwap_distance_pct"] > 0
    )
    known = sum(1 for _, d in evaluated if d.get("vwap_distance_pct") is not None)
    breadth = (above / known * 100.0) if known else 50.0
    changes = [float(d.get("change_pct", 0.0)) for _, d in evaluated]
    median_change = float(np.median(changes)) if changes else 0.0
    halts = sum(1 for _, d in evaluated if d.get("halted"))
    halts += sum(halts_today_fn(e.symbol) for e, _ in evaluated)
    regime = classify_regime(
        breadth,
        median_change,
        halts,
        halt_storm_threshold=monitor_cfg.halt_storm_threshold,
    )
    return regime, regime_buy_thresholds(regime, monitor_cfg)


def apply_regime_gate(
    evaluated: list[tuple[SignalEvent, dict[str, Any]]],
    regime: MarketRegime,
    thresholds: dict[str, float],
    enabled: bool,
) -> None:
    if not enabled:
        return
    for event, details in evaluated:
        if event.action != SignalAction.BUY:
            continue
        if regime == MarketRegime.HALT_STORM:
            event.action = SignalAction.HOLD
            event.reasons = ["régimen HALT_STORM: cero compras nuevas, solo exits"] + event.reasons
        elif (
            event.score < thresholds["min_score"]
            or float(details.get("rvol", 0.0)) < thresholds["min_rvol"]
        ):
            event.action = SignalAction.HOLD
            event.reasons = [
                f"régimen {regime.value}: exige score>={thresholds['min_score']:.0f} "
                f"y RVOL>={thresholds['min_rvol']:.1f}x"
            ] + event.reasons


def apply_correlation_gate(
    evaluated: list[tuple[SignalEvent, dict[str, Any]]],
    monitor_cfg: Any,
) -> list[str]:
    """Demote correlated BUY clones. Returns dropped symbols."""
    if not monitor_cfg.correlation_enabled:
        return []
    cands = [
        {"symbol": e.symbol, "score": e.score} for e, _ in evaluated if e.action == SignalAction.BUY
    ]
    if len(cands) <= 1:
        return []
    series = {
        e.symbol: np.array(d["returns_5m"], dtype=float)
        for e, d in evaluated
        if e.action == SignalAction.BUY and d.get("returns_5m") is not None
    }
    kept = correlation_filter(cands, series, max_corr=monitor_cfg.max_corr)
    kept_syms = {
        str(c["symbol"])
        for c in kept
        if "corr_note" not in c or "descartado" not in str(c.get("corr_note", ""))
    }
    dropped = [str(c["symbol"]) for c in cands if str(c["symbol"]) not in kept_syms]
    for event, _ in evaluated:
        if event.symbol in dropped and event.action == SignalAction.BUY:
            note = next(
                (c.get("corr_note", "") for c in kept if c.get("symbol") == event.symbol),
                "",
            )
            event.action = SignalAction.HOLD
            event.reasons = [
                f"correlación: clon de otro candidato (|rho|>{monitor_cfg.max_corr}) "
                f"— se queda el de mayor score. {note}".strip()
            ] + event.reasons
    return dropped


def apply_exit_rules(
    evaluated: list[tuple[SignalEvent, dict[str, Any]]],
    monitor_cfg: Any,
    position_pnl_pct: Any,
) -> None:
    """Take-profit / stop-loss on open paper positions → SELL."""
    take_profit = monitor_cfg.sell_take_profit_pct
    stop_loss = monitor_cfg.sell_stop_loss_pct
    if (take_profit is None and stop_loss is None) or not evaluated:
        return
    for event, _details in evaluated:
        if event.action == SignalAction.SELL:
            continue
        pnl = position_pnl_pct(event.symbol)
        if pnl is None:
            continue
        if take_profit is not None and pnl >= take_profit:
            event.action = SignalAction.SELL
            event.reasons = [
                f"take-profit: posición {pnl:+.2f}% >= +{take_profit:.2f}%"
            ] + event.reasons
        elif stop_loss is not None and pnl <= -abs(stop_loss):
            event.action = SignalAction.SELL
            event.reasons = [
                f"stop-loss: posición {pnl:+.2f}% <= -{abs(stop_loss):.2f}%"
            ] + event.reasons


def apply_breadth_cap(
    evaluated: list[tuple[SignalEvent, dict[str, Any]]],
    max_buys: int | None,
) -> int:
    """Keep at most N BUYs (best score). Returns how many were capped."""
    if max_buys is None or max_buys < 0:
        return 0
    ranked_buys = sorted(
        (e for e, _ in evaluated if e.action == SignalAction.BUY),
        key=lambda e: (e.score, e.symbol),
        reverse=True,
    )
    capped = 0
    for extra in ranked_buys[max_buys:]:
        extra.action = SignalAction.HOLD
        extra.reasons = [
            f"límite {max_buys} compras/ronda: se quedan las de mayor score"
        ] + extra.reasons
        capped += 1
    return capped
