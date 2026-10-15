"""
Core domain models for the Penny Stock Intelligence Engine.
"""

from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, computed_field


class Exchange(str, Enum):
    """Supported exchanges."""

    NASDAQ = "NASDAQ"
    NYSE = "NYSE"
    AMEX = "AMEX"
    OTC = "OTC"
    OTCQB = "OTCQB"
    OTCQX = "OTCQX"
    PINK = "PINK"


class MarketSession(str, Enum):
    """Market session types."""

    PREMARKET = "premarket"
    REGULAR = "regular"
    AFTER_HOURS = "after_hours"
    CLOSED = "closed"


class DataProvider(str, Enum):
    """Data provider identifiers."""

    YFINANCE = "yfinance"
    ALPHA_VANTAGE = "alpha_vantage"
    FINNHUB = "finnhub"
    POLYGON = "polygon"
    TWELVE_DATA = "twelve_data"
    SEC_EDGAR = "sec_edgar"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"


class SignalType(str, Enum):
    """Signal types for alerts."""

    PREMARKET_GAPPER = "premarket_gapper"
    HIGH_RVOL = "high_rvol"
    BREAKOUT = "breakout"
    CATALYST = "catalyst"
    MOMENTUM = "momentum"
    REVERSAL = "reversal"
    NEWS_DRIVEN = "news_driven"
    LOW_FLOAT_SQUEEZE = "low_float_squeeze"


class RiskFlagType(str, Enum):
    """Risk flag types."""

    LOW_FLOAT = "LOW_FLOAT"
    MICRO_FLOAT = "MICRO_FLOAT"
    LOW_LIQUIDITY = "LOW_LIQUIDITY"
    VERY_LOW_LIQUIDITY = "VERY_LOW_LIQUIDITY"
    WIDE_SPREAD = "WIDE_SPREAD"
    EXTREME_VOLATILITY = "EXTREME_VOLATILITY"
    RECENT_OFFERING = "RECENT_OFFERING"
    ACTIVE_ATM = "ACTIVE_ATM"
    SHELF_REGISTRATION = "SHELF_REGISTRATION"
    WARRANT_OVERHANG = "WARRANT_OVERHANG"
    CONVERTIBLE_DEBT = "CONVERTIBLE_DEBT"
    SHARE_DILUTION = "SHARE_DILUTION"
    RECENT_REVERSE_SPLIT = "RECENT_REVERSE_SPLIT"
    DELISTING_WARNING = "DELISTING_WARNING"
    GOING_CONCERN = "GOING_CONCERN"
    NEGATIVE_WORKING_CAPITAL = "NEGATIVE_WORKING_CAPITAL"
    LOW_CASH_RUNWAY = "LOW_CASH_RUNWAY"
    TRADING_HALT = "TRADING_HALT"
    NO_RECENT_FILINGS = "NO_RECENT_FILINGS"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    NEWS_UNVERIFIED = "NEWS_UNVERIFIED"


class RiskSeverity(str, Enum):
    """Risk severity levels."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class CatalystCategory(str, Enum):
    """Catalyst categories."""

    EARNINGS = "earnings"
    GUIDANCE = "guidance"
    CONTRACT = "contract"
    PARTNERSHIP = "partnership"
    ACQUISITION = "acquisition"
    MERGER = "merger"
    FDA = "fda"
    CLINICAL_TRIAL = "clinical_trial"
    PATENT = "patent"
    REGULATORY = "regulatory"
    FINANCING = "financing"
    PUBLIC_OFFERING = "public_offering"
    ATM = "atm"
    PRIVATE_PLACEMENT = "private_placement"
    WARRANT = "warrant"
    DEBT = "debt"
    REVERSE_SPLIT = "reverse_split"
    DELISTING = "delisting"
    COMPLIANCE = "compliance"
    LAWSUIT = "lawsuit"
    MANAGEMENT_CHANGE = "management_change"
    ANALYST = "analyst"
    PRODUCT_LAUNCH = "product_launch"
    CUSTOMER_WIN = "customer_win"
    GOVERNMENT_CONTRACT = "government_contract"
    OTHER = "other"


class CatalystStrength(str, Enum):
    """Catalyst strength levels."""

    NONE = "none"
    WEAK = "weak"
    MODERATE = "moderate"
    STRONG = "strong"


class Sentiment(str, Enum):
    """Sentiment classification."""

    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"


class ImpactLevel(str, Enum):
    """Impact level classification."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TimeHorizon(str, Enum):
    """Time horizon for catalysts."""

    SHORT_TERM = "short_term"
    MEDIUM_TERM = "medium_term"
    LONG_TERM = "long_term"


