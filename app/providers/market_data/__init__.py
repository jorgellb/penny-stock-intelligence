"""
Market data provider implementations.
"""

from abc import ABC, abstractmethod
from datetime import UTC, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from app.domain.models import (
    Bar,
    DailyBar,
    DataProvider,
    Exchange,
    Quote,
    Security,
)
from app.providers import MarketDataProvider as ProviderProtocol


class BaseMarketDataProvider(ABC):
    """Base class for market data providers."""

    @property
    @abstractmethod
    def name(self) -> DataProvider: ...

    @property
    @abstractmethod
    def rate_limit_per_minute(self) -> int: ...

    @abstractmethod
    async def health_check(self) -> bool: ...

    async def get_quote(self, symbol: str) -> Quote:
        raise NotImplementedError

    async def get_quotes(self, symbols: list[str]) -> dict[str, Quote]:
        raise NotImplementedError

    async def get_bars(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime | None = None,
        limit: int | None = None,
    ) -> list[Bar]:
        raise NotImplementedError

    async def get_daily_bars(
        self,
        symbol: str,
        start: datetime,
        end: datetime | None = None,
        limit: int | None = None,
        adjusted: bool = True,
    ) -> list[DailyBar]:
        raise NotImplementedError

    async def search_symbols(
        self,
        query: str,
        exchanges: list[Exchange] | None = None,
    ) -> list[Security]:
        raise NotImplementedError

    async def get_universe(
        self,
        min_price: float,
        max_price: float,
        exchanges: list[Exchange],
        include_otc: bool = False,
    ) -> list[Security]:
        raise NotImplementedError

    async def get_latest_bar(self, symbol: str, timeframe: str) -> Bar | None:
        raise NotImplementedError


class YFinanceMarketDataProvider(BaseMarketDataProvider):
    """Yahoo Finance market data provider (free)."""

    @property
    def name(self) -> DataProvider:
        return DataProvider.YFINANCE

    @property
    def rate_limit_per_minute(self) -> int:
        return 60

    async def health_check(self) -> bool:
        try:
            import yfinance  # type: ignore[import-not-found]

            ticker = yfinance.Ticker("AAPL")
            _ = ticker.history(period="1d")
            return True
        except Exception:
            return False

    async def get_quote(self, symbol: str) -> Quote:
        import yfinance

        try:
            ticker = yfinance.Ticker(symbol)
            hist = ticker.history(period="1d", interval="1m")
            if hist.empty:
                return Quote(symbol=symbol, timestamp=datetime.now(UTC), provider=self.name)
            last_row = hist.iloc[-1]
            return Quote(
                symbol=symbol,
                bid=Decimal(str(last_row.get("Close", 0))),
                ask=Decimal(str(last_row.get("Close", 0))),
                last=Decimal(str(last_row.get("Close", 0))),
                timestamp=datetime.now(UTC),
                provider=self.name,
            )
        except Exception:
            return Quote(symbol=symbol, timestamp=datetime.now(UTC), provider=self.name)

    async def get_bars(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime | None = None,
        limit: int | None = None,
    ) -> list[Bar]:
        import yfinance

        try:
            ticker = yfinance.Ticker(symbol)
            hist = ticker.history(period="5d", interval="5m")
            bars = []
            for idx, row in hist.iterrows():
                ts = idx.to_pydatetime() if hasattr(idx, "to_pydatetime") else idx
                bars.append(
                    Bar(
                        symbol=symbol,
                        timestamp=ts,
                        open=Decimal(str(row["Open"])),
                        high=Decimal(str(row["High"])),
                        low=Decimal(str(row["Low"])),
                        close=Decimal(str(row["Close"])),
                        volume=int(row["Volume"]),
                        provider=self.name,
                        timeframe="5m",
                    )
                )
            if limit:
                bars = bars[-limit:]
            return bars
        except Exception:
            return []

    async def get_daily_bars(
        self,
        symbol: str,
        start: datetime,
        end: datetime | None = None,
        limit: int | None = None,
        adjusted: bool = True,
    ) -> list[DailyBar]:
        import yfinance

        try:
            ticker = yfinance.Ticker(symbol)
            hist = ticker.history(start=start, end=end, auto_adjust=adjusted)
            bars = []
            for idx, row in hist.iterrows():
                bars.append(
                    DailyBar(
                        symbol=symbol,
                        date=idx,
                        open=Decimal(str(row["Open"])),
                        high=Decimal(str(row["High"])),
                        low=Decimal(str(row["Low"])),
                        close=Decimal(str(row["Close"])),
                        volume=int(row["Volume"]),
                        provider=self.name,
                    )
                )
            return bars
        except Exception:
            return []

    async def get_universe(
        self,
        min_price: float,
        max_price: float,
        exchanges: list[Exchange],
        include_otc: bool = False,
    ) -> list[Security]:
        # Stub implementation - uses yfinance for symbol lookup
        return []


