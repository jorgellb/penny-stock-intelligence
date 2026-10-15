"""
Market data provider implementations.
"""

import asyncio
import time
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


class _TTLCache:
    """Tiny in-process TTL cache (per provider instance, no external deps)."""

    def __init__(self, max_items: int = 2048) -> None:
        self._data: dict[Any, tuple[float, Any]] = {}
        self._max = max_items

    def get(self, key: Any, ttl: float) -> Any | None:
        hit = self._data.get(key)
        if hit is None:
            return None
        ts, value = hit
        if time.monotonic() - ts > ttl:
            self._data.pop(key, None)
            return None
        return value

    def put(self, key: Any, value: Any) -> None:
        if len(self._data) >= self._max:
            # Drop the oldest ~10% to stay bounded.
            for k, _ in sorted(self._data.items(), key=lambda kv: kv[1][0])[: self._max // 10]:
                self._data.pop(k, None)
        self._data[key] = (time.monotonic(), value)


_INTERVALS = {
    "1m": "1m",
    "2m": "2m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "60m": "60m",
    "1h": "60m",
}


def _cache_ttls() -> tuple[float, float, float]:
    """(quote, intraday, daily) TTLs from config, with safe fallbacks."""
    try:
        from app.config import get_settings

        ttl = get_settings().providers.market_data.cache_ttl_seconds
        return float(ttl.quotes), float(ttl.bars), float(ttl.daily_bars)
    except Exception:
        return 5.0, 60.0, 3600.0


class YFinanceMarketDataProvider(BaseMarketDataProvider):
    """Yahoo Finance market data provider (free).

    yfinance is synchronous: every call runs in a worker thread so the
    monitor's concurrent evaluation is real concurrency, not a queue.
    Intraday data includes extended hours (premarket gappers matter).
    Responses are TTL-cached: daily history barely changes intraday and
    the live session bar is rebuilt from intraday bars by the monitor.
    """

    def __init__(self) -> None:
        self._cache = _TTLCache()

    @property
    def name(self) -> DataProvider:
        return DataProvider.YFINANCE

    @property
    def rate_limit_per_minute(self) -> int:
        return 60

    async def health_check(self) -> bool:
        try:
            import yfinance

            hist = await asyncio.to_thread(lambda: yfinance.Ticker("AAPL").history(period="1d"))
            return not hist.empty
        except Exception:
            return False

    async def get_quote(self, symbol: str) -> Quote:
        import yfinance

        quote_ttl, _, _ = _cache_ttls()
        cached = self._cache.get(("quote", symbol), quote_ttl)
        if cached is not None:
            return cached  # type: ignore[no-any-return]

        def _fetch() -> Any:
            return yfinance.Ticker(symbol).history(period="1d", interval="1m", prepost=True)

        try:
            hist = await asyncio.to_thread(_fetch)
            if hist.empty:
                return Quote(symbol=symbol, timestamp=datetime.now(UTC), provider=self.name)
            last_row = hist.iloc[-1]
            last = Decimal(str(round(float(last_row.get("Close", 0)), 4)))
            # yfinance has no NBBO: leave bid/ask empty so spread is "unknown"
            # instead of a fake 0% that would pass every liquidity gate.
            quote = Quote(
                symbol=symbol,
                last=last,
                last_size=int(last_row.get("Volume", 0) or 0),
                timestamp=datetime.now(UTC),
                provider=self.name,
            )
            self._cache.put(("quote", symbol), quote)
            return quote
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

        interval = _INTERVALS.get(timeframe, "5m")
        _, bars_ttl, _ = _cache_ttls()
        days = max(1, (datetime.now(UTC) - start).days + 1)
        period = "1d" if days <= 1 else ("5d" if days <= 5 else ("1mo" if days <= 30 else "60d"))
        if interval == "1m" and period not in {"1d", "5d"}:
            period = "5d"
        key = ("bars", symbol, interval, period)
        bars: list[Bar] | None = self._cache.get(key, bars_ttl)
        if bars is None:

            def _fetch() -> Any:
                return yfinance.Ticker(symbol).history(
                    period=period, interval=interval, prepost=True
                )

            try:
                hist = await asyncio.to_thread(_fetch)
            except Exception:
                return []
            bars = []
            for idx, row in hist.iterrows():
                ts = idx.to_pydatetime() if hasattr(idx, "to_pydatetime") else idx
                try:
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
                            timeframe=interval,
                        )
                    )
                except Exception:
                    continue  # skip NaN rows yfinance emits around halts
            self._cache.put(key, bars)
        out = list(bars)
        if limit:
            out = out[-limit:]
        return out

    async def get_daily_bars(
        self,
        symbol: str,
        start: datetime,
        end: datetime | None = None,
        limit: int | None = None,
        adjusted: bool = True,
    ) -> list[DailyBar]:
        import yfinance

        _, _, daily_ttl = _cache_ttls()
        key = (
            "daily",
            symbol,
            start.date().isoformat(),
            end.date().isoformat() if end else None,
            adjusted,
        )
        bars: list[DailyBar] | None = self._cache.get(key, daily_ttl)
        if bars is None:

            def _fetch() -> Any:
                return yfinance.Ticker(symbol).history(start=start, end=end, auto_adjust=adjusted)

            try:
                hist = await asyncio.to_thread(_fetch)
            except Exception:
                return []
            bars = []
            for idx, row in hist.iterrows():
                try:
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
                except Exception:
                    continue
            self._cache.put(key, bars)
        out = list(bars)
        if limit:
            out = out[-limit:]
        return out

    async def get_universe(
        self,
        min_price: float,
        max_price: float,
        exchanges: list[Exchange],
        include_otc: bool = False,
    ) -> list[Security]:
        # Universe comes from the Nasdaq Trader directory (see nasdaq_listings).
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