class SourceReliability(str, Enum):
    """Source reliability levels."""

    CONFIRMED = "confirmed"
    REPORTED = "reported"
    RUMOR = "rumor"
    UNKNOWN = "unknown"


class FilingType(str, Enum):
    """SEC filing types."""

    S_1 = "S-1"
    S_3 = "S-3"
    S_4 = "S-4"
    F_1 = "F-1"
    F_3 = "F-3"
    F_4 = "F-4"
    FORM_8K = "8-K"
    FORM_10K = "10-K"
    FORM_10Q = "10-Q"
    FORM_424B = "424B"
    FORM_424B1 = "424B1"
    FORM_424B2 = "424B2"
    FORM_424B3 = "424B3"
    FORM_424B4 = "424B4"
    FORM_424B5 = "424B5"
    FORM_424B7 = "424B7"
    FORM_424B8 = "424B8"
    FORM_4 = "4"
    FORM_13D = "13D"
    FORM_13G = "13G"
    FORM_144 = "144"
    DEF_14A = "DEF 14A"
    OTHER = "other"


class OfferingType(str, Enum):
    """Offering types."""

    PUBLIC_OFFERING = "public_offering"
    REGISTERED_DIRECT = "registered_direct"
    PRIVATE_PLACEMENT = "private_placement"
    ATM = "atm"
    SHELF = "shelf"
    EQUITY_LINE = "equity_line"
    PIPE = "pipe"
    RIGHTS_OFFERING = "rights_offering"
    WARRANT_EXERCISE = "warrant_exercise"
    CONVERTIBLE_NOTE = "convertible_note"
    CONVERTIBLE_DEBT = "convertible_debt"
    UNKNOWN = "unknown"


class AlertProvider(str, Enum):
    """Alert provider types."""

    CONSOLE = "console"
    TELEGRAM = "telegram"
    DISCORD = "discord"
    EMAIL = "email"
    WEBHOOK = "webhook"


class BaseDomainModel(BaseModel):
    """Base model with common fields."""

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class TimestampedModel(BaseDomainModel):
    """Model with event timestamps for point-in-time tracking."""

    event_time: datetime
    published_at: datetime | None = None
    received_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    processed_at: datetime | None = None
    provider: DataProvider
    source_url: str | None = None


class Security(BaseDomainModel):
    """Security/Stock master data."""

    symbol: str
    name: str | None = None
    exchange: Exchange
    is_etf: bool = False
    is_preferred: bool = False
    is_warrant: bool = False
    is_spac_unit: bool = False
    is_fund: bool = False
    is_active: bool = True
    cik: str | None = None
    sic_code: str | None = None
    industry: str | None = None
    sector: str | None = None
    ipo_date: datetime | None = None


class Quote(BaseModel):
    """Real-time quote data."""

    symbol: str
    bid: Decimal | None = None
    ask: Decimal | None = None
    bid_size: int | None = None
    ask_size: int | None = None
    last: Decimal | None = None
    last_size: int | None = None
    timestamp: datetime
    provider: DataProvider

    @computed_field  # type: ignore[prop-decorator]
    @property
    def mid(self) -> Decimal | None:
        if self.bid is not None and self.ask is not None:
            return (self.bid + self.ask) / 2
        return None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def spread_absolute(self) -> Decimal | None:
        if self.bid is not None and self.ask is not None:
            return self.ask - self.bid
        return None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def spread_pct(self) -> float | None:
        if self.mid and self.spread_absolute and self.mid > 0:
            return float(self.spread_absolute / self.mid * 100)
        return None


class Bar(BaseModel):
    """OHLCV bar data."""

    symbol: str
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    vwap: Decimal | None = None
    trade_count: int | None = None
    provider: DataProvider
    timeframe: str = "1m"  # 1m, 5m, 15m, 1h, 1d


