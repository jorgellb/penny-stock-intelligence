"""
SQLAlchemy ORM models for the database.
"""

from datetime import UTC, datetime, timezone
from decimal import Decimal
from enum import Enum as PyEnum
from typing import List, Optional
from uuid import uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy import (
    Enum as SQLEnum,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.models import (
    AlertProvider,
    CatalystCategory,
    DataProvider,
    Exchange,
    FilingType,
    ImpactLevel,
    OfferingType,
    RiskFlagType,
    RiskSeverity,
    SignalType,
    SourceReliability,
    TimeHorizon,
)
from app.domain.models import (
    Sentiment as SentimentEnum,
)


class Securities(Base):
    __tablename__ = "securities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    exchange: Mapped[str] = mapped_column(
        SQLEnum(Exchange, name="exchange_enum", create_constraint=False), nullable=False, index=True
    )
    is_etf: Mapped[bool] = mapped_column(Boolean, default=False)
    is_preferred: Mapped[bool] = mapped_column(Boolean, default=False)
    is_warrant: Mapped[bool] = mapped_column(Boolean, default=False)
    is_spac_unit: Mapped[bool] = mapped_column(Boolean, default=False)
    is_fund: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    cik: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    sic_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sector: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ipo_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("idx_securities_symbol_exchange", "symbol", "exchange"),
        Index("idx_securities_active_exchange", "is_active", "exchange"),
    )


class Quotes(Base):
    __tablename__ = "quotes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    bid: Mapped[Decimal | None] = mapped_column(String(20), nullable=True)
    ask: Mapped[Decimal | None] = mapped_column(String(20), nullable=True)
    bid_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    ask_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    last: Mapped[Decimal | None] = mapped_column(String(20), nullable=True)
    last_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    event_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    provider: Mapped[str] = mapped_column(
        SQLEnum(DataProvider, name="provider_enum", create_constraint=False), nullable=False
    )
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    metadata_: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        Index("idx_quotes_symbol_event", "symbol", "event_time"),
        Index("idx_quotes_symbol_received", "symbol", "received_at"),
        Index("idx_quotes_provider_received", "provider", "received_at"),
    )


class DailyBars(Base):
    __tablename__ = "daily_bars"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    open: Mapped[Decimal] = mapped_column(String(20), nullable=False)
    high: Mapped[Decimal] = mapped_column(String(20), nullable=False)
    low: Mapped[Decimal] = mapped_column(String(20), nullable=False)
    close: Mapped[Decimal] = mapped_column(String(20), nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False)
    vwap: Mapped[Decimal | None] = mapped_column(String(20), nullable=True)
    adjusted_close: Mapped[Decimal | None] = mapped_column(String(20), nullable=True)
    dividend: Mapped[Decimal | None] = mapped_column(String(20), nullable=True)
    split_coefficient: Mapped[Decimal | None] = mapped_column(String(20), nullable=True)
    provider: Mapped[str] = mapped_column(
        SQLEnum(DataProvider, name="provider_enum2", create_constraint=False), nullable=False
    )

    __table_args__ = (
        Index("idx_dailybars_symbol_date", "symbol", "date"),
        Index("idx_dailybars_date", "date"),
    )


class Fundamentals(Base):
    __tablename__ = "fundamentals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_type: Mapped[str] = mapped_column(String(20), nullable=False)
    market_cap: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    enterprise_value: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    shares_outstanding: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    float_shares: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    insider_ownership_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    institutional_ownership_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    revenue: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    gross_profit: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    operating_income: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    net_income: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    eps_diluted: Mapped[float | None] = mapped_column(Float, nullable=True)
    eps_basic: Mapped[float | None] = mapped_column(Float, nullable=True)
    cash: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    cash_equivalents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    short_term_investments: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    total_cash: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    total_debt: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    current_assets: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    current_liabilities: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    working_capital: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    total_assets: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    total_liabilities: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    shareholders_equity: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    operating_cash_flow: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    free_cash_flow: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    capital_expenditures: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    revenue_yoy_growth: Mapped[float | None] = mapped_column(Float, nullable=True)
    revenue_qoq_growth: Mapped[float | None] = mapped_column(Float, nullable=True)
    data_quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    provider: Mapped[str] = mapped_column(
        SQLEnum(DataProvider, name="provider_enum3", create_constraint=False), nullable=False
    )
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    __table_args__ = (
        Index("idx_fundamentals_symbol_period", "symbol", "period_end"),
        Index("idx_fundamentals_symbol_type", "symbol", "period_type"),
    )


