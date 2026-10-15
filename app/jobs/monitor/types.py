"""Monitor domain types and pure scoring helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


def impact_rank(impact: object) -> int:
    return {"high": 3, "medium": 2, "low": 1}.get(str(impact).lower(), 0)


def enum_val(value: object) -> str:
    """Raw value of a (str) enum, or str() as fallback."""
    return str(getattr(value, "value", value))


@dataclass
class SymbolState:
    score: int = 0
    above_vwap: bool | None = None
    blocking: list[str] = field(default_factory=list)
    price: float = 0.0
    last_signal: str = "hold"
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class MonitoredEvent:
    symbol: str
    action: str
    price: float
    score: int
    reasons: list[str]
    sent: bool
    order_template: dict[str, Any] | None = None
    change_pct: float = 0.0
    rvol: float = 0.0
    dollar_volume: float = 0.0
    risk_flags: list[str] = field(default_factory=list)
    catalyst_summary: str | None = None
    vwap_distance_pct: float | None = None
    providers: list[str] = field(default_factory=list)
    setup: str | None = None
    matched_setups: list[str] = field(default_factory=list)
    trade_plan: dict[str, Any] | None = None
    grade: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class MarketData:
    """Fetched market bundle for one symbol.

    Separates I/O (quotes, bars, VWAP) from the pure compute/signal steps
    in `evaluate_symbol`. Field names mirror the former locals on purpose.
    """

    quote: Any
    price_f: float
    spread: float | None
    feed_lag_stale: bool
    feed_max_lag_ms: int
    bars: list
    closes: Any
    volumes: Any
    change_pct: float
    rvol: float
    bars_5m: list
    vwap_now: float | None
    vwap_distance: float | None
    live: Any = None  # LiveSession (session phase, prev close, HOD/LOD, OR, premarket)


def momentum_score(change_pct: float) -> float:
    """0-100 momentum mapped from day change (deterministic, unit-tested)."""
    return max(0.0, min(100.0, change_pct * 5.0))


def liquidity_score(spread_pct: float | None) -> float:
    """0-100 liquidity mapped from bid/ask spread (None spread = 90)."""
    spread = spread_pct or 0.0
    if spread <= 1.0:
        return 90.0
    if spread <= 2.5:
        return 70.0
    return 50.0
