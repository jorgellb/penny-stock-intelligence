"""Opportunity radar — rank liquid movers before they hit a watchlist.

Pure ranking over market snapshots (no I/O). The job layer fetches quotes
and persists winners into the ``radar`` list for the monitor to evaluate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Opportunity:
    symbol: str
    rank_score: float
    change_pct: float
    rvol: float
    price: float
    dollar_volume: float
    setups_hint: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


def _setup_hints(change_pct: float, rvol: float, score_proxy: float) -> list[str]:
    hints: list[str] = []
    if change_pct >= 5.0 and rvol >= 2.0:
        hints.append("gap_and_go")
    if rvol >= 2.0 and score_proxy >= 70 and change_pct > 0:
        hints.append("momentum_vwap")
    if rvol >= 2.5 and change_pct >= 3.0:
        hints.append("catalyst_impulse")
    if rvol >= 1.5 and change_pct >= 1.0:
        hints.append("accumulation_markup")
    return hints


def rank_opportunities(
    rows: list[dict[str, Any]],
    *,
    min_score: float = 55.0,
    min_rvol: float = 1.5,
    min_change_pct: float = 2.0,
    max_results: int = 40,
) -> list[Opportunity]:
    """Rank candidate dicts with keys: symbol, price, change_pct, rvol, volume.

    ``score_proxy`` is optional (0-100); when missing, derived from change+rvol.
    """
    out: list[Opportunity] = []
    for row in rows:
        sym = str(row.get("symbol", "")).upper().strip()
        if not sym:
            continue
        try:
            price = float(row.get("price") or 0)
            change = float(row.get("change_pct") or 0)
            rvol = float(row.get("rvol") or 0)
            volume = float(row.get("volume") or 0)
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue
        if change < min_change_pct or rvol < min_rvol:
            continue
        proxy = row.get("score_proxy")
        try:
            score_proxy = float(proxy) if proxy is not None else min(
                100.0, max(0.0, change * 4.0 + rvol * 12.0)
            )
        except (TypeError, ValueError):
            score_proxy = min(100.0, max(0.0, change * 4.0 + rvol * 12.0))
        if score_proxy < min_score:
            continue
        dollar = price * volume
        hints = _setup_hints(change, rvol, score_proxy)
        # Composite: emphasize relative volume and gap size.
        rank = score_proxy * 0.45 + min(rvol, 10.0) * 8.0 + min(change, 40.0) * 1.2
        if dollar >= 1_000_000:
            rank += 5.0
        reasons = [
            f"proxy score {score_proxy:.0f}",
            f"cambio {change:+.2f}%",
            f"RVOL {rvol:.1f}x",
            f"dollar vol ${dollar:,.0f}",
        ]
        if hints:
            reasons.append(f"setups posibles: {', '.join(hints)}")
        out.append(
            Opportunity(
                symbol=sym,
                rank_score=round(rank, 2),
                change_pct=round(change, 2),
                rvol=round(rvol, 2),
                price=price,
                dollar_volume=round(dollar, 2),
                setups_hint=hints,
                reasons=reasons,
            )
        )
    out.sort(key=lambda o: o.rank_score, reverse=True)
    return out[: max(1, max_results)]
