"""
Provider interfaces (protocols) for dependency injection and abstraction.
"""

from collections.abc import AsyncGenerator
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Protocol
from uuid import UUID

from app.domain.models import (
    Bar,
    CatalystCategory,
    CorporateAction,
    DailyBar,
    DataProvider,
    Exchange,
    Filing,
    FilingAnalysis,
    Fundamentals,
    ImpactLevel,
    NewsAnalysis,
    NewsArticle,
    OfferingType,
    Quote,
    RiskFlag,
    RiskFlagType,
    RiskSeverity,
    ScannerSnapshot,
    Security,
    Sentiment,
    ShareStatistics,
    TechnicalIndicators,
    TimeHorizon,
)


class MarketDataProvider(Protocol):
    """Market data provider interface."""

    async def get_quote(self, symbol: str) -> Quote:
        """Get real-time quote for a symbol."""
        ...

    async def get_quotes(self, symbols: list[str]) -> dict[str, Quote]:
        """Get real-time quotes for multiple symbols."""
        ...

    async def get_bars(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime | None = None,
        limit: int | None = None,
    ) -> list[Bar]:
        """Get intraday bars for a symbol."""
        ...

    async def get_daily_bars(
        self,
        symbol: str,
        start: datetime,
        end: datetime | None = None,
        limit: int | None = None,
        adjusted: bool = True,
    ) -> list[DailyBar]:
        """Get daily bars for a symbol."""
        ...

    async def get_latest_bar(self, symbol: str, timeframe: str) -> Bar | None:
        """Get the most recent bar for a symbol."""
        ...

    async def search_symbols(
        self,
        query: str,
        exchanges: list[Exchange] | None = None,
    ) -> list[Security]:
        """Search for symbols matching query."""
        ...

    async def get_universe(
        self,
        min_price: float,
        max_price: float,
        exchanges: list[Exchange],
        include_otc: bool = False,
    ) -> list[Security]:
        """Get universe of securities matching criteria."""
        ...

    @property
    def name(self) -> DataProvider:
        """Provider name."""
        ...

    @property
    def rate_limit_per_minute(self) -> int:
        """Rate limit in requests per minute."""
        ...

    async def health_check(self) -> bool:
        """Check if provider is healthy."""
        ...


class FundamentalsProvider(Protocol):
    """Fundamentals data provider interface."""

    async def get_fundamentals(
        self,
        symbol: str,
        period_type: str = "ttm",
    ) -> Fundamentals | None:
        """Get fundamental data for a symbol."""
        ...

    async def get_fundamentals_batch(
        self,
        symbols: list[str],
        period_type: str = "ttm",
    ) -> dict[str, Fundamentals]:
        """Get fundamental data for multiple symbols."""
        ...

    async def get_share_statistics(self, symbol: str) -> ShareStatistics | None:
        """Get share statistics for a symbol."""
        ...

    async def get_share_statistics_batch(
        self,
        symbols: list[str],
    ) -> dict[str, ShareStatistics]:
        """Get share statistics for multiple symbols."""
        ...

    @property
    def name(self) -> DataProvider:
        """Provider name."""
        ...

    @property
    def rate_limit_per_minute(self) -> int:
        """Rate limit in requests per minute."""
        ...

    async def health_check(self) -> bool:
        """Check if provider is healthy."""
        ...


class NewsProvider(Protocol):
    """News provider interface."""

    async def get_news(
        self,
        symbols: list[str] | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 100,
    ) -> list[NewsArticle]:
        """Get news articles."""
        ...

    async def get_news_for_symbol(
        self,
        symbol: str,
        start: datetime | None = None,
        limit: int = 50,
    ) -> list[NewsArticle]:
        """Get news for a specific symbol."""
        ...

    @property
    def name(self) -> DataProvider:
        """Provider name."""
        ...

    @property
    def rate_limit_per_minute(self) -> int:
        """Rate limit in requests per minute."""
        ...

    async def health_check(self) -> bool:
        """Check if provider is healthy."""
        ...


class FilingProvider(Protocol):
    """SEC filings provider interface."""

    async def get_filings(
        self,
        symbol: str,
        filing_types: list[str] | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 50,
    ) -> list[Filing]:
        """Get SEC filings for a symbol."""
        ...

    async def get_filing_content(self, filing: Filing) -> str:
        """Get filing document content."""
        ...

    async def get_recent_filings(
        self,
        symbols: list[str] | None = None,
        filing_types: list[str] | None = None,
        hours: int = 24,
    ) -> list[Filing]:
        """Get recent filings across symbols."""
        ...

    async def get_corporate_actions(
        self,
        symbol: str,
        start: datetime | None = None,
    ) -> list[CorporateAction]:
        """Get corporate actions for a symbol."""
        ...

    @property
    def name(self) -> DataProvider:
        """Provider name."""
        ...

    @property
    def rate_limit_per_minute(self) -> int:
        """Rate limit in requests per minute."""
        ...

    async def health_check(self) -> bool:
        """Check if provider is healthy."""
        ...


class AIProvider(Protocol):
    """AI/LLM provider interface for structured analysis."""

    async def analyze_news(
        self,
        article: NewsArticle,
    ) -> NewsAnalysis:
        """Analyze news article and return structured output."""
        ...

    async def analyze_filing(
        self,
        filing: Filing,
        content: str,
    ) -> FilingAnalysis:
        """Analyze SEC filing and return structured output."""
        ...

    async def classify_catalyst(
        self,
        text: str,
        symbol: str,
    ) -> dict[str, Any]:
        """Classify catalyst from text."""
        ...

    @property
    def name(self) -> DataProvider:
        """Provider name."""
        ...

    @property
    def model(self) -> str:
        """Model name."""
        ...

    async def health_check(self) -> bool:
        """Check if provider is healthy."""
        ...


class AlertProvider(Protocol):
    """Alert delivery provider interface."""

    async def send(self, alert: Any) -> bool:
        """Send alert. Returns True if successful."""
        ...

    async def send_batch(self, alerts: list[Any]) -> dict[str, bool]:
        """Send multiple alerts. Returns dict of alert_id -> success."""
        ...

    @property
    def name(self) -> str:
        """Provider name."""
        ...

    async def health_check(self) -> bool:
        """Check if provider is healthy."""
        ...


class BrokerAdapter(Protocol):
    """Broker adapter interface for future trading integration."""

    async def get_account(self) -> dict[str, Any]:
        """Get account information."""
        ...

    async def get_positions(self) -> list[dict[str, Any]]:
        """Get current positions."""
        ...

    async def place_order(
        self,
        symbol: str,
        qty: int,
        side: str,
        order_type: str,
        limit_price: Decimal | None = None,
        stop_price: Decimal | None = None,
        time_in_force: str = "day",
    ) -> dict[str, Any]:
        """Place an order."""
        ...

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an order."""
        ...

    async def get_order(self, order_id: str) -> dict[str, Any]:
        """Get order status."""
        ...

    async def get_orders(self, status: str | None = None) -> list[dict[str, Any]]:
        """Get orders."""
        ...

    @property
    def name(self) -> str:
        """Broker name."""
        ...

    async def health_check(self) -> bool:
        """Check if broker is connected."""
        ...
