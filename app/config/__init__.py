"""
Application configuration management using Pydantic Settings.
"""

from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml  # type: ignore[import-untyped]
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class UniverseConfig(BaseSettings):
    """Universe scanning configuration."""

    country: str = "US"
    min_price: float = 0.10
    max_price: float = 5.00
    exchanges: list[str] = Field(default_factory=lambda: ["NASDAQ", "NYSE", "AMEX"])
    include_otc: bool = False
    exclude_etfs: bool = True
    exclude_preferred: bool = True
    exclude_warrants: bool = True
    exclude_spac_units: bool = True
    exclude_funds: bool = True


class LiquidityConfig(BaseSettings):
    """Liquidity filtering configuration."""

    min_avg_daily_volume: int = 500000
    min_daily_dollar_volume: float = 1000000.0
    max_spread_pct: float = 5.0
    min_float: int = 1000000


class MarketConfig(BaseSettings):
    """Market hours configuration."""

    premarket_enabled: bool = True
    afterhours_enabled: bool = False
    timezone: str = "America/New_York"


class ScannerConfig(BaseSettings):
    """Scanner behavior configuration."""

    refresh_seconds: int = 60
    premarket_refresh_seconds: int = 30
    intraday_refresh_seconds: int = 15
    max_symbols_per_batch: int = 100
    request_timeout_seconds: int = 10
    max_concurrent_requests: int = 10


class AlertsConfig(BaseSettings):
    """Alert configuration."""

    minimum_score: int = 70
    cooldown_minutes: int = 20
    score_change_realert: int = 10
    enabled_providers: list[str] = Field(default_factory=lambda: ["console", "telegram"])


class SetupToggles(BaseSettings):
    """Which BUY playbooks are active. All on by default for max coverage."""

    momentum_vwap: bool = True
    gap_and_go: bool = True
    donchian_breakout: bool = True
    accumulation_markup: bool = True
    squeeze_continuation: bool = True
    catalyst_impulse: bool = True


class MonitorConfig(BaseSettings):
    """Realtime list-monitor configuration (buy/sell signals for review)."""

    enabled: bool = True
    interval_seconds: int = 60
    buy_min_score: int = 70
    buy_min_rvol: float = 2.0
    buy_require_above_vwap: bool = True
    buy_max_spread_pct: float = 5.0
    sell_score_drop: int = 15
    sell_vwap_break_pct: float = 3.0
    block_flags: list[str] = Field(
        default_factory=lambda: [
            "TRADING_HALT",
            "RECENT_OFFERING",
            "ACTIVE_ATM",
            "DELISTING_WARNING",
            "GOING_CONCERN",
        ]
    )
    max_symbols: int = 200
    # Entry gates (opt-in; None/False = off, current behavior preserved).
    buy_min_dollar_volume: float | None = None
    buy_min_change_pct: float | None = None
    buy_require_catalyst: bool = False
    sell_take_profit_pct: float | None = None
    sell_stop_loss_pct: float | None = None
    max_buys_per_round: int | None = None
    regime_enabled: bool = True
    halt_storm_threshold: int = 10
    correlation_enabled: bool = True
    max_corr: float = 0.85
    regime_chop_min_score: float = 80.0
    regime_chop_min_rvol: float = 4.0
    regime_riskoff_min_score: float = 80.0
    regime_riskoff_min_rvol: float = 4.0
    circuit_enabled: bool = True
    # Multi-setup playbooks
    setups: SetupToggles = Field(default_factory=SetupToggles)
    gap_min_change_pct: float = 5.0
    gap_min_score: int = 60
    gap_min_rvol: float = 2.0
    donchian_min_score: int = 65
    markup_min_score: int = 65
    markup_min_rvol: float = 1.5
    squeeze_min_score: int = 65
    squeeze_min_rvol: float = 2.0
    catalyst_min_score: int = 60
    catalyst_min_rvol: float = 2.5
    catalyst_setup_min_confidence: float = 0.6
    # Opportunity radar
    radar_enabled: bool = True
    radar_list_name: str = "radar"
    radar_max_symbols: int = 40
    radar_min_score: int = 55
    radar_min_rvol: float = 1.5
    radar_min_change_pct: float = 2.0
    # Chase guard: demote BUYs too far above VWAP / with exhausted RSI.
    buy_block_overextended: bool = True
    extension_max_vwap_atr: float = 1.0
    extension_max_vwap_pct: float = 15.0
    extension_max_rsi: float = 88.0
    # Trade plan (entry / structural stop / R-multiple targets)
    plan_min_stop_pct: float = 3.0
    plan_max_stop_pct: float = 12.0
    plan_min_rr: float = 2.0
    plan_exits_enabled: bool = True


