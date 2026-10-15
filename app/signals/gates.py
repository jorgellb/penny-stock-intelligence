"""Strategy gates for NASDAQ/NYSE penny stocks.

- ShortSqueezeGate: blocks mean-reversion shorts into parabolic squeezes.
  This project has no short side (BUY/SELL/HOLD on longs only), so the
  gate acts as an annotation + exit discipline: during an active squeeze,
  overbought exits are vetoed and only momentum-long entries are allowed.
- donchian_entry_gate: Donchian(20d) breakout validated by RVOL >= 3-4x,
  high-impact AI-validated catalyst, spread/dollar-volume liquidity, and
  no dilution freeze / recent halt.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class SqueezeAssessment:
    active: bool = False
    parabolic_days: int = 0
    reasons: list[str] = field(default_factory=list)


def detect_squeeze(
    closes: np.ndarray,
    volumes: np.ndarray,
    min_parabolic_days: int = 3,
    min_day_gain_pct: float = 10.0,
) -> SqueezeAssessment:
    """Heuristic squeeze detector: N+ consecutive strong up days on rising volume."""
    n = len(closes)
    if n < min_parabolic_days + 1 or len(volumes) != n:
        return SqueezeAssessment()
    days = 0
    for i in range(n - 1, min_parabolic_days - 1 - 1, -1):
        if closes[i - 1] <= 0:
            break
        gain = (closes[i] - closes[i - 1]) / closes[i - 1] * 100
        vol_up = volumes[i] >= volumes[i - 1]
        if gain >= min_day_gain_pct and vol_up:
            days += 1
        else:
            break
    if days >= min_parabolic_days:
        return SqueezeAssessment(
            active=True,
            parabolic_days=days,
            reasons=[f"squeeze activo: {days} días parabólicos con volumen creciente"],
        )
    return SqueezeAssessment(parabolic_days=days)


@dataclass
class ShortGateDecision:
    allow_contrarian_short: bool = False
    allow_momentum_long: bool = True
    reasons: list[str] = field(default_factory=list)


class ShortSqueezeGate:
    """Hard gate for the short side (Connors/Simons mean-reversion).

    Args:
        max_short_interest_pct: shorts above this float % veto contrarian shorts.
        max_borrow_rate_pct: borrow rates above this veto contrarian shorts.
    """

    def __init__(
        self, max_short_interest_pct: float = 20.0, max_borrow_rate_pct: float = 10.0
    ) -> None:
        self.max_short_interest_pct = max_short_interest_pct
        self.max_borrow_rate_pct = max_borrow_rate_pct

    def evaluate(
        self,
        short_interest_pct: float | None,
        borrow_rate_pct: float | None,
        squeeze: SqueezeAssessment | None = None,
        downtrend_confirmed: bool = False,
    ) -> ShortGateDecision:
        out = ShortGateDecision()
        if squeeze is not None and squeeze.active:
            out.allow_contrarian_short = False
            out.reasons.append(
                "squeeze activo: prohibido apostar contra la parabólica; solo momentum-long"
            )
            return out
        if short_interest_pct is not None and short_interest_pct >= self.max_short_interest_pct:
            if not downtrend_confirmed:
                out.allow_contrarian_short = False
                out.reasons.append(
                    f"short interest {short_interest_pct:.1f}% >= {self.max_short_interest_pct}% "
                    "sin tendencia bajista confirmada: short contrarian vetado"
                )
                return out
        if borrow_rate_pct is not None and borrow_rate_pct >= self.max_borrow_rate_pct:
            out.allow_contrarian_short = False
            out.reasons.append(
                f"borrow {borrow_rate_pct:.1f}% >= {self.max_borrow_rate_pct}%: "
                "sin locates baratos, short vetado"
            )
            return out
        out.allow_contrarian_short = True
        out.reasons.append("short contrarian permitido (filtros superados)")
        return out


@dataclass
class DonchianInput:
    close: float
    high_20d: float
    rvol_same_time: float
    catalyst_impact: str | None = None  # low|medium|high
    catalyst_confidence: float = 0.0
    catalyst_age_hours: float | None = None
    catalyst_primary_source: bool = False
    spread_pct: float | None = None
    dollar_volume: float = 0.0
    dilution_frozen: bool = False
    halted_recently: bool = False


def donchian_entry_gate(
    inp: DonchianInput,
    min_rvol: float = 3.0,
    min_catalyst_confidence: float = 0.8,
    max_catalyst_age_hours: float = 24.0,
    max_spread_pct: float = 2.0,
    min_dollar_volume: float = 2_000_000.0,
) -> tuple[bool, list[str]]:
    """Donchian(20d) breakout gate. Returns (pass, reasons)."""
    reasons: list[str] = []
    if inp.close <= inp.high_20d:
        return False, ["sin ruptura del máximo 20d"]
    reasons.append(f"ruptura Donchian 20d (${inp.high_20d:.2f})")
    if inp.rvol_same_time < min_rvol:
        return False, reasons + [
            f"RVOL {inp.rvol_same_time:.1f}x < {min_rvol}x: ruptura falsa probable"
        ]
    reasons.append(f"RVOL {inp.rvol_same_time:.1f}x >= {min_rvol}x")
    if (
        inp.catalyst_impact != "high"
        or inp.catalyst_confidence < min_catalyst_confidence
        or not inp.catalyst_primary_source
        or inp.catalyst_age_hours is None
        or inp.catalyst_age_hours > max_catalyst_age_hours
    ):
        return False, reasons + ["sin catalizador high validado por IA (<24h, fuente primaria)"]
    reasons.append("catalizador high validado por IA")
    if inp.spread_pct is not None and inp.spread_pct > max_spread_pct:
        return False, reasons + [f"spread {inp.spread_pct:.2f}% > {max_spread_pct}%: ilíquido"]
    if inp.dollar_volume < min_dollar_volume:
        return False, reasons + ["dollar volume insuficiente para ejecución"]
    if inp.dilution_frozen:
        return False, reasons + ["dilución inminente: entrada congelada"]
    if inp.halted_recently:
        return False, reasons + ["halt reciente: entrada congelada"]
    return True, reasons
