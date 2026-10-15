"""
Scoring engine: deterministic, explainable scoring system.
"""

from datetime import UTC, datetime, timezone
from typing import Any, Dict, List, Optional

from app.config import get_settings
from app.domain.models import Fundamentals, RiskFlag, Score, ScoreBreakdown
from app.scoring.components import volume_component


def map_catalyst_strength(impact: str | None) -> str | None:
    """Map catalyst impact labels (high/medium/low) to scoring buckets."""
    if not impact:
        return None
    return {
        "high": "strong",
        "medium": "moderate",
        "low": "weak",
        "strong": "strong",
        "moderate": "moderate",
        "weak": "weak",
        "none": "none",
    }.get(impact.strip().lower())


def fundamentals_health_score(fundamentals: Fundamentals | None) -> float | None:
    """0-100 health score from available fundamental fields. None if no data."""
    if fundamentals is None:
        return None

    parts: list[float] = []

    runway = fundamentals.cash_runway_months
    if runway is not None:
        if runway >= 18:
            parts.append(100.0)
        elif runway >= 12:
            parts.append(80.0)
        elif runway >= 6:
            parts.append(50.0)
        else:
            parts.append(20.0)

    if fundamentals.working_capital is not None:
        parts.append(80.0 if fundamentals.working_capital > 0 else 20.0)

    if fundamentals.revenue_yoy_growth is not None:
        g = fundamentals.revenue_yoy_growth
        if g >= 0.5:
            parts.append(90.0)
        elif g >= 0.1:
            parts.append(70.0)
        elif g >= 0:
            parts.append(55.0)
        else:
            parts.append(30.0)

    if fundamentals.data_quality_score is not None:
        parts.append(max(0.0, min(100.0, fundamentals.data_quality_score * 100.0)))

    if not parts:
        # Object present but empty — weak positive so DQ/fund weights aren't zeroed.
        return 40.0
    return sum(parts) / len(parts)


def data_quality_from_completeness(
    completeness: float,
    *,
    feed_lag_stale: bool = False,
) -> float:
    """Map risk-engine completeness (0-1) to a 0-100 data-quality score."""
    base = max(0.0, min(1.0, completeness)) * 100.0
    if feed_lag_stale:
        return max(15.0, base * 0.7)
    # Floor so quote-only evaluations still contribute a small DQ component.
    return max(25.0, base) if completeness > 0 else 20.0


