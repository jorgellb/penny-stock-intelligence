"""
Dilution risk engine.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.config import get_settings
from app.domain.models import (
    DataProvider,
    Filing,
    FilingAnalysis,
    FilingType,
    OfferingType,
    RiskFlag,
    RiskFlagType,
    RiskSeverity,
    ShareStatistics,
)


@dataclass
class OfferingInfo:
    """Parsed offering information."""

    filing_type: str
    filing_date: datetime
    offering_type: OfferingType
    shares: int | None = None
    price: float | None = None
    gross_proceeds: float | None = None
    net_proceeds: float | None = None
    warrants: int | None = None
    exercise_price: float | None = None
    potential_dilution_pct: float | None = None
    confidence: str = "low"
    source_url: str | None = None


@dataclass
class DilutionResult:
    """Result of dilution analysis."""

    symbol: str
    has_offering: bool = False
    offering_type: OfferingType | None = None
    shares_issued: int | None = None
    dilution_pct: float | None = None
    warrants_overhang: float | None = None
    atm_active: bool = False
    shelf_registration: bool = False
    convertible_debt: bool = False
    confidence: str = "low"
    source_filing: str | None = None
    filing_date: datetime | None = None
    detected_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class DilutionEngine:
    """Analyzes dilution risks from filings and corporate actions."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.risk_config = self.settings.risk
        self._penalties = self.settings.scoring.penalties

    async def analyze_filing(
        self,
        filing: Filing,
        filing_analysis: FilingAnalysis | None = None,
        share_stats: ShareStatistics | None = None,
    ) -> DilutionResult:
        """Analyze a filing for dilution information."""
        symbol = filing.symbol
        result = DilutionResult(symbol=symbol)

        if filing_analysis:
            result.offering_type = filing_analysis.offering_type
            result.shares_issued = filing_analysis.shares_offered
            result.confidence = filing_analysis.confidence.lower()
            result.source_filing = filing.accession_number
            result.filing_date = filing.filing_date

            if filing_analysis.potential_dilution_pct is not None:
                result.dilution_pct = filing_analysis.potential_dilution_pct
            elif (
                filing_analysis.shares_offered
                and share_stats
                and share_stats.shares_outstanding
                and share_stats.shares_outstanding > 0
            ):
                result.dilution_pct = (
                    filing_analysis.shares_offered / share_stats.shares_outstanding * 100
                )
            if filing_analysis.warrants:
                result.warrants_overhang = filing_analysis.warrants
            if filing_analysis.offering_type == OfferingType.ATM:
                result.atm_active = True

        # Check filing type
        if filing.filing_type.value in (
            "S-1",
            "S-3",
            "F-1",
            "F-3",
            "424B",
            "424B1",
            "424B2",
            "424B3",
            "424B4",
            "424B5",
            "424B7",
            "424B8",
        ):
            result.has_offering = True
            if result.offering_type is None:
                result.offering_type = self._classify_offering(filing.filing_type)
        if filing.filing_type.value == "8-K":
            result.has_offering = self._check_8k_for_offering(filing)

        return result

    def _classify_offering(self, filing_type: FilingType) -> OfferingType:
        """Classify offering type from filing type."""
        type_map = {
            "S-1": OfferingType.PUBLIC_OFFERING,
            "S-3": OfferingType.PUBLIC_OFFERING,
            "424B": OfferingType.PUBLIC_OFFERING,
            "424B1": OfferingType.REGISTERED_DIRECT,
            "424B2": OfferingType.PRIVATE_PLACEMENT,
            "424B3": OfferingType.PUBLIC_OFFERING,
            "424B4": OfferingType.PUBLIC_OFFERING,
            "424B5": OfferingType.PUBLIC_OFFERING,
            "424B7": OfferingType.PRIVATE_PLACEMENT,
            "424B8": OfferingType.PRIVATE_PLACEMENT,
        }
        return type_map.get(filing_type.value, OfferingType.UNKNOWN)

    def _check_8k_for_offering(self, filing: Filing) -> bool:
        """Check if 8-K contains offering information."""
        if filing.items:
            return any("8.01" in item or "7.01" in item or "1.01" in item for item in filing.items)
        return False

    def analyze_share_changes(
        self,
        current_shares: int,
        shares_history: list[tuple],  # [(date, shares)]
    ) -> dict[str, Any]:
        """Analyze share outstanding changes over time."""
        result: dict[str, Any] = {
            "current_shares": current_shares,
            "changes": {},
        }

        if not shares_history:
            return result

        for days_label, days in [("30d", 30), ("90d", 90), ("180d", 180), ("1y", 365)]:
            older_date = datetime.now(UTC) - __import__("datetime").timedelta(days=days)
            older_shares = None
            for date, shares in sorted(shares_history, reverse=True):
                if date <= older_date:
                    older_shares = shares
                    break
            if older_shares and older_shares > 0:
                change_pct = ((current_shares - older_shares) / older_shares) * 100
                result["changes"][f"shares_outstanding_change_{days_label}"] = round(change_pct, 2)

        return result

    def detect_risk_flags(
        self,
        dilution_result: DilutionResult,
        share_stats: ShareStatistics | None = None,
        float_shares: int | None = None,
    ) -> list[RiskFlag]:
        """Generate risk flags based on dilution analysis."""
        flags: list[RiskFlag] = []
        now = datetime.now(UTC)

        if dilution_result.has_offering and dilution_result.confidence in ("high", "medium"):
            flags.append(
                RiskFlag(
                    symbol=dilution_result.symbol,
                    flag_type=RiskFlagType.RECENT_OFFERING,
                    severity=RiskSeverity.HIGH,
                    detected_at=now,
                    source=DataProvider.SEC_EDGAR,
                    explanation=f"Recent offering detected: {dilution_result.offering_type}",
                    score_penalty=self._penalties.recent_offering,
                )
            )

        if dilution_result.atm_active:
            flags.append(
                RiskFlag(
                    symbol=dilution_result.symbol,
                    flag_type=RiskFlagType.ACTIVE_ATM,
                    severity=RiskSeverity.HIGH,
                    detected_at=now,
                    source=DataProvider.SEC_EDGAR,
                    explanation="Active ATM program detected",
                    score_penalty=self._penalties.active_atm,
                )
            )

        if dilution_result.shelf_registration:
            flags.append(
                RiskFlag(
                    symbol=dilution_result.symbol,
                    flag_type=RiskFlagType.SHELF_REGISTRATION,
                    severity=RiskSeverity.MEDIUM,
                    detected_at=now,
                    source=DataProvider.SEC_EDGAR,
                    explanation="Shelf registration detected",
                    score_penalty=self._penalties.shelf_registration,
                )
            )

        if dilution_result.warrants_overhang and dilution_result.warrants_overhang > 0:
            dilution_pct = dilution_result.warrants_overhang
            flags.append(
                RiskFlag(
                    symbol=dilution_result.symbol,
                    flag_type=RiskFlagType.WARRANT_OVERHANG,
                    severity=RiskSeverity.MEDIUM,
                    detected_at=now,
                    source=DataProvider.SEC_EDGAR,
                    explanation=f"Warrant overhang: {dilution_pct:.2f}%",
                    score_penalty=self._penalties.warrant_overhang,
                )
            )

        if (
            dilution_result.dilution_pct
            and dilution_result.dilution_pct > self.risk_config.dilution_threshold_pct
        ):
            flags.append(
                RiskFlag(
                    symbol=dilution_result.symbol,
                    flag_type=RiskFlagType.SHARE_DILUTION,
                    severity=RiskSeverity.HIGH,
                    detected_at=now,
                    source=DataProvider.SEC_EDGAR,
                    explanation=f"Dilution of {dilution_result.dilution_pct:.2f}%",
                    score_penalty=self._penalties.dilution,
                )
            )

        if float_shares and float_shares > 0:
            if float_shares < self.risk_config.micro_float_max:
                flags.append(
                    RiskFlag(
                        symbol=dilution_result.symbol,
                        flag_type=RiskFlagType.MICRO_FLOAT,
                        severity=RiskSeverity.CRITICAL,
                        detected_at=now,
                        source=DataProvider.SEC_EDGAR,
                        explanation=f"Micro float: {float_shares:,} shares",
                        score_penalty=20,
                    )
                )
            elif float_shares < self.risk_config.low_float_max:
                flags.append(
                    RiskFlag(
                        symbol=dilution_result.symbol,
                        flag_type=RiskFlagType.LOW_FLOAT,
                        severity=RiskSeverity.HIGH,
                        detected_at=now,
                        source=DataProvider.SEC_EDGAR,
                        explanation=f"Low float: {float_shares:,} shares",
                        score_penalty=10,
                    )
                )

        return flags

    async def detect_reverse_split(
        self,
        filings: list[Filing],
        corporate_actions: list,
    ) -> dict[str, Any]:
        """Detect reverse splits from filings and corporate actions."""
        result: dict[str, Any] = {
            "reverse_split_recent": False,
            "days_since_reverse_split": None,
            "reverse_split_ratio": None,
        }

        for action in corporate_actions:
            if "reverse" in action.action_type.lower():
                result["reverse_split_recent"] = True
                result["reverse_split_ratio"] = action.ratio
                if action.effective_date:
                    days_since = (datetime.now(UTC) - action.effective_date).days
                    result["days_since_reverse_split"] = days_since

        for filing in filings:
            if filing.filing_type.value == "8-K":
                if any("reverse" in str(item).lower() for item in (filing.items or [])):
                    result["reverse_split_recent"] = True

        return result
