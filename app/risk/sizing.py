"""Dynamic position sizing for penny stocks (fractional-risk, never fixed).

`risk_per_trade_pct` of equity divided by 1.5x ATR, capped by 5m-volume
impact, float participation and dollar caps per score band. Kelly is
deliberately NOT an allocator here (fat tails); Kelly <= 0.25x is only
a theoretical ceiling, documented, not implemented as sizing.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SizingInput:
    equity: float
    score: int
    atr: float
    price: float
    avg_vol_5m: float | None = None
    float_shares: float | None = None


@dataclass
class SizingResult:
    shares: int
    dollars: float
    risk_dollars: float
    capped_by: list[str] = field(default_factory=list)


class PositionSizer:
    def __init__(
        self,
        risk_per_trade_pct: float = 0.005,
        high_score_bonus_pct: float = 0.01,
        high_score_threshold: int = 85,
        atr_multiple: float = 1.5,
        max_volume_participation: float = 0.05,
        max_float_participation: float = 0.10,
    ) -> None:
        self.risk_per_trade_pct = risk_per_trade_pct
        self.high_score_bonus_pct = high_score_bonus_pct
        self.high_score_threshold = high_score_threshold
        self.atr_multiple = atr_multiple
        self.max_volume_participation = max_volume_participation
        self.max_float_participation = max_float_participation

    @staticmethod
    def dollar_cap(score: int) -> float:
        if score >= 90:
            return 10_000.0
        if score >= 80:
            return 5_000.0
        return 2_000.0

    def compute(self, inp: SizingInput) -> SizingResult:
        capped: list[str] = []
        if inp.equity <= 0 or inp.atr <= 0 or inp.price <= 0:
            return SizingResult(
                shares=0, dollars=0.0, risk_dollars=0.0, capped_by=["invalid_input"]
            )
        pct = (
            self.high_score_bonus_pct
            if inp.score >= self.high_score_threshold
            else self.risk_per_trade_pct
        )
        risk_dollars = inp.equity * pct
        stop_distance = self.atr_multiple * inp.atr
        shares = int(risk_dollars / stop_distance)
        if inp.avg_vol_5m and inp.avg_vol_5m > 0:
            max_shares = int(inp.avg_vol_5m * self.max_volume_participation)
            if shares > max_shares:
                shares = max_shares
                capped.append("volume_impact_5pct")
        if inp.float_shares and inp.float_shares > 0:
            max_shares = int(inp.float_shares * self.max_float_participation)
            if shares > max_shares:
                shares = max_shares
                capped.append("float_10pct")
        dollars = shares * inp.price
        cap = self.dollar_cap(inp.score)
        if dollars > cap:
            shares = int(cap / inp.price)
            dollars = shares * inp.price
            capped.append(f"dollar_cap_{int(cap)}")
        return SizingResult(
            shares=max(shares, 0),
            dollars=round(dollars, 2),
            risk_dollars=round(risk_dollars, 2),
            capped_by=capped,
        )
