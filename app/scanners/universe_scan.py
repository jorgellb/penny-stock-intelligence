"""Batched universe scan with an explicit request budget.

Pipeline: load candidates from securities master -> fetch quote + latest
daily volume per symbol (semaphore-limited, fail-soft, stops at budget) ->
UniverseEngine price/exchange/spread/volume filters. Dollar-volume uses
last price x latest daily volume.

The budget exists because a full 6k-symbol scan at 2 requests/symbol is
~12k provider calls: callers must pass max_symbols explicitly (no silent
full scans). Symbols without a quote are excluded with reason
`no_quote` (never assumed eligible).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.core.logging import get_logger
from app.scanners.universe import FilterResult, UniverseEngine

log = get_logger(__name__)


async def load_candidates(
    session: Any,
    exchanges: list[str] | None = None,
    exclude_etfs: bool = True,
    limit: int = 200,
    after_symbol: str | None = None,
) -> list[dict[str, Any]]:
    """Active securities from master, rotated by optional cursor (after_symbol)."""
    from app.models import Securities

    q = select(Securities).where(Securities.is_active.is_(True))  # noqa: E712
    if exchanges:
        upper = [e.upper() for e in exchanges]
        q = q.where(Securities.exchange.in_(upper))
    if exclude_etfs:
        q = q.where(Securities.is_etf.is_(False))  # noqa: E712
    if after_symbol:
        q = q.where(Securities.symbol > after_symbol.upper())
    q = q.order_by(Securities.symbol).limit(max(1, limit))
    res = await session.execute(q)
    rows = []
    for s in res.scalars().all():
        exch = getattr(s.exchange, "value", s.exchange)
        rows.append({"symbol": s.symbol, "exchange": str(exch), "name": s.name})
    # Wrap-around when cursor past end: fill from the start.
    if after_symbol and len(rows) < limit:
        q2 = select(Securities).where(Securities.is_active.is_(True))  # noqa: E712
        if exchanges:
            q2 = q2.where(Securities.exchange.in_([e.upper() for e in exchanges]))
        if exclude_etfs:
            q2 = q2.where(Securities.is_etf.is_(False))  # noqa: E712
        q2 = q2.order_by(Securities.symbol).limit(max(1, limit - len(rows)))
        res2 = await session.execute(q2)
        seen = {r["symbol"] for r in rows}
        for s in res2.scalars().all():
            if s.symbol in seen:
                continue
            exch = getattr(s.exchange, "value", s.exchange)
            rows.append({"symbol": s.symbol, "exchange": str(exch), "name": s.name})
            if len(rows) >= limit:
                break
    return rows


async def fetch_market(
    provider: Any,
    symbols: list[str],
    max_concurrent: int = 5,
    budget: int = 400,
) -> tuple[dict[str, Any], dict[str, int]]:
    """Quote + latest daily volume per symbol until the request budget runs out."""
    sem = asyncio.Semaphore(max(1, max_concurrent))
    quotes: dict[str, Any] = {}
    spent = 0
    failed = 0
    start = datetime.now(UTC) - timedelta(days=10)

    async def _one(sym: str) -> None:
        nonlocal spent, failed
        async with sem:
            if spent >= budget:
                return
            try:
                quote = await provider.get_quote(sym)
                spent += 1
                volume: int | None = None
                if spent < budget:
                    try:
                        bars = await provider.get_daily_bars(sym, start=start)
                        spent += 1
                        if bars:
                            volume = int(bars[-1].volume)
                    except Exception:
                        volume = None
                price = quote.last or quote.mid
                quotes[sym] = {
                    "price": float(price) if price else 0.0,
                    "spread_pct": quote.spread_pct,
                    "volume": volume,
                }
            except Exception as exc:
                failed += 1
                log.error("universe_fetch_failed", symbol=sym, error=str(exc))

    await asyncio.gather(*(_one(s) for s in symbols))
    stats = {
        "requested": len(symbols),
        "fetched": len(quotes),
        "failed": failed,
        "spent": spent,
        "budget": budget,
        "budget_hit": spent >= budget,
    }
    return quotes, stats


async def scan_universe(
    session: Any,
    provider: Any,
    exchanges: list[str] | None = None,
    limit: int = 200,
    max_concurrent: int = 5,
    budget: int = 400,
    min_price: float | None = None,
    max_price: float | None = None,
    after_symbol: str | None = None,
) -> dict[str, Any]:
    """Full pipeline returning eligible rows with explicit reasons."""
    from app.config import get_settings

    settings = get_settings()
    engine = UniverseEngine(market_data_provider=provider)
    if min_price is not None:
        engine.universe_config.min_price = min_price
    if max_price is not None:
        engine.universe_config.max_price = max_price
    t0 = datetime.now(UTC)
    cands = await load_candidates(
        session,
        exchanges=exchanges or settings.universe.exchanges,
        exclude_etfs=settings.universe.exclude_etfs,
        limit=limit,
        after_symbol=after_symbol,
    )
    symbols = [c["symbol"] for c in cands]
    by_exch = {c["symbol"]: c["exchange"] for c in cands}
    market, stats = await fetch_market(provider, symbols, max_concurrent, budget)
    results: list[FilterResult] = []
    for sym in symbols:
        m = market.get(sym)
        if m is None:
            results.append(
                FilterResult(
                    symbol=sym, eligible=False, reasons=["no_quote"], exchange=by_exch.get(sym)
                )
            )
            continue
        r = engine.get_filter_result(
            symbol=sym,
            price=m["price"],
            volume=m["volume"],
            spread_pct=m["spread_pct"],
            exchange=by_exch.get(sym),
        )
        if m["volume"] is None:
            r.reasons.append("volume_unknown")
        results.append(r)
    eligible = [r for r in results if r.eligible]
    # Prefer liquid names when callers seed radar / discovery.
    eligible.sort(key=lambda r: float(r.dollar_volume or 0), reverse=True)
    cursor = symbols[-1] if symbols else after_symbol
    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "duration_ms": int((datetime.now(UTC) - t0).total_seconds() * 1000),
        "stats": stats,
        "total": len(results),
        "eligible_count": len(eligible),
        "next_after_symbol": cursor,
        "eligible": [
            {
                "symbol": r.symbol,
                "price": r.price,
                "volume": r.volume,
                "dollar_volume": r.dollar_volume,
                "spread_pct": r.spread_pct,
                "exchange": r.exchange,
            }
            for r in eligible
        ],
        "excluded": [{"symbol": r.symbol, "reasons": r.reasons} for r in results if not r.eligible],
    }