class DailyBar(BaseModel):
    """Daily OHLCV bar."""

    symbol: str
    date: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    vwap: Decimal | None = None
    adjusted_close: Decimal | None = None
    dividend: Decimal | None = None
    split_coefficient: Decimal | None = None
    provider: DataProvider


class Fundamentals(BaseModel):
    """Fundamental data for a security."""

    symbol: str
    period_end: datetime
    period_type: str  # "annual", "quarterly", "ttm"

    # Market data
    market_cap: Decimal | None = None
    enterprise_value: Decimal | None = None
    shares_outstanding: int | None = None
    float_shares: int | None = None
    insider_ownership_pct: float | None = None
    institutional_ownership_pct: float | None = None

    # Income statement
    revenue: Decimal | None = None
    gross_profit: Decimal | None = None
    operating_income: Decimal | None = None
    net_income: Decimal | None = None
    eps_diluted: Decimal | None = None
    eps_basic: Decimal | None = None

    # Balance sheet
    cash: Decimal | None = None
    cash_equivalents: Decimal | None = None
    short_term_investments: Decimal | None = None
    total_cash: Decimal | None = None
    total_debt: Decimal | None = None
    current_assets: Decimal | None = None
    current_liabilities: Decimal | None = None
    working_capital: Decimal | None = None
    total_assets: Decimal | None = None
    total_liabilities: Decimal | None = None
    shareholders_equity: Decimal | None = None

    # Cash flow
    operating_cash_flow: Decimal | None = None
    free_cash_flow: Decimal | None = None
    capital_expenditures: Decimal | None = None

    # Growth
    revenue_yoy_growth: float | None = None
    revenue_qoq_growth: float | None = None

    # Data quality
    data_quality_score: float | None = None
    provider: DataProvider
    source_url: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cash_runway_months(self) -> float | None:
        """Estimated cash runway in months."""
        if self.total_cash and self.operating_cash_flow and self.operating_cash_flow < 0:
            monthly_burn = abs(float(self.operating_cash_flow)) / 3
            if monthly_burn > 0:
                return float(self.total_cash) / monthly_burn
        return None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cash_runway_confidence(self) -> str | None:
        """Confidence level for cash runway estimate."""
        if self.cash_runway_months is not None:
            if self.data_quality_score and self.data_quality_score > 0.7:
                return "high"
            elif self.data_quality_score and self.data_quality_score > 0.4:
                return "medium"
            return "low"
        return None


class ShareStatistics(BaseModel):
    """Share statistics and dilution tracking."""

    symbol: str
    date: datetime
    shares_outstanding: int | None = None
    float_shares: int | None = None
    insider_shares: int | None = None
    institutional_shares: int | None = None
    short_interest: int | None = None
    short_ratio: float | None = None
    provider: DataProvider

    @computed_field  # type: ignore[prop-decorator]
    @property
    def insider_pct(self) -> float | None:
        if self.shares_outstanding and self.insider_shares and self.shares_outstanding > 0:
            return self.insider_shares / self.shares_outstanding * 100
        return None


class NewsArticle(BaseModel):
    """News article data."""

    id: UUID = Field(default_factory=uuid4)
    symbol: str
    headline: str
    summary: str | None = None
    body: str | None = None
    source: str
    url: str
    published_at: datetime
    received_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    provider: DataProvider
    symbols_mentioned: list[str] = Field(default_factory=list)
    content_hash: str | None = None


class NewsAnalysis(BaseModel):
    """AI-analyzed news data."""

    id: UUID = Field(default_factory=uuid4)
    article_id: UUID
    symbol: str
    category: CatalystCategory
    sentiment: Sentiment
    impact: ImpactLevel
    time_horizon: TimeHorizon
    is_material: bool
    is_primary_source: bool
    confidence: float = Field(ge=0.0, le=1.0)
    summary: str
    bullish_factors: list[str] = Field(default_factory=list)
    bearish_factors: list[str] = Field(default_factory=list)
    risk_factors: list[str] = Field(default_factory=list)
    provider: DataProvider
    model: str
    analyzed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Filing(BaseModel):
    """SEC filing data."""

    id: UUID = Field(default_factory=uuid4)
    symbol: str
    cik: str
    accession_number: str
    filing_type: FilingType
    filing_date: datetime
    report_date: datetime | None = None
    accepted_at: datetime
    url: str
    primary_document: str | None = None
    primary_doc_description: str | None = None
    items: list[str] = Field(default_factory=list)
    size_bytes: int | None = None
    provider: DataProvider = DataProvider.SEC_EDGAR


