"""Deterministic buy/sell signal rules for monitored lists.

Signals are rule-based triggers for *human review*, not recommendations:
a BUY signal means the symbol matches at least one configured setup, never
that the price will rise. Every signal carries its reasons and setup id.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from app.config import get_settings
from app.signals.setups import best_setup, match_setups


class SignalAction(str, Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass
class SignalInput:
    """Snapshot used to evaluate signals for one symbol."""

    symbol: str
    price: float
    score: int
    rvol: float = 0.0
    change_pct: float = 0.0
    vwap_distance_pct: float | None = None
    spread_pct: float | None = None
    blocking_flags: list[str] = field(default_factory=list)
    stale: bool = False
    halted: bool = False
    buys_frozen: bool = False
    # entry-gate context (None/False = gate off)
    dollar_volume: float | None = None
    has_catalyst: bool = False
    # multi-setup features (populated by MonitorService)
    donchian_pass: bool = False
    markup_ready: bool = False
    squeeze_active: bool = False
    catalyst_impact: str | None = None
    catalyst_confidence: float | None = None
    float_shares: float | None = None
    # previous evaluation state (for SELL transitions)
    prev_score: int | None = None
    prev_above_vwap: bool | None = None
    prev_blocking_flags: list[str] = field(default_factory=list)


@dataclass
class SignalEvent:
    """Result of evaluating one symbol."""

    symbol: str
    action: SignalAction
    price: float
    score: int
    reasons: list[str] = field(default_factory=list)
    setup: str | None = None
    matched_setups: list[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def is_actionable(self) -> bool:
        return self.action in (SignalAction.BUY, SignalAction.SELL)

    def describe(self) -> str:
        head = {
            SignalAction.BUY: "POSIBLE COMPRA (revisar)",
            SignalAction.SELL: "POSIBLE VENTA (revisar)",
            SignalAction.HOLD: "HOLD",
        }[self.action]
        setup_bit = f" [{self.setup}]" if self.setup else ""
        lines = [f"{head}: {self.symbol} @ ${self.price:.2f} (score {self.score}){setup_bit}"]
        lines.extend(f"- {r}" for r in self.reasons)
        lines.append("Señal automática para revisión manual, no es recomendación.")
        return "\n".join(lines)


def _cfg() -> Any:
    return get_settings().monitor


def evaluate_buy(inp: SignalInput, cfg: Any | None = None) -> list[str]:
    """Return BUY reasons from the best matching setup, or [].

    Kept for backward-compatible tests; prefers multi-setup matching.
    """
    cfg = cfg or _cfg()
    match = best_setup(inp, cfg)
    return list(match.reasons) if match else []


def evaluate_sell(inp: SignalInput, cfg: Any | None = None) -> list[str]:
    """Return SELL reasons, or [] when nothing triggers."""
    cfg = cfg or _cfg()
    if inp.stale:
        return []
    reasons: list[str] = []
    new_blocks = set(inp.blocking_flags) - set(inp.prev_blocking_flags)
    critical_new = new_blocks & set(cfg.block_flags)
    if critical_new:
        reasons.append(f"nuevo riesgo bloqueante: {', '.join(sorted(critical_new))}")
    if inp.prev_score is not None and inp.prev_score - inp.score >= cfg.sell_score_drop:
        reasons.append(f"score cae {inp.prev_score} -> {inp.score} (>= {cfg.sell_score_drop})")
    if (
        inp.vwap_distance_pct is not None
        and inp.prev_above_vwap
        and inp.vwap_distance_pct <= -abs(cfg.sell_vwap_break_pct)
    ):
        reasons.append(f"pierde VWAP ({inp.vwap_distance_pct:.2f}%)")
    return reasons


def evaluate(inp: SignalInput, cfg: Any | None = None) -> SignalEvent:
    """Evaluate BUY via multi-setup engine, then SELL; HOLD otherwise."""
    cfg = cfg or _cfg()
    if inp.halted:
        return SignalEvent(
            symbol=inp.symbol,
            action=SignalAction.HOLD,
            price=inp.price,
            score=inp.score,
            reasons=["halt activo: señales congeladas (solo HOLD)"],
        )
    matches = match_setups(inp, cfg)
    if matches:
        best = matches[0]
        extra: list[str] = []
        if len(matches) > 1:
            others = ", ".join(m.name for m in matches[1:])
            extra.append(f"también coincide: {others}")
        return SignalEvent(
            symbol=inp.symbol,
            action=SignalAction.BUY,
            price=inp.price,
            score=inp.score,
            reasons=list(best.reasons) + extra,
            setup=best.name,
            matched_setups=[m.name for m in matches],
        )
    sell_reasons = evaluate_sell(inp, cfg)
    if sell_reasons:
        return SignalEvent(
            symbol=inp.symbol,
            action=SignalAction.SELL,
            price=inp.price,
            score=inp.score,
            reasons=sell_reasons,
        )
    return SignalEvent(
        symbol=inp.symbol,
        action=SignalAction.HOLD,
        price=inp.price,
        score=inp.score,
        reasons=["sin setup coincidente"],
    )