class ScoringEngine:
    """Deterministic, auditable scoring engine."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.weights = self.settings.scoring.weights
        self.penalties = self.settings.scoring.penalties

    def compute_raw_score(
        self,
        rvol: float | None = None,
        catalyst_strength: str | None = None,
        momentum_score: float | None = None,
        technical_score: float | None = None,
        liquidity_score: float | None = None,
        fundamentals_score: float | None = None,
        data_quality_score: float | None = None,
        volume_score: float | None = None,
        renormalize_unknown_catalyst: bool = False,
    ) -> ScoreBreakdown:
        """Compute the raw score components.

        Sub-scores are 0-100 and scaled by their weight (rounded, not
        truncated). `volume_score` overrides the RVOL mapping when the
        caller has richer context (float rotation). With
        `renormalize_unknown_catalyst`, an *unknown* catalyst (no news
        provider / not checked) does not cap the score at 80: the other
        components are rescaled to the full 100. A checked-and-absent
        catalyst ("none") still scores 0.
        """
        breakdown = ScoreBreakdown()

        def scaled(sub: float | None, weight: int) -> int:
            if sub is None:
                return 0
            return int(min(max(round(sub * weight / 100), 0), weight))

        breakdown.momentum = scaled(momentum_score, self.weights.momentum)

        if volume_score is None and rvol is not None:
            volume_score = volume_component(rvol)
        breakdown.volume = scaled(volume_score, self.weights.volume)

        if catalyst_strength is not None:
            catalyst_map = {"weak": 25.0, "moderate": 55.0, "strong": 100.0, "none": 0.0}
            breakdown.catalyst = scaled(
                catalyst_map.get(catalyst_strength, 0.0), self.weights.catalyst
            )

        breakdown.technical = scaled(technical_score, self.weights.technical)
        breakdown.liquidity = scaled(liquidity_score, self.weights.liquidity)
        breakdown.fundamentals = scaled(fundamentals_score, self.weights.fundamentals)
        breakdown.data_quality = scaled(data_quality_score, self.weights.data_quality)

        raw = sum(
            [
                breakdown.momentum,
                breakdown.volume,
                breakdown.catalyst,
                breakdown.technical,
                breakdown.liquidity,
                breakdown.fundamentals,
                breakdown.data_quality,
            ]
        )
        if catalyst_strength is None and renormalize_unknown_catalyst:
            available = 100 - self.weights.catalyst
            if available > 0:
                raw = int(round(raw * 100 / available))
        breakdown.raw_score = min(raw, 100)

        return breakdown

    def compute_risk_penalties(
        self,
        risk_flags: list[RiskFlag],
    ) -> dict[str, int]:
        """Compute risk penalties based on active flags."""
        penalties: dict[str, int] = {}

        flag_penalty_map = {
            "RECENT_OFFERING": self.penalties.recent_offering,
            "ACTIVE_ATM": self.penalties.active_atm,
            "RECENT_REVERSE_SPLIT": self.penalties.reverse_split,
            "LOW_LIQUIDITY": self.penalties.low_liquidity,
            "VERY_LOW_LIQUIDITY": self.penalties.low_liquidity,
            "WIDE_SPREAD": self.penalties.wide_spread,
            "SHARE_DILUTION": self.penalties.dilution,
            "SHELF_REGISTRATION": self.penalties.shelf_registration,
            "WARRANT_OVERHANG": self.penalties.warrant_overhang,
            "CONVERTIBLE_DEBT": self.penalties.convertible_debt,
            "GOING_CONCERN": self.penalties.going_concern,
            "DELISTING_WARNING": self.penalties.delisting_warning,
            "NEGATIVE_WORKING_CAPITAL": self.penalties.negative_working_capital,
            "LOW_CASH_RUNWAY": self.penalties.low_cash_runway,
            "TRADING_HALT": self.penalties.trading_halt,
            "NO_RECENT_FILINGS": self.penalties.no_recent_filings,
            "INSUFFICIENT_DATA": self.penalties.insufficient_data,
            "NEWS_UNVERIFIED": self.penalties.news_unverified,
            "LOW_FLOAT": self.penalties.low_float,
            "MICRO_FLOAT": self.penalties.micro_float,
        }

        for flag in risk_flags:
            penalty = flag_penalty_map.get(flag.flag_type.value, 0)
            if penalty > 0:
                penalties[flag.flag_type.value] = penalty

        return penalties

    def compute_final_score(
        self,
        breakdown: ScoreBreakdown,
        risk_flags: list[RiskFlag],
    ) -> Score:
        """Compute the final score with risk penalties."""
        penalties = self.compute_risk_penalties(risk_flags)
        total_penalty = sum(penalties.values())
        final_score = max(0, breakdown.raw_score - total_penalty)

        # Determine data quality
        if breakdown.data_quality >= 4:
            data_quality = "high"
        elif breakdown.data_quality >= 2:
            data_quality = "medium"
        elif breakdown.data_quality > 0:
            data_quality = "low"
        else:
            data_quality = "unknown"

        missing_data = []
        if breakdown.data_quality < 2:
            missing_data.append("insufficient data")

        return Score(
            symbol="",
            timestamp=datetime.now(UTC),
            breakdown=breakdown,
            raw_score=breakdown.raw_score,
            risk_penalty=total_penalty,
            final_score=final_score,
            penalties=penalties,
            components=breakdown.model_dump(),
            features={},
            data_quality=data_quality,
            missing_data=missing_data,
            config_version="1.0",
            config_hash="placeholder",
        )

    def score_security(
        self,
        rvol: float | None = None,
        catalyst_strength: str | None = None,
        momentum_score: float | None = None,
        technical_score: float | None = None,
        liquidity_score: float | None = None,
        fundamentals_score: float | None = None,
        data_quality_score: float | None = None,
        risk_flags: list[RiskFlag] | None = None,
        volume_score: float | None = None,
        renormalize_unknown_catalyst: bool = False,
    ) -> Score:
        """Full scoring pipeline."""
        breakdown = self.compute_raw_score(
            rvol=rvol,
            catalyst_strength=catalyst_strength,
            momentum_score=momentum_score,
            technical_score=technical_score,
            liquidity_score=liquidity_score,
            fundamentals_score=fundamentals_score,
            data_quality_score=data_quality_score,
            volume_score=volume_score,
            renormalize_unknown_catalyst=renormalize_unknown_catalyst,
        )
        flags = risk_flags or []
        return self.compute_final_score(breakdown, flags)

    def generate_score_explanation(self, score: Score) -> str:
        """Generate human-readable score explanation."""
        lines = []
        lines.append(f"Base score: +{score.raw_score}")
        if score.breakdown.momentum > 0:
            lines.append(f"+{score.breakdown.momentum} momentum")
        if score.breakdown.volume > 0:
            lines.append(f"+{score.breakdown.volume} volume")
        if score.breakdown.catalyst > 0:
            lines.append(f"+{score.breakdown.catalyst} catalyst")
        if score.breakdown.technical > 0:
            lines.append(f"+{score.breakdown.technical} technical")
        if score.breakdown.liquidity > 0:
            lines.append(f"+{score.breakdown.liquidity} liquidity")
        if score.breakdown.fundamentals > 0:
            lines.append(f"+{score.breakdown.fundamentals} fundamentals")
        if score.breakdown.data_quality > 0:
            lines.append(f"+{score.breakdown.data_quality} data quality")

        if score.risk_penalty > 0:
            lines.append(f"\nRisk penalties: -{score.risk_penalty}")
            for flag, penalty in score.penalties.items():
                if penalty > 0:
                    lines.append(f"  -{penalty} {flag}")

        lines.append(f"\nFINAL = {score.final_score}/100")
        lines.append("\nThis score is a ranking metric, not a probability forecast.")
        return "\n".join(lines)