class SizingConfig(BaseSettings):
    """Dynamic position sizing (fractional risk over ATR)."""

    risk_per_trade_pct: float = 0.005
    high_score_bonus_pct: float = 0.01
    high_score_threshold: int = 85
    atr_multiple: float = 1.5
    max_volume_participation: float = 0.05
    max_float_participation: float = 0.10
    paper_equity: float = 10000.0


class CircuitConfig(BaseSettings):
    """Circuit breakers: symbol / strategy / portfolio."""

    symbol_max_loss_pct: float = 8.0
    strategy_max_daily_loss_pct: float = 3.0
    portfolio_max_daily_loss_pct: float = 5.0
    max_halts_per_day: int = 3


class ExecutionConfig(BaseSettings):
    """Manual-assisted execution (DEGIRO). Limit orders only, always."""

    limit_only: bool = True
    default_venue: str = "ARCA"
    urgency_offset_bps: int = 10
    allowed_venues: list[str] = Field(default_factory=lambda: ["ARCA", "BATS", "EDGX"])


class GateConfig(BaseSettings):
    """Donchian breakout + squeeze gate thresholds."""

    donchian_min_rvol: float = 3.0
    donchian_chop_rvol: float = 4.0
    catalyst_min_confidence: float = 0.8
    catalyst_max_age_hours: float = 24.0
    max_spread_pct: float = 2.0
    min_dollar_volume: float = 2_000_000.0
    max_short_interest_pct: float = 20.0
    max_borrow_rate_pct: float = 10.0


class FeedConfig(BaseSettings):
    """Market feed selection (SIP retail reality vs Direct institutional).

    SIP consolidates with ms latency vs direct feeds; a retail monitor
    without co-location must be honest about it: every fetch measures
    its lag and rounds above max_fetch_lag_ms are marked STALE.
    kind=direct requires entitlement or the monitor falls back to SIP
    with an explicit warning (never silently).
    """

    kind: str = "sip"
    max_fetch_lag_ms: int = 1500
    direct_entitlement: str | None = None


class RiskConfig(BaseSettings):
    """Risk flag configuration."""

    exclude_recent_reverse_split: bool = False
    penalize_offerings: bool = True
    penalize_atm: bool = True
    penalize_shelf_registration: bool = True
    penalize_warrant_overhang: bool = True
    penalize_convertible_debt: bool = True
    penalize_dilution: bool = True
    penalize_low_liquidity: bool = True
    penalize_wide_spread: bool = True
    reverse_split_lookback_days: int = 90
    offering_lookback_days: int = 30
    dilution_threshold_pct: float = 10.0
    low_float_max: int = 20000000
    micro_float_max: int = 5000000


class FloatConfig(BaseSettings):
    """Float classification configuration."""

    micro_float_max: int = 5000000
    low_float_max: int = 20000000


class ScoringWeights(BaseSettings):
    """Scoring weights configuration."""

    momentum: int = 20
    volume: int = 20
    catalyst: int = 20
    technical: int = 15
    liquidity: int = 10
    fundamentals: int = 10
    data_quality: int = 5


