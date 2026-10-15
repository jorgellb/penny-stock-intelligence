"""Gap + premarket + intraday scanners."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class GapInfo:
    symbol: str
    previous_close: float
    premarket_last: float | None = None
    official_open: float | None = None
    gap_pct: float = 0.0
    premarket_volume: int | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


def gap_percent(previous_close: float, current: float) -> float:
    if not previous_close:
        return 0.0
    return (current - previous_close) / previous_close * 100


@dataclass
class RankedSymbol:
    symbol: str
    score: int
    price: float
    change_pct: float = 0.0
    gap_pct: float = 0.0
    rvol: float = 0.0
    dollar_volume: float = 0.0
    reasons: list[str] = field(default_factory=list)


def rank_premarket(rows: list[dict]) -> list[RankedSymbol]:
    ranked = []
    for r in rows:
        score = 0
        if r.get("gap_pct", 0) >= 5:
            score += 30
        if r.get("rvol", 0) >= 3:
            score += 30
        if r.get("dollar_volume", 0) >= 1_000_000:
            score += 20
        if r.get("catalyst_strength") == "strong":
            score += 20
        ranked.append(
            RankedSymbol(
                symbol=r["symbol"],
                score=min(score, 100),
                price=r.get("price", 0.0),
                change_pct=r.get("change_pct", 0.0),
                gap_pct=r.get("gap_pct", 0.0),
                rvol=r.get("rvol", 0.0),
                dollar_volume=r.get("dollar_volume", 0.0),
            )
        )
    return sorted(ranked, key=lambda x: x.score, reverse=True)


def rank_intraday(rows: list[dict]) -> list[RankedSymbol]:
    ranked = []
    for r in rows:
        score = 0
        if r.get("vwap_distance_pct", 0) > 0:
            score += 20
        if r.get("rvol", 0) >= 2:
            score += 30
        if r.get("breakout_20d"):
            score += 25
        if r.get("rsi14", 50) >= 60:
            score += 15
        ranked.append(
            RankedSymbol(
                symbol=r["symbol"],
                score=min(score, 100),
                price=r.get("price", 0.0),
                change_pct=r.get("change_pct", 0.0),
                rvol=r.get("rvol", 0.0),
                dollar_volume=r.get("dollar_volume", 0.0),
            )
        )
    return sorted(ranked, key=lambda x: x.score, reverse=True)