class ShareStatistics(Base):
    __tablename__ = "share_statistics"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    shares_outstanding: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    float_shares: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    insider_shares: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    institutional_shares: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    short_interest: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    short_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    provider: Mapped[str] = mapped_column(
        SQLEnum(DataProvider, name="provider_enum4", create_constraint=False), nullable=False
    )

    __table_args__ = (Index("idx_share_stats_symbol_date", "symbol", "date"),)


class NewsArticles(Base):
    __tablename__ = "news_articles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    headline: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(200), nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(
        SQLEnum(DataProvider, name="provider_enum5", create_constraint=False), nullable=False
    )
    symbols_mentioned: Mapped[list[str]] = mapped_column(JSON, nullable=True, default=list)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    __table_args__ = (
        Index("idx_news_symbol_published", "symbol", "published_at"),
        Index("idx_news_content_hash", "content_hash"),
        Index("idx_news_published_received", "published_at", "received_at"),
    )


class NewsAnalysis(Base):
    __tablename__ = "news_analysis"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    article_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    category: Mapped[str] = mapped_column(
        SQLEnum(CatalystCategory, name="category_enum", create_constraint=False), nullable=False
    )
    sentiment: Mapped[str] = mapped_column(
        SQLEnum(SentimentEnum, name="sentiment_enum", create_constraint=False), nullable=False
    )
    impact: Mapped[str] = mapped_column(
        SQLEnum(ImpactLevel, name="impact_enum", create_constraint=False), nullable=False
    )
    time_horizon: Mapped[str] = mapped_column(
        SQLEnum(TimeHorizon, name="horizon_enum", create_constraint=False), nullable=False
    )
    is_material: Mapped[bool] = mapped_column(Boolean, default=False)
    is_primary_source: Mapped[bool] = mapped_column(Boolean, default=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    bullish_factors: Mapped[list[str]] = mapped_column(JSON, nullable=True, default=list)
    bearish_factors: Mapped[list[str]] = mapped_column(JSON, nullable=True, default=list)
    risk_factors: Mapped[list[str]] = mapped_column(JSON, nullable=True, default=list)
    provider: Mapped[str] = mapped_column(
        SQLEnum(DataProvider, name="provider_enum6", create_constraint=False), nullable=False
    )
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    analyzed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("idx_news_analysis_symbol_category", "symbol", "category"),
        Index("idx_news_analysis_article", "article_id"),
    )


class Filings(Base):
    __tablename__ = "filings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    cik: Mapped[str] = mapped_column(String(20), nullable=False)
    accession_number: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    filing_type: Mapped[str] = mapped_column(
        SQLEnum(FilingType, name="filing_type_enum", create_constraint=False), nullable=False
    )
    filing_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    report_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    primary_document: Mapped[str | None] = mapped_column(String(500), nullable=True)
    primary_doc_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    items: Mapped[list[str]] = mapped_column(JSON, nullable=True, default=list)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    provider: Mapped[str] = mapped_column(
        SQLEnum(DataProvider, name="provider_enum7", create_constraint=False), nullable=False
    )

    __table_args__ = (
        Index("idx_filings_symbol_type_date", "symbol", "filing_type", "filing_date"),
        Index("idx_filings_cik_date", "cik", "filing_date"),
        Index("idx_filings_accession", "accession_number", unique=True),
    )


class FilingAnalysis(Base):
    __tablename__ = "filing_analysis"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    filing_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    offering_type: Mapped[str | None] = mapped_column(
        SQLEnum(OfferingType, name="offering_enum", create_constraint=False), nullable=True
    )
    shares_offered: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    offering_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    gross_proceeds: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    net_proceeds: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    warrants: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    warrant_exercise_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    potential_dilution_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    reverse_split_ratio: Mapped[str | None] = mapped_column(String(20), nullable=True)
    reverse_split_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    confidence: Mapped[str] = mapped_column(
        SQLEnum(RiskSeverity, name="confidence_enum", create_constraint=False), nullable=False
    )
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider: Mapped[str] = mapped_column(
        SQLEnum(DataProvider, name="provider_enum8", create_constraint=False), nullable=False
    )
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    analyzed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("idx_filing_analysis_filing", "filing_id"),
        Index("idx_filing_analysis_symbol", "symbol"),
    )