class ScoringPenalties(BaseSettings):
    """Scoring penalties configuration."""

    recent_offering: int = 20
    active_atm: int = 20
    reverse_split: int = 10
    low_liquidity: int = 25
    wide_spread: int = 15
    dilution: int = 25
    shelf_registration: int = 15
    warrant_overhang: int = 10
    convertible_debt: int = 10
    going_concern: int = 30
    delisting_warning: int = 30
    negative_working_capital: int = 15
    low_cash_runway: int = 15
    trading_halt: int = 50
    no_recent_filings: int = 10
    insufficient_data: int = 20
    news_unverified: int = 5
    # Low float is the fuel of penny runners, not a defect: its risk is
    # handled by sizing (float participation cap) and plan stops.
    low_float: int = 0
    micro_float: int = 5


class ScoringConfig(BaseSettings):
    """Scoring configuration."""

    weights: ScoringWeights = Field(default_factory=ScoringWeights)
    penalties: ScoringPenalties = Field(default_factory=ScoringPenalties)


class ProviderCacheTTL(BaseSettings):
    """Cache TTL configuration for providers."""

    quotes: int = 5
    bars: int = 60
    daily_bars: int = 3600


class MarketDataProviderConfig(BaseSettings):
    """Market data provider configuration."""

    primary: str = "yfinance"
    fallback: str = "alpha_vantage"
    cache_ttl_seconds: ProviderCacheTTL = Field(default_factory=ProviderCacheTTL)


class FundamentalsProviderConfig(BaseSettings):
    """Fundamentals provider configuration."""

    primary: str = "yfinance"
    fallback: str = "alpha_vantage"
    cache_ttl_seconds: int = 3600


class NewsProviderConfig(BaseSettings):
    """News provider configuration."""

    primary: str = "finnhub"
    fallback: str = "alpha_vantage"
    cache_ttl_seconds: int = 300


class SecProviderConfig(BaseSettings):
    """SEC filings provider configuration."""

    primary: str = "sec_edgar"
    cache_ttl_seconds: int = 3600


class AIProviderConfig(BaseSettings):
    """AI provider configuration."""

    primary: str = "openai"
    fallback: str = "anthropic"
    model: str = "gpt-4o-mini"
    max_tokens: int = 1000
    temperature: float = 0.1


class ProvidersConfig(BaseSettings):
    """All providers configuration."""

    market_data: MarketDataProviderConfig = Field(default_factory=MarketDataProviderConfig)
    fundamentals: FundamentalsProviderConfig = Field(default_factory=FundamentalsProviderConfig)
    news: NewsProviderConfig = Field(default_factory=NewsProviderConfig)
    sec: SecProviderConfig = Field(default_factory=SecProviderConfig)
    ai: AIProviderConfig = Field(default_factory=AIProviderConfig)


class SchedulerJobConfig(BaseSettings):
    """Individual scheduler job configuration."""

    sync_universe: str = "0 6 * * 1-5"
    sync_daily_history: str = "0 7 * * 1-5"
    sync_fundamentals: str = "0 8 * * 1-5"
    sync_filings: str = "*/30 * * * 1-5"
    sync_filings_fast: str = "*/5 * * * 1-5"
    sync_news: str = "*/15 * * * 1-5"
    premarket_scan: str = "*/5 4-9 * * 1-5"
    intraday_scan: str = "*/2 9-16 * * 1-5"
    radar: str = "*/3 4-16 * * 1-5"
    risk_refresh: str = "0 * * * 1-5"
    alert_dispatch: str = "*/1 * * * 1-5"
    data_cleanup: str = "0 2 * * *"


class SchedulerConfig(BaseSettings):
    """Scheduler configuration."""

    jobs: SchedulerJobConfig = Field(default_factory=SchedulerJobConfig)


class BacktestingConfig(BaseSettings):
    """Backtesting configuration."""

    default_commission_pct: float = 0.001
    default_slippage_pct: float = 0.01
    min_liquidity_for_execution: int = 500000
    default_spread_threshold_pct: float = 3.0
    default_spread_penalty_pct: float = 0.01


class CacheConfig(BaseSettings):
    """Cache configuration."""

    redis_url: str = "redis://localhost:6379/0"
    default_ttl_seconds: int = 300


class LoggingConfig(BaseSettings):
    """Logging configuration."""

    level: str = "INFO"
    format: str = "json"
    file: str = "logs/app.log"