class MockMarketDataProvider(BaseMarketDataProvider):
    """Mock market data provider for testing."""

    def __init__(self) -> None:
        self._quotes: dict[str, Quote] = {}
        self._daily_bars: dict[str, list[DailyBar]] = {}

    @property
    def name(self) -> DataProvider:
        return DataProvider.YFINANCE

    @property
    def rate_limit_per_minute(self) -> int:
        return 9999

    async def health_check(self) -> bool:
        return True

    async def get_quote(self, symbol: str) -> Quote:
        if symbol not in self._quotes:
            import random

            price = random.uniform(0.5, 5.0)
            self._quotes[symbol] = Quote(
                symbol=symbol,
                bid=Decimal(str(price - 0.01)),
                ask=Decimal(str(price + 0.01)),
                last=Decimal(str(price)),
                timestamp=datetime.now(UTC),
                provider=self.name,
            )
        return self._quotes[symbol]

    async def get_daily_bars(
        self,
        symbol: str,
        start: datetime,
        end: datetime | None = None,
        limit: int | None = None,
        adjusted: bool = True,
    ) -> list[DailyBar]:
        if symbol not in self._daily_bars:
            import random

            bars = []
            price = random.uniform(1.0, 5.0)
            for i in range(30):
                day = start + __import__("datetime").timedelta(days=i)
                open_p = price
                high_p = price * (1 + random.uniform(0, 0.1))
                low_p = price * (1 - random.uniform(0, 0.1))
                close_p = price * (1 + random.uniform(-0.05, 0.05))
                volume = random.randint(100000, 5000000)
                bars.append(
                    DailyBar(
                        symbol=symbol,
                        date=day,
                        open=Decimal(str(open_p)),
                        high=Decimal(str(high_p)),
                        low=Decimal(str(low_p)),
                        close=Decimal(str(close_p)),
                        volume=volume,
                        provider=self.name,
                    )
                )
                price = close_p
            self._daily_bars[symbol] = bars
        return self._daily_bars[symbol]

    async def get_universe(
        self,
        min_price: float,
        max_price: float,
        exchanges: list[Exchange],
        include_otc: bool = False,
    ) -> list[Security]:
        return []

    def set_quote(self, symbol: str, price: float) -> None:
        """Set a mock quote for testing."""
        from decimal import Decimal

        px = Decimal(str(price))
        self._quotes[symbol] = Quote(
            symbol=symbol,
            bid=px - Decimal("0.01"),
            ask=px + Decimal("0.01"),
            last=px,
            timestamp=datetime.now(UTC),
            provider=self.name,
        )

    def set_daily_bars(self, symbol: str, bars: list[DailyBar]) -> None:
        """Set mock daily bars for testing."""
        self._daily_bars[symbol] = bars

    async def get_bars(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime | None = None,
        limit: int | None = None,
    ) -> list[Bar]:
        """Deterministic mock intraday bars (seeded by symbol)."""
        import random
        from datetime import timedelta

        rng = random.Random(f"{symbol}:{timeframe}")
        bars = []
        price = 2.0
        days = 5
        per_day = 30
        for d in range(days):
            day = (start + timedelta(days=d)).replace(hour=13, minute=30, second=0, microsecond=0)
            for i in range(per_day):
                ts = day + timedelta(minutes=5 * i)
                open_p = price
                high_p = price * (1 + rng.uniform(0, 0.01))
                low_p = price * (1 - rng.uniform(0, 0.01))
                close_p = price * (1 + rng.uniform(-0.005, 0.005))
                bars.append(
                    Bar(
                        symbol=symbol,
                        timestamp=ts,
                        open=Decimal(str(round(open_p, 4))),
                        high=Decimal(str(round(high_p, 4))),
                        low=Decimal(str(round(low_p, 4))),
                        close=Decimal(str(round(close_p, 4))),
                        volume=rng.randint(10_000, 100_000),
                        provider=self.name,
                        timeframe=timeframe,
                    )
                )
                price = close_p
        if limit:
            bars = bars[-limit:]
        return bars