class CorporateActions(Base):
    __tablename__ = "corporate_actions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    action_type: Mapped[str] = mapped_column(String(50), nullable=False)
    announced_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ex_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ratio: Mapped[str | None] = mapped_column(String(50), nullable=True)
    dividend_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="USD")
    source: Mapped[str] = mapped_column(
        SQLEnum(DataProvider, name="provider_enum9", create_constraint=False), nullable=False
    )
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    __table_args__ = (Index("idx_corp_actions_symbol_date", "symbol", "effective_date"),)


class RiskFlags(Base):
    __tablename__ = "risk_flags"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    flag_type: Mapped[str] = mapped_column(
        SQLEnum(RiskFlagType, name="risk_flag_enum", create_constraint=False), nullable=False
    )
    severity: Mapped[str] = mapped_column(
        SQLEnum(RiskSeverity, name="risk_severity_enum", create_constraint=False), nullable=False
    )
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    source: Mapped[str] = mapped_column(
        SQLEnum(DataProvider, name="provider_enum10", create_constraint=False), nullable=False
    )
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    score_penalty: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metadata_: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        Index("idx_risk_flags_symbol_type", "symbol", "flag_type"),
        Index("idx_risk_flags_symbol_detected", "symbol", "detected_at"),
    )


class TechnicalSnapshots(Base):
    __tablename__ = "technical_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    ema_5: Mapped[float | None] = mapped_column(Float, nullable=True)
    ema_9: Mapped[float | None] = mapped_column(Float, nullable=True)
    ema_20: Mapped[float | None] = mapped_column(Float, nullable=True)
    ema_50: Mapped[float | None] = mapped_column(Float, nullable=True)
    ema_200: Mapped[float | None] = mapped_column(Float, nullable=True)
    sma_20: Mapped[float | None] = mapped_column(Float, nullable=True)
    sma_50: Mapped[float | None] = mapped_column(Float, nullable=True)
    sma_200: Mapped[float | None] = mapped_column(Float, nullable=True)
    rsi_14: Mapped[float | None] = mapped_column(Float, nullable=True)
    macd: Mapped[float | None] = mapped_column(Float, nullable=True)
    macd_signal: Mapped[float | None] = mapped_column(Float, nullable=True)
    macd_histogram: Mapped[float | None] = mapped_column(Float, nullable=True)
    roc_10: Mapped[float | None] = mapped_column(Float, nullable=True)
    atr_14: Mapped[float | None] = mapped_column(Float, nullable=True)
    atr_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    realized_vol_20: Mapped[float | None] = mapped_column(Float, nullable=True)
    intraday_range_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    avg_volume_20: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    rvol_daily: Mapped[float | None] = mapped_column(Float, nullable=True)
    rvol_same_time: Mapped[float | None] = mapped_column(Float, nullable=True)
    rvol_5m: Mapped[float | None] = mapped_column(Float, nullable=True)
    rvol_15m: Mapped[float | None] = mapped_column(Float, nullable=True)
    rvol_30m: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume_acceleration: Mapped[float | None] = mapped_column(Float, nullable=True)
    dollar_volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    vwap: Mapped[float | None] = mapped_column(Float, nullable=True)
    vwap_distance_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    gap_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    change_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    distance_to_high: Mapped[float | None] = mapped_column(Float, nullable=True)
    distance_to_low: Mapped[float | None] = mapped_column(Float, nullable=True)
    distance_to_high_20d: Mapped[float | None] = mapped_column(Float, nullable=True)
    distance_to_high_52w: Mapped[float | None] = mapped_column(Float, nullable=True)
    breakout_5d: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    breakout_20d: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    breakout_50d: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    higher_highs: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    higher_lows: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    momentum_5m: Mapped[float | None] = mapped_column(Float, nullable=True)
    momentum_15m: Mapped[float | None] = mapped_column(Float, nullable=True)
    momentum_30m: Mapped[float | None] = mapped_column(Float, nullable=True)
    momentum_60m: Mapped[float | None] = mapped_column(Float, nullable=True)
    bollinger_upper: Mapped[float | None] = mapped_column(Float, nullable=True)
    bollinger_lower: Mapped[float | None] = mapped_column(Float, nullable=True)
    bollinger_bandwidth: Mapped[float | None] = mapped_column(Float, nullable=True)
    adx_14: Mapped[float | None] = mapped_column(Float, nullable=True)
    obv: Mapped[float | None] = mapped_column(Float, nullable=True)
    provider: Mapped[str] = mapped_column(
        SQLEnum(DataProvider, name="provider_enum11", create_constraint=False), nullable=False
    )

    __table_args__ = (
        Index("idx_tech_snap_symbol_ts", "symbol", "timestamp"),
        Index("idx_tech_snap_ts", "timestamp"),
    )


