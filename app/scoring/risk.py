"""
Risk engine: detects and manages risk flags.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.config import get_settings
from app.domain.models import (
    DataProvider,
    Fundamentals,
    Quote,
    RiskFlag,
    RiskFlagType,
    RiskSeverity,
    ShareStatistics,
)


@dataclass
class RiskAssessment:
    """Complete risk assessment for a security."""

    symbol: str
    flags: list[RiskFlag]
    overall_severity: RiskSeverity
    data_completeness: float
    data_freshness_seconds: int
    stale_data: bool
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def total_penalty(self) -> int:
        return sum(flag.score_penalty for flag in self.flags)


class RiskEngine:
    """Risk detection and management engine."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.risk_config = self.settings.risk
        self._penalties = self.settings.scoring.penalties

    def assess(
        self,
        symbol: str,
        quote: Quote | None = None,
        fundamentals: Fundamentals | None = None,
        share_stats: ShareStatistics | None = None,
        float_shares: int | None = None,
        data_age_seconds: int = 0,
    ) -> RiskAssessment:
        """Complete risk assessment."""
        flags: list[RiskFlag] = []
        now = datetime.now(UTC)

        # Liquidity risk
        if quote and quote.spread_pct is not None:
            if quote.spread_pct > self.settings.liquidity.max_spread_pct:
                severity = RiskSeverity.CRITICAL if quote.spread_pct > 10 else RiskSeverity.HIGH
                flags.append(
                    RiskFlag(
                        symbol=symbol,
                        flag_type=RiskFlagType.WIDE_SPREAD,
                        severity=severity,
                        detected_at=now,
                        source=DataProvider.YFINANCE,
                        explanation=f"Spread of {quote.spread_pct:.2f}% exceeds threshold",
                        score_penalty=self._penalties.wide_spread,
                    )
                )

            if quote.ask and quote.bid:
                if quote.bid_size and quote.bid_size < 1000:
                    severity = RiskSeverity.CRITICAL if quote.bid_size < 100 else RiskSeverity.HIGH
                    flags.append(
                        RiskFlag(
                            symbol=symbol,
                            flag_type=RiskFlagType.VERY_LOW_LIQUIDITY
                            if quote.bid_size < 100
                            else RiskFlagType.LOW_LIQUIDITY,
                            severity=severity,
                            detected_at=now,
                            source=DataProvider.YFINANCE,
                            explanation=f"Very low bid size: {quote.bid_size}",
                            score_penalty=self._penalties.low_liquidity,
                        )
                    )

        # Volatility risk
        if quote and quote.last and fundamentals:
            if fundamentals.data_quality_score and fundamentals.data_quality_score < 0.3:
                flags.append(
                    RiskFlag(
                        symbol=symbol,
                        flag_type=RiskFlagType.INSUFFICIENT_DATA,
                        severity=RiskSeverity.MEDIUM,
                        detected_at=now,
                        source=DataProvider.YFINANCE,
                        explanation="Insufficient fundamental data",
                        score_penalty=self._penalties.insufficient_data,
                    )
                )

        # Cash runway risk
        if fundamentals and fundamentals.total_cash and fundamentals.operating_cash_flow:
            if fundamentals.operating_cash_flow < 0:
                runway = fundamentals.cash_runway_months
                if runway is not None and runway < 6:
                    flags.append(
                        RiskFlag(
                            symbol=symbol,
                            flag_type=RiskFlagType.LOW_CASH_RUNWAY,
                            severity=RiskSeverity.HIGH,
                            detected_at=now,
                            source=DataProvider.YFINANCE,
                            explanation=f"Estimated cash runway: ~{runway:.1f} months",
                            score_penalty=self._penalties.low_cash_runway,
                        )
                    )
                if runway is not None and runway < 3:
                    for flag in flags:
                        if flag.flag_type == RiskFlagType.LOW_CASH_RUNWAY:
                            flag.severity = RiskSeverity.CRITICAL
                            flag.score_penalty = self._penalties.low_cash_runway

        # Going concern
        if fundamentals and fundamentals.working_capital is not None:
            if fundamentals.working_capital < 0:
                flags.append(
                    RiskFlag(
                        symbol=symbol,
                        flag_type=RiskFlagType.NEGATIVE_WORKING_CAPITAL,
                        severity=RiskSeverity.HIGH,
                        detected_at=now,
                        source=DataProvider.YFINANCE,
                        explanation="Negative working capital",
                        score_penalty=self._penalties.negative_working_capital,
                    )
                )

        # Float risk (micro/low float = squeeze & liquidity risk)
        float_val = float_shares
        if float_val is None and share_stats is not None and share_stats.float_shares:
            float_val = int(share_stats.float_shares)
        if float_val is not None:
            micro = self.settings.float.micro_float_max
            low = self.settings.float.low_float_max
            if float_val <= micro:
                flags.append(
                    RiskFlag(
                        symbol=symbol,
                        flag_type=RiskFlagType.MICRO_FLOAT,
                        severity=RiskSeverity.MEDIUM,
                        detected_at=now,
                        source=DataProvider.YFINANCE,
                        explanation=f"Micro float {float_val:,} ≤ {micro:,}",
                        score_penalty=self._penalties.micro_float,
                    )
                )
            elif float_val <= low:
                flags.append(
                    RiskFlag(
                        symbol=symbol,
                        flag_type=RiskFlagType.LOW_FLOAT,
                        severity=RiskSeverity.LOW,
                        detected_at=now,
                        source=DataProvider.YFINANCE,
                        explanation=f"Low float {float_val:,} ≤ {low:,}",
                        score_penalty=self._penalties.low_float,
                    )
                )

        # Data freshness
        if data_age_seconds > 3600:
            flags.append(
                RiskFlag(
                    symbol=symbol,
                    flag_type=RiskFlagType.INSUFFICIENT_DATA,
                    severity=RiskSeverity.LOW,
                    detected_at=now,
                    source=DataProvider.YFINANCE,
                    explanation=f"Data is {data_age_seconds}s old",
                    score_penalty=self._penalties.insufficient_data,
                )
            )

        # Stale data flag
        stale_data = data_age_seconds > 7200 or (quote is None and fundamentals is None)

        # Determine overall severity
        if any(f.severity == RiskSeverity.CRITICAL for f in flags):
            overall_severity = RiskSeverity.CRITICAL
        elif any(f.severity == RiskSeverity.HIGH for f in flags):
            overall_severity = RiskSeverity.HIGH
        elif len(flags) > 0:
            overall_severity = RiskSeverity.MEDIUM
        else:
            overall_severity = RiskSeverity.LOW

        # Data completeness
        data_completeness = self._compute_data_completeness(
            fundamentals, share_stats, quote, float_shares
        )

        return RiskAssessment(
            symbol=symbol,
            flags=flags,
            overall_severity=overall_severity,
            data_completeness=data_completeness,
            data_freshness_seconds=data_age_seconds,
            stale_data=stale_data,
        )

    def _compute_data_completeness(
        self,
        fundamentals: Fundamentals | None,
        share_stats: ShareStatistics | None,
        quote: Quote | None,
        float_shares: int | None,
    ) -> float:
        """Compute data completeness score (0-1)."""
        score = 0.0

        if quote is not None:
            score += 0.25
        if fundamentals is not None:
            score += 0.25
        if share_stats is not None:
            score += 0.25
        if float_shares is not None:
            score += 0.25

        return score

    def generate_risk_summary(self, assessment: RiskAssessment) -> str:
        """Generate human-readable risk summary."""
        lines = [f"Risk Assessment: {assessment.symbol}"]
        lines.append(f"Overall Severity: {assessment.overall_severity.value.upper()}")
        lines.append(f"Data Completeness: {assessment.data_completeness:.0%}")
        lines.append(f"Data Freshness: {assessment.data_freshness_seconds}s ago")

        if assessment.flags:
            lines.append("\nRisk Flags:")
            for flag in assessment.flags:
                lines.append(
                    f"  ⚠ [{flag.flag_type.value}] ({flag.severity.value}): {flag.explanation}"
                )
        else:
            lines.append("\nNo risk flags detected.")

        return "\n".join(lines)
