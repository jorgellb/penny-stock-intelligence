"""Feed adapters: SIP (retail reality) vs Direct (institutional future).

Retail cannot afford co-location/TotalView, so the architecture is a
`FeedAdapter` protocol with two implementations:
- SipFeed (MVP): wraps any MarketDataProvider, tags quotes/bars with
  feed="SIP", listing-exchange-only policy note, and measured fetch
  latency as a lag proxy. No-open-SIP-bars policy enforced by callers.
- DirectFeed (future): raises NotConfiguredError until a TotalView/
  OpenBook entitlement exists. No code path may assume it silently.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Protocol

from app.domain.models import Bar, DailyBar, Quote


class NotConfiguredError(RuntimeError):
    """Raised when the direct feed has no entitlement configured."""


class FeedAdapter(Protocol):
    kind: str

    async def get_quote(self, symbol: str) -> Quote: ...
    async def get_daily_bars(self, symbol: str, start: datetime) -> list[DailyBar]: ...
    async def get_bars(self, symbol: str, timeframe: str, start: datetime) -> list[Bar]: ...


class SipFeed:
    """Consolidated SIP feed over a polling market-data provider."""

    kind = "SIP"
    listing_exchange_only_open: bool = True

    def __init__(self, provider: Any, max_fetch_lag_ms: int = 1500) -> None:
        self.provider = provider
        self.max_fetch_lag_ms = max_fetch_lag_ms
        self.last_lag_ms: float = 0.0

    async def _timed(self, coro: Any) -> Any:
        t0 = time.perf_counter()
        try:
            return await coro
        finally:
            self.last_lag_ms = (time.perf_counter() - t0) * 1000

    async def get_quote(self, symbol: str) -> Quote:
        return await self._timed(self.provider.get_quote(symbol))  # type: ignore[no-any-return]

    async def get_daily_bars(self, symbol: str, start: datetime) -> list[DailyBar]:
        return await self._timed(  # type: ignore[no-any-return]
            self.provider.get_daily_bars(symbol, start=start)
        )

    async def get_bars(self, symbol: str, timeframe: str, start: datetime) -> list[Bar]:
        if hasattr(self.provider, "get_bars"):
            return await self._timed(  # type: ignore[no-any-return]
                self.provider.get_bars(symbol, timeframe, start)
            )
        return []

    def lag_ok(self) -> bool:
        return self.last_lag_ms <= self.max_fetch_lag_ms


class DirectFeed:
    """NASDAQ TotalView / NYSE OpenBook placeholder (no entitlement)."""

    kind = "DIRECT"

    def __init__(self, entitlement: str | None = None) -> None:
        self.entitlement = entitlement

    def _guard(self) -> None:
        if not self.entitlement:
            raise NotConfiguredError(
                "direct feed sin entitlement (TotalView/OpenBook): configure credenciales"
            )

    async def get_quote(self, symbol: str) -> Quote:
        self._guard()
        raise NotImplementedError("direct feed wiring pendiente de entitlement")

    async def get_daily_bars(self, symbol: str, start: datetime) -> list[DailyBar]:
        self._guard()
        raise NotImplementedError("direct feed wiring pendiente de entitlement")

    async def get_bars(self, symbol: str, timeframe: str, start: datetime) -> list[Bar]:
        self._guard()
        raise NotImplementedError("direct feed wiring pendiente de entitlement")