class FilingAnalysis(BaseModel):
    """AI-analyzed filing data."""

    id: UUID = Field(default_factory=uuid4)
    filing_id: UUID
    symbol: str
    offering_type: OfferingType | None = None
    shares_offered: int | None = None
    offering_price: Decimal | None = None
    gross_proceeds: Decimal | None = None
    net_proceeds: Decimal | None = None
    warrants: int | None = None
    warrant_exercise_price: Decimal | None = None
    potential_dilution_pct: float | None = None
    reverse_split_ratio: str | None = None
    reverse_split_date: datetime | None = None
    confidence: str = "low"  # low, medium, high
    extracted_text: str | None = None
    provider: DataProvider
    model: str
    analyzed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CorporateAction(BaseModel):
    """Corporate actions (splits, dividends, etc.)."""

    id: UUID = Field(default_factory=uuid4)
    symbol: str
    action_type: str  # "split", "reverse_split", "dividend", "spin_off", "merger"
    announced_date: datetime | None = None
    ex_date: datetime | None = None
    effective_date: datetime | None = None
    ratio: str | None = None  # e.g., "1:10" for reverse split
    dividend_amount: Decimal | None = None
    currency: str = "USD"
    source: DataProvider
    source_url: str | None = None


class RiskFlag(BaseModel):
    """Risk flag for a security."""

    id: UUID = Field(default_factory=uuid4)
    symbol: str
    flag_type: RiskFlagType
    severity: RiskSeverity
    detected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source: DataProvider
    source_url: str | None = None
    explanation: str
    score_penalty: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class TechnicalIndicators(BaseModel):
    """Technical indicators for a security."""

    symbol: str
    timestamp: datetime

    # Moving averages
    ema_5: float | None = None
    ema_9: float | None = None
    ema_20: float | None = None
    ema_50: float | None = None
    ema_200: float | None = None
    sma_20: float | None = None
    sma_50: float | None = None
    sma_200: float | None = None

    # Momentum
    rsi_14: float | None = None
    macd: float | None = None
    macd_signal: float | None = None
    macd_histogram: float | None = None
    roc_10: float | None = None

    # Volatility
    atr_14: float | None = None
    atr_pct: float | None = None
    realized_vol_20: float | None = None
    intraday_range_pct: float | None = None

    # Volume
    volume: int | None = None
    avg_volume_20: int | None = None
    rvol_daily: float | None = None
    rvol_same_time: float | None = None
    rvol_5m: float | None = None
    rvol_15m: float | None = None
    rvol_30m: float | None = None
    volume_acceleration: float | None = None
    dollar_volume: float | None = None

    # VWAP
    vwap: float | None = None
    vwap_distance_pct: float | None = None

    # Price action
    gap_pct: float | None = None
    change_pct: float | None = None
    distance_to_high: float | None = None
    distance_to_low: float | None = None
    distance_to_high_20d: float | None = None
    distance_to_high_52w: float | None = None
    breakout_5d: bool | None = None
    breakout_20d: bool | None = None
    breakout_50d: bool | None = None

    # Intraday structure
    higher_highs: bool | None = None
    higher_lows: bool | None = None
    momentum_5m: float | None = None
    momentum_15m: float | None = None
    momentum_30m: float | None = None
    momentum_60m: float | None = None

    # Additional
    bollinger_upper: float | None = None
    bollinger_lower: float | None = None
    bollinger_bandwidth: float | None = None
    adx_14: float | None = None
    obv: float | None = None

    provider: DataProvider