class Scores(Base):
    __tablename__ = "scores"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    raw_score: Mapped[int] = mapped_column(Integer, nullable=False)
    risk_penalty: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    final_score: Mapped[int] = mapped_column(Integer, nullable=False)
    breakdown: Mapped[dict] = mapped_column(JSON, nullable=False)
    penalties: Mapped[dict] = mapped_column(JSON, nullable=False)
    components: Mapped[dict] = mapped_column(JSON, nullable=False)
    features: Mapped[dict] = mapped_column(JSON, nullable=False)
    data_quality: Mapped[str] = mapped_column(String(20), nullable=False)
    missing_data: Mapped[list[str]] = mapped_column(JSON, nullable=True, default=list)
    config_version: Mapped[str] = mapped_column(String(50), nullable=False)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    data_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("idx_scores_symbol_ts", "symbol", "timestamp"),
        Index("idx_scores_ts_final", "timestamp", "final_score"),
        Index("idx_scores_symbol_final", "symbol", "final_score"),
    )


class ScannerSnapshots(Base):
    __tablename__ = "scanner_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    run_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    security_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("securities.id"), nullable=True
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    symbols_scanned: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    eligible_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    alerts_generated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        Index("idx_scanner_runs_type_status", "run_type", "status"),
        Index("idx_scanner_runs_started", "started_at"),
    )


class MonitorSnapshots(Base):
    """Per-symbol monitor evaluations: the dataset for calibration (§70).

    One row per symbol per round with the features that produced the
    signal. Future returns are NEVER written here (targets live only in
    training/backtest frames) to prevent leakage into live features.
    """

    __tablename__ = "monitor_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(10), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    change_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    rvol: Mapped[float | None] = mapped_column(Float, nullable=True)
    vwap_distance_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_flags: Mapped[list[str]] = mapped_column(JSON, nullable=True, default=list)
    regime: Mapped[str | None] = mapped_column(String(20), nullable=True)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True, default=lambda: datetime.now(UTC)
    )

    __table_args__ = (Index("idx_monitor_symbol_created", "symbol", "created_at"),)


class Alerts(Base):
    __tablename__ = "alerts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    score_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("scores.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(10), nullable=False, default="hold")
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    signal_type: Mapped[str] = mapped_column(
        SQLEnum(SignalType, name="signal_enum", create_constraint=False), nullable=False
    )
    price: Mapped[float] = mapped_column(Float, nullable=False)
    change_pct: Mapped[float] = mapped_column(Float, nullable=False)
    gap_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    rvol: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    dollar_volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    float_shares: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    market_cap: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    catalyst_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    catalyst_strength: Mapped[str | None] = mapped_column(
        SQLEnum(ImpactLevel, name="catalyst_strength_enum", create_constraint=False), nullable=True
    )
    risk_flags: Mapped[list[str]] = mapped_column(JSON, nullable=True, default=list)
    reasons: Mapped[list[str]] = mapped_column(JSON, nullable=True, default=list)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    providers: Mapped[list[str]] = mapped_column(JSON, nullable=True, default=list)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True, default=lambda: datetime.now(UTC)
    )
    cooldown_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    __table_args__ = (
        Index("idx_alerts_symbol_created", "symbol", "created_at"),
        Index("idx_alerts_signal_created", "signal_type", "created_at"),
        Index("idx_alerts_cooldown", "cooldown_until"),
    )


class WatchlistItems(Base):
    __tablename__ = "watchlist"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    list_name: Mapped[str] = mapped_column(String(100), nullable=False, default="default")
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=True, default=list)

    __table_args__ = (
        Index("idx_watchlist_user_list", "user_id", "list_name"),
        Index("idx_watchlist_user_list_symbol", "user_id", "list_name", "symbol", unique=True),
    )