class DatabaseConfig(BaseSettings):
    """Database configuration."""

    pool_size: int = 10
    max_overflow: int = 20
    pool_timeout: int = 30


class SecurityConfig(BaseSettings):
    """Security configuration."""

    api_key_header: str = "X-API-Key"
    # None = auto: required in production/staging, optional in development/test
    require_api_key: bool | None = None
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:8501",
            "http://127.0.0.1:8501",
        ]
    )
    cors_allow_credentials: bool = True
    rate_limit_requests: int = 100
    rate_limit_window_seconds: int = 60
    # Stricter budget for POST /monitor/run (per API key or client IP)
    monitor_run_rate_limit: int = 10


class Settings(BaseSettings):
    """Main application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        nested_model_default_partial_update=True,
    )

    # Environment
    environment: str = "development"
    debug: bool = False
    log_level: str = "INFO"
    secret_key: str = "change-me-in-production"

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/penny_stocks"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # API Keys - Market Data
    alpha_vantage_api_key: str | None = None
    finnhub_api_key: str | None = None
    polygon_api_key: str | None = None
    twelve_data_api_key: str | None = None

    # API Keys - AI
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None

    # API Keys - Alerts
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    discord_webhook_url: str | None = None
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    email_from: str | None = None
    email_to: str | None = None
    webhook_url: str | None = None
    webhook_secret: str | None = None

    # SEC
    sec_edgar_user_agent: str = "PennyStockIntelligence/0.1"

    # Trading
    paper_mode: bool = True
    live_trading: bool = False

    # API Security
    api_key: str = "your-secure-api-key-here"
    api_rate_limit: int = 100
    api_rate_limit_window: int = 60

    # Nested configurations (loaded from YAML)
    universe: UniverseConfig = Field(default_factory=UniverseConfig)
    liquidity: LiquidityConfig = Field(default_factory=LiquidityConfig)
    market: MarketConfig = Field(default_factory=MarketConfig)
    scanner: ScannerConfig = Field(default_factory=ScannerConfig)
    alerts: AlertsConfig = Field(default_factory=AlertsConfig)
    monitor: MonitorConfig = Field(default_factory=MonitorConfig)
    feed: FeedConfig = Field(default_factory=FeedConfig)
    sizing: SizingConfig = Field(default_factory=SizingConfig)
    circuit: CircuitConfig = Field(default_factory=CircuitConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    gates: GateConfig = Field(default_factory=GateConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    float: FloatConfig = Field(default_factory=FloatConfig)
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)
    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    backtesting: BacktestingConfig = Field(default_factory=BacktestingConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)

    @field_validator("database_url", mode="before")
    @classmethod
    def validate_database_url(cls, v: Any) -> str:
        if isinstance(v, str) and v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql+asyncpg://", 1)
        return str(v)

    @classmethod
    def from_yaml(cls, path: str = "config/settings.yaml") -> "Settings":
        """Load settings from YAML file and merge with environment variables."""
        yaml_path = Path(path)
        if yaml_path.exists():
            with open(yaml_path) as f:
                yaml_data = yaml.safe_load(f) or {}
            # Create instance with YAML data as defaults, then env vars override
            return cls(**yaml_data)
        return cls()


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings.from_yaml()


def reload_settings() -> Settings:
    """Force reload of settings (clears cache)."""
    get_settings.cache_clear()
    return get_settings()


def config_fingerprint(settings: Settings | None = None) -> str:
    """Stable hash of the scoring-relevant config (§64 config versioning).

    Stored with every snapshot/score so historic rows keep their meaning
    when weights change.
    """
    import hashlib
    import json

    s = settings or get_settings()
    payload = {
        "monitor": s.monitor.model_dump(),
        "scoring": s.scoring.model_dump(),
        "circuit": s.circuit.model_dump(),
        "gates": s.gates.model_dump(),
        "risk": s.risk.model_dump(),
        "sizing": s.sizing.model_dump(),
        "backtesting": s.backtesting.model_dump(),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
