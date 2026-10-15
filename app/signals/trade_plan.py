"""Trade plan for every BUY: entry, structural stop, R-multiple targets, grade.

A signal without a stop and a target is an opinion. Every BUY now ships
with a concrete, explainable plan for manual execution:

- Entry: the signal price (limit; the order template adds the offset).
- Stop: the tightest *structural* level (VWAP, opening-range low, day
  low, premarket high for gap plays) that sits at least `min_stop_pct`
  below entry — tighter than that is noise. Falls back to 1 daily ATR and
  is clamped at `max_stop_pct` so a runner never carries a 30% stop.
- Targets: 1R / 2R / 3R. The nearest overhead resistance (20d high) is
  reported so the reviewer sees if T2 runs into supply.
- Grade: A/B/C from confluence (score, # setups, catalyst, R:R, trend).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class TradePlan:
    entry: float
    stop: float
    stop_basis: str
    risk_per_share: float
    risk_pct: float
    targets: list[float]
    reward_risk: float  # to T2 (or to resistance if lower)
    resistance: float | None = None
    grade: str = "C"
    grade_reasons: list[str] = field(default_factory=list)
    breakeven_after: float | None = None  # move stop to entry once T1 trades

    def as_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["entry"] = round(self.entry, 4)
        out["stop"] = round(self.stop, 4)
        out["risk_per_share"] = round(self.risk_per_share, 4)
        out["risk_pct"] = round(self.risk_pct, 2)
        out["targets"] = [round(t, 4) for t in self.targets]
        out["reward_risk"] = round(self.reward_risk, 2)
        if self.resistance is not None:
            out["resistance"] = round(self.resistance, 4)
        if self.breakeven_after is not None:
            out["breakeven_after"] = round(self.breakeven_after, 4)
        return out

    def describe(self) -> str:
        t = " / ".join(f"${x:.4g}" for x in self.targets)
        return (
            f"plan [{self.grade}]: entrada ${self.entry:.4g} · stop ${self.stop:.4g} "
            f"({self.stop_basis}, -{self.risk_pct:.1f}%) · objetivos {t} · "
            f"R:R {self.reward_risk:.1f}"
        )


def build_trade_plan(
    price: float,
    atr: float | None = None,
    vwap: float | None = None,
    day_low: float | None = None,
    opening_range_low: float | None = None,
    premarket_high: float | None = None,
    resistance: float | None = None,
    setup: str | None = None,
    min_stop_pct: float = 3.0,
    max_stop_pct: float = 12.0,
) -> TradePlan | None:
    """Build an entry/stop/targets plan. None when price is unusable."""
    if price <= 0:
        return None
    floor_px = price * (1 - min_stop_pct / 100)  # stops must sit at/below this
    cap_px = price * (1 - max_stop_pct / 100)  # and never below this

    candidates: list[tuple[float, str]] = []
    buf = 0.995  # a hair under the level: stops sit below support, not on it
    if vwap and vwap > 0:
        candidates.append((vwap * buf, "VWAP"))
    if opening_range_low and opening_range_low > 0:
        candidates.append((opening_range_low * buf, "mínimo opening range"))
    if setup == "gap_and_go" and premarket_high and premarket_high > 0:
        candidates.append((premarket_high * buf, "máximo premarket"))
    if day_low and day_low > 0:
        candidates.append((day_low * buf, "mínimo del día"))

    valid = [(lvl, why) for lvl, why in candidates if cap_px <= lvl <= floor_px]
    if valid:
        stop, basis = max(valid, key=lambda c: c[0])
    elif atr and atr > 0:
        stop, basis = price - atr, "1 ATR diario"
        if stop > floor_px:
            stop, basis = floor_px, f"stop mínimo {min_stop_pct:.0f}%"
    else:
        stop, basis = floor_px, f"stop mínimo {min_stop_pct:.0f}%"
    if stop < cap_px:
        stop, basis = cap_px, f"stop máximo {max_stop_pct:.0f}%"

    risk = price - stop
    if risk <= 0:
        return None
    targets = [price + risk * r for r in (1.0, 2.0, 3.0)]
    reward = targets[1] - price
    res = resistance if resistance and resistance > price else None
    if res is not None and res < targets[1]:
        reward = res - price  # supply overhead caps the realistic reward
    return TradePlan(
        entry=price,
        stop=stop,
        stop_basis=basis,
        risk_per_share=risk,
        risk_pct=risk / price * 100,
        targets=targets,
        reward_risk=reward / risk,
        resistance=res,
        breakeven_after=targets[0],
    )


def grade_signal(
    plan: TradePlan,
    score: int,
    matched_setups: int,
    has_catalyst: bool,
    trend_aligned: bool,
    min_rr: float = 2.0,
) -> TradePlan:
    """Assign an A/B/C confluence grade (mutates and returns the plan)."""
    pts = 0
    why: list[str] = []
    if score >= 80:
        pts += 2
        why.append(f"score {score}")
    elif score >= 70:
        pts += 1
    if matched_setups >= 2:
        pts += 1
        why.append(f"{matched_setups} setups coinciden")
    if has_catalyst:
        pts += 1
        why.append("catalizador")
    if trend_aligned:
        pts += 1
        why.append("tendencia alineada")
    if plan.reward_risk >= min_rr:
        pts += 1
        why.append(f"R:R {plan.reward_risk:.1f}")
    else:
        why.append(f"R:R {plan.reward_risk:.1f} < {min_rr:.1f}")
    plan.grade = "A" if pts >= 5 else ("B" if pts >= 3 else "C")
    plan.grade_reasons = why
    return plan