class BacktestResults(Base):
    __tablename__ = "backtest_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    symbols_tested: Mapped[int] = mapped_column(Integer, nullable=False)
    total_signals: Mapped[int] = mapped_column(Integer, nullable=False)
    win_rate: Mapped[float] = mapped_column(Float, nullable=False)
    avg_return: Mapped[float] = mapped_column(Float, nullable=False)
    median_return: Mapped[float] = mapped_column(Float, nullable=False)
    expectancy: Mapped[float] = mapped_column(Float, nullable=False)
    profit_factor: Mapped[float] = mapped_column(Float, nullable=False)
    max_drawdown: Mapped[float] = mapped_column(Float, nullable=False)
    sharpe: Mapped[float | None] = mapped_column(Float, nullable=True)
    sortino: Mapped[float | None] = mapped_column(Float, nullable=True)
    mae: Mapped[float | None] = mapped_column(Float, nullable=True)
    mfe: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("idx_backtest_name_date", "name", "start_date"),)


class BacktestTrades(Base):
    __tablename__ = "backtest_trades"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    backtest_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("backtest_results.id"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    entry_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    exit_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    return_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    holding_period_minutes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    max_favorable_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_adverse_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_at_entry: Mapped[int] = mapped_column(Integer, nullable=False)
    signal_type: Mapped[str] = mapped_column(
        SQLEnum(SignalType, name="signal_enum2", create_constraint=False), nullable=False
    )

    __table_args__ = (
        Index("idx_backtest_trades_backtest", "backtest_id"),
        Index("idx_backtest_trades_symbol", "symbol"),
    )


class ProviderRequests(Base):
    __tablename__ = "provider_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    provider: Mapped[str] = mapped_column(
        SQLEnum(DataProvider, name="provider_enum12", create_constraint=False), nullable=False
    )
    endpoint: Mapped[str] = mapped_column(String(200), nullable=False)
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_ms: Mapped[float] = mapped_column(Float, nullable=False)
    cached: Mapped[bool] = mapped_column(Boolean, default=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    __table_args__ = (Index("idx_provider_requests_provider_ts", "provider", "timestamp"),)


class DataQualityLog(Base):
    __tablename__ = "data_quality_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    data_type: Mapped[str] = mapped_column(String(50), nullable=False)
    completeness: Mapped[float] = mapped_column(Float, nullable=False)
    freshness_seconds: Mapped[int] = mapped_column(BigInteger, nullable=False)
    stale: Mapped[bool] = mapped_column(Boolean, default=False)
    missing_fields: Mapped[list[str]] = mapped_column(JSON, nullable=True, default=list)
    provider: Mapped[str] = mapped_column(
        SQLEnum(DataProvider, name="provider_enum13", create_constraint=False), nullable=False
    )
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("idx_dq_symbol_type", "symbol", "data_type"),)


class CircuitEvents(Base):
    """Audit trail for symbol/strategy/portfolio circuit breakers."""

    __tablename__ = "circuit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    level: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True, default=lambda: datetime.now(UTC)
    )

    __table_args__ = (Index("idx_circuit_level_created", "level", "created_at"),)


class PaperTrades(Base):
    """Closed paper trades (audit trail; live positions stay in memory)."""

    __tablename__ = "paper_trades"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    shares: Mapped[int] = mapped_column(Integer, nullable=False)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    exit_price: Mapped[float] = mapped_column(Float, nullable=False)
    pnl_dollars: Mapped[float] = mapped_column(Float, nullable=False)
    pnl_pct: Mapped[float] = mapped_column(Float, nullable=False)
    entry_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    exit_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True, default=lambda: datetime.now(UTC)
    )

    __table_args__ = (Index("idx_paper_symbol_exit", "symbol", "exit_time"),)


class PaperPositions(Base):
    """Open paper positions (one row per symbol; deleted on close)."""

    __tablename__ = "paper_positions"

    symbol: Mapped[str] = mapped_column(String(20), primary_key=True)
    shares: Mapped[int] = mapped_column(Integer, nullable=False)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    entry_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


__all__ = [
    "Base",
    "Securities",
    "Quotes",
    "DailyBars",
    "Fundamentals",
    "ShareStatistics",
    "NewsArticles",
    "NewsAnalysis",
    "Filings",
    "FilingAnalysis",
    "CorporateActions",
    "RiskFlags",
    "TechnicalSnapshots",
    "Scores",
    "ScannerSnapshots",
    "Alerts",
    "WatchlistItems",
    "BacktestResults",
    "BacktestTrades",
    "ProviderRequests",
    "DataQualityLog",
    "CircuitEvents",
    "PaperTrades",
    "PaperPositions",
    "MonitorSnapshots",
]
