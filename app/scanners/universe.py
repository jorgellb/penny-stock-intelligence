"""
Universe engine: scans and filters stocks.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.config import get_settings
from app.domain.models import (
    Exchange,
)


@dataclass
class FilterResult:
    """Result of filtering a single symbol."""

    symbol: str
    eligible: bool
    reasons: list[str] = field(default_factory=list)
    price: float | None = None
    volume: int | None = None
    dollar_volume: float | None = None
    spread_pct: float | None = None
    exchange: str | None = None


@dataclass
class ScanResult:
    """Result of a universe scan."""

    timestamp: datetime
    total_symbols: int
    eligible_count: int
    excluded_count: int
    results: list[FilterResult] = field(default_factory=list)
    duration_ms: int | None = None


class UniverseEngine:
    """Scans and filters the stock universe."""

    def __init__(self, market_data_provider: Any = None) -> None:
        self.market_data_provider = market_data_provider
        self.settings = get_settings()
        self.universe_config = self.settings.universe
        self.liquidity_config = self.settings.liquidity

    def get_filter_result(
        self,
        symbol: str,
        price: float,
        volume: int | None = None,
        spread_pct: float | None = None,
        exchange: str | None = None,
    ) -> FilterResult:
        """Filter a single symbol against universe criteria."""
        reasons: list[str] = []
        eligible = True

        # Price filter
        if price < self.universe_config.min_price:
            reasons.append("below_min_price")
            eligible = False
        if price > self.universe_config.max_price:
            reasons.append("above_max_price")
            eligible = False

        # Exchange filter
        if exchange and exchange not in self.universe_config.exchanges:
            reasons.append("exchange_not_enabled")
            eligible = False

        # OTC filter
        if not self.universe_config.include_otc and exchange == Exchange.OTC.value:
            reasons.append("otc_not_enabled")
            eligible = False

        # Liquidity filter
        if volume is not None and volume < self.liquidity_config.min_avg_daily_volume:
            reasons.append("avg_daily_volume_below_threshold")
            eligible = False

        dollar_volume = (price * volume) if volume is not None and price > 0 else None
        if (
            dollar_volume is not None
            and dollar_volume < self.liquidity_config.min_daily_dollar_volume
        ):
            reasons.append("dollar_volume_below_threshold")
            eligible = False

        if spread_pct is not None and spread_pct > self.liquidity_config.max_spread_pct:
            reasons.append("spread_too_wide")
            eligible = False

        return FilterResult(
            symbol=symbol,
            eligible=eligible,
            reasons=reasons,
            price=price,
            volume=volume,
            dollar_volume=dollar_volume,
            spread_pct=spread_pct,
            exchange=exchange,
        )

    async def scan(
        self,
        symbols: list[str],
        prices: dict[str, float],
        volumes: dict[str, int],
        spreads: dict[str, float],
        exchanges: dict[str, str],
    ) -> ScanResult:
        """Scan all symbols and filter universe."""
        start = datetime.now(UTC)
        results: list[FilterResult] = []

        for symbol in symbols:
            price = prices.get(symbol, 0)
            volume = volumes.get(symbol)
            spread = spreads.get(symbol)
            exchange = exchanges.get(symbol)
            result = self.get_filter_result(
                symbol=symbol,
                price=price,
                volume=volume,
                spread_pct=spread,
                exchange=exchange,
            )
            results.append(result)

        eligible_count = sum(1 for r in results if r.eligible)
        end = datetime.now(UTC)
        duration_ms = int((end - start).total_seconds() * 1000)

        return ScanResult(
            timestamp=end,
            total_symbols=len(results),
            eligible_count=eligible_count,
            excluded_count=len(results) - eligible_count,
            results=results,
            duration_ms=duration_ms,
        )

    async def get_eligible_symbols(
        self,
        symbols: list[str],
        prices: dict[str, float],
        volumes: dict[str, int],
        spreads: dict[str, float],
        exchanges: dict[str, str],
    ) -> list[str]:
        """Get only eligible symbols."""
        scan = await self.scan(symbols, prices, volumes, spreads, exchanges)
        return [r.symbol for r in scan.results if r.eligible]

    def calculate_dollar_volume(self, price: float, volume: int) -> float:
        """Calculate dollar volume."""
        return price * volume