class ScoreBreakdown(BaseModel):
    """Detailed score breakdown."""

    momentum: int = 0
    volume: int = 0
    catalyst: int = 0
    technical: int = 0
    liquidity: int = 0
    fundamentals: int = 0
    data_quality: int = 0
    raw_score: int = 0

    # Risk penalties
    recent_offering: int = 0
    active_atm: int = 0
    reverse_split: int = 0
    low_liquidity: int = 0
    wide_spread: int = 0
    dilution: int = 0
    shelf_registration: int = 0
    warrant_overhang: int = 0
    convertible_debt: int = 0
    going_concern: int = 0
    delisting_warning: int = 0
    negative_working_capital: int = 0
    low_cash_runway: int = 0
    trading_halt: int = 0
    no_recent_filings: int = 0
    insufficient_data: int = 0
    news_unverified: int = 0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_penalty(self) -> int:
        return sum(
            [
                self.recent_offering,
                self.active_atm,
                self.reverse_split,
                self.low_liquidity,
                self.wide_spread,
                self.dilution,
                self.shelf_registration,
                self.warrant_overhang,
                self.convertible_debt,
                self.going_concern,
                self.delisting_warning,
                self.negative_working_capital,
                self.low_cash_runway,
                self.trading_halt,
                self.no_recent_filings,
                self.insufficient_data,
                self.news_unverified,
            ]
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def final_score(self) -> int:
        return max(0, self.raw_score - self.total_penalty)


class Score(BaseModel):
    """Score for a security."""

    id: UUID = Field(default_factory=uuid4)
    symbol: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    breakdown: ScoreBreakdown
    raw_score: int = 0
    risk_penalty: int = 0
    final_score: int = 0
    penalties: dict[str, int] = Field(default_factory=dict)
    components: dict[str, Any] = Field(default_factory=dict)
    features: dict[str, Any] = Field(default_factory=dict)
    config_version: str
    config_hash: str = "dev"
    data_quality: str = "unknown"  # high, medium, low, unknown
    missing_data: list[str] = Field(default_factory=list)


class ScannerSnapshot(BaseModel):
    """Scanner run snapshot for historical tracking."""

    id: UUID = Field(default_factory=uuid4)
    run_type: str  # "premarket", "intraday", "daily"
    started_at: datetime
    completed_at: datetime | None = None
    symbols_scanned: int = 0
    eligible_count: int = 0
    alerts_generated: int = 0
    duration_ms: int | None = None
    status: str = "running"  # running, completed, failed
    error: str | None = None
    config_hash: str


class Alert(BaseModel):
    """Alert/Notification."""

    id: UUID = Field(default_factory=uuid4)
    symbol: str
    score_id: UUID
    score: int
    signal_type: SignalType
    price: Decimal
    change_pct: float
    gap_pct: float | None = None
    rvol: float | None = None
    volume: int | None = None
    dollar_volume: float | None = None
    float_shares: int | None = None
    market_cap: Decimal | None = None
    catalyst_summary: str | None = None
    catalyst_strength: CatalystStrength | None = None
    risk_flags: list[RiskFlagType] = Field(default_factory=list)
    message: str
    providers: list[AlertProvider] = Field(default_factory=list)
    sent_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class WatchlistItem(BaseModel):
    """User watchlist item."""

    id: UUID = Field(default_factory=uuid4)
    user_id: str
    symbol: str
    added_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    notes: str | None = None
    tags: list[str] = Field(default_factory=list)


class BacktestResult(BaseModel):
    """Backtest result."""

    id: UUID = Field(default_factory=uuid4)
    name: str
    config_hash: str
    start_date: datetime
    end_date: datetime
    symbols_tested: int
    total_signals: int
    win_rate: float
    avg_return: float
    median_return: float
    expectancy: float
    profit_factor: float
    max_drawdown: float
    sharpe: float | None = None
    sortino: float | None = None
    mae: float | None = None  # Maximum Adverse Excursion
    mfe: float | None = None  # Maximum Favorable Excursion
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class BacktestTrade(BaseModel):
    """Individual backtest trade."""

    id: UUID = Field(default_factory=uuid4)
    backtest_id: UUID
    symbol: str
    entry_date: datetime
    entry_price: Decimal
    exit_date: datetime | None = None
    exit_price: Decimal | None = None
    return_pct: float | None = None
    holding_period_minutes: int | None = None
    max_favorable_pct: float | None = None
    max_adverse_pct: float | None = None
    score_at_entry: int
    signal_type: SignalType
