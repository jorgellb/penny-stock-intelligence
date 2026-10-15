"""Fast SEC filings sync: DilutionFreeze live for monitored lists.

`FilingsCache` polls recent filings per symbol with a TTL (default 5 min,
respecting SEC rate limits) and keeps the `DilutionFreeze` decision ready
for the monitor. `sync_filings_fast` is the scheduler job: it refreshes
every symbol found in any watchlist.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.core.database import get_db_manager
from app.core.logging import get_logger
from app.domain.models import Filing
from app.risk.freeze import DilutionFreeze, FreezeDecision

log = get_logger(__name__)


@dataclass
class CachedFilings:
    symbol: str
    filings: list[Filing] = field(default_factory=list)
    decision: FreezeDecision | None = None
    fetched_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class FilingsCache:
    """TTL cache of recent filings + freeze decisions per symbol."""

    def __init__(
        self,
        sec_provider: Any | None = None,
        ttl_seconds: int = 300,
        hours: int = 48,
    ) -> None:
        self.sec = sec_provider
        self.ttl_seconds = ttl_seconds
        self.hours = hours
        self.freeze = DilutionFreeze()
        self._cache: dict[str, CachedFilings] = {}

    def _fresh(self, symbol: str, now: datetime) -> bool:
        entry = self._cache.get(symbol.upper())
        if entry is None:
            return False
        return (now - entry.fetched_at).total_seconds() < self.ttl_seconds

    async def refresh(self, symbols: list[str]) -> dict[str, FreezeDecision]:
        """Fetch stale symbols only; returns decisions for all requested."""
        now = datetime.now(UTC)
        out: dict[str, FreezeDecision] = {}
        for symbol in dict.fromkeys(s.upper() for s in symbols):
            if self._fresh(symbol, now):
                entry = self._cache[symbol]
                if entry.decision is not None:
                    out[symbol] = entry.decision
                continue
            filings: list[Filing] = []
            if self.sec is not None:
                try:
                    filings = await self.sec.get_recent_filings([symbol], hours=self.hours)
                except Exception as exc:
                    log.error("filings_refresh_failed", symbol=symbol, error=str(exc))
            decision = self.freeze.evaluate(symbol, filings, now=now)
            self._cache[symbol] = CachedFilings(
                symbol=symbol, filings=filings, decision=decision, fetched_at=now
            )
            out[symbol] = decision
        return out

    def get(self, symbol: str) -> FreezeDecision | None:
        entry = self._cache.get(symbol.upper())
        if entry is None:
            return None
        if (datetime.now(UTC) - entry.fetched_at).total_seconds() >= self.ttl_seconds:
            return None
        return entry.decision

    def frozen_symbols(self) -> list[str]:
        now = datetime.now(UTC)
        return [
            sym
            for sym, entry in self._cache.items()
            if (now - entry.fetched_at).total_seconds() < self.ttl_seconds
            and entry.decision is not None
            and entry.decision.freeze_buys
        ]


_cache: FilingsCache | None = None


def get_filings_cache() -> FilingsCache:
    """Shared singleton: the scheduler job warms it, the monitor reads it."""
    global _cache
    if _cache is None:
        _cache = FilingsCache()
    return _cache


async def all_watchlist_symbols() -> list[str]:
    """Every symbol in every list (all users)."""
    from app.repositories import WatchlistRepository

    db = get_db_manager()
    seen: list[str] = []
    async with db.session() as session:
        repo = WatchlistRepository(session)
        for user_id in await repo.user_ids():
            for lst in await repo.lists(user_id):
                for sym in await repo.symbols(user_id, str(lst["name"])):
                    if sym not in seen:
                        seen.append(sym)
    return seen


async def sync_lists(hours: int = 48, job: str = "sync_filings_fast") -> dict[str, Any]:
    """Refresh filings for all watchlisted symbols. Returns a summary.

    `hours` tunes the lookback window (fast job: 48h; backfill: 720h).
    The shared cache window follows the caller (documented side effect).
    """
    from app.providers.sec import SecEdgarProvider

    cache = get_filings_cache()
    if cache.sec is None:
        cache.sec = SecEdgarProvider()
    cache.hours = hours
    symbols = await all_watchlist_symbols()
    decisions = await cache.refresh(symbols)
    frozen = [s for s, d in decisions.items() if d.freeze_buys]
    log.info("filings_completed", job=job, symbols=len(symbols), frozen=len(frozen))
    return {
        "job": job,
        "at": datetime.now(UTC).isoformat(),
        "symbols": len(symbols),
        "frozen": frozen,
        "hours": hours,
    }
