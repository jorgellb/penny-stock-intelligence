"""Stock analysis endpoints (live monitor pipeline, fail-soft).

Every endpoint evaluates the symbol through MonitorService or reads its
caches. When an upstream provider is unconfigured/offline the field is
null with an explicit note — never zero-filled demo data.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.jobs.monitor import get_monitor_service

router = APIRouter()


def _service():  # type: ignore[no-untyped-def]
    return get_monitor_service()


def _bars_provider():  # type: ignore[no-untyped-def]
    """Market-data provider for OHLC history (indirection for tests)."""
    from app.providers.market_data import YFinanceMarketDataProvider

    return YFinanceMarketDataProvider()


async def _evaluate(symbol: str) -> tuple[Any, dict[str, Any]]:
    sym = symbol.strip().upper()
    if not sym:
        raise HTTPException(status_code=400, detail="empty symbol")
    try:
        result = await _service().evaluate_symbol(sym)
        return result  # type: ignore[no-any-return]
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"evaluation failed for {sym}: {exc}") from exc


async def _fundamentals(symbol: str) -> tuple[dict[str, Any] | None, str | None]:
    """Live fundamentals via yfinance (free); null + note when unavailable."""
    try:
        from app.providers.fundamentals import YFinanceFundamentalsProvider

        provider = YFinanceFundamentalsProvider()
        fund = await asyncio.wait_for(provider.get_fundamentals(symbol), timeout=12)
        if fund is None:
            return None, "no fundamentals published for this symbol"
        return {
            "market_cap": getattr(fund, "market_cap", None),
            "revenue_ttm": getattr(fund, "revenue_ttm", None),
            "net_income": getattr(fund, "net_income", None),
            "eps": getattr(fund, "eps", None),
            "cash": getattr(fund, "cash", None),
            "total_debt": getattr(fund, "total_debt", None),
            "shares_outstanding": getattr(fund, "shares_outstanding", None),
            "float_shares": getattr(fund, "float_shares", None),
        }, None
    except Exception as exc:
        return None, f"fundamentals unavailable: {exc}"


def _snapshot(symbol: str, event: Any, details: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "price": event.price,
        "action": event.action.value,
        "score": event.score,
        "change_pct": details.get("change_pct"),
        "rvol": details.get("rvol"),
        "rvol_source": details.get("rvol_source"),
        "dollar_volume": details.get("dollar_volume"),
        "vwap": details.get("vwap"),
        "vwap_distance_pct": details.get("vwap_distance_pct"),
        "risk_flags": details.get("risk_flags", []),
        "reasons": event.reasons,
        "stale": details.get("stale"),
        "score_breakdown": details.get("score_breakdown"),
        "halted": details.get("halted"),
        "dollar_rule": details.get("dollar_rule"),
        "dilution_frozen": details.get("dilution_frozen"),
        "vetoed": details.get("vetoed"),
        "kill_switch": details.get("kill_switch"),
        "feed": {
            "kind": details.get("feed_kind"),
            "lag_ms": details.get("feed_lag_ms"),
        },
        "setup": details.get("setup"),
        "matched_setups": details.get("matched_setups", []),
        "trade_plan": details.get("trade_plan"),
        "grade": details.get("grade"),
        "subscores": details.get("subscores"),
        "session": details.get("session"),
        "overextended": details.get("overextended"),
        "extension_reasons": details.get("extension_reasons", []),
        "float_rotation": details.get("float_rotation"),
        "evaluated_at": datetime.now(UTC).isoformat(),
    }


@router.get("/stocks/{symbol}")
async def get_stock(symbol: str) -> dict[str, Any]:
    """Full live snapshot: pipeline evaluation + filings + fundamentals."""
    sym = symbol.strip().upper()
    event, details = await _evaluate(sym)
    snap = _snapshot(sym, event, details)
    snap["technical"] = _technical(details)
    snap["catalyst"] = details.get("catalyst")
    snap["accumulation"] = details.get("accumulation")
    snap["donchian_gate"] = details.get("donchian_gate")
    snap["order_template"] = details.get("order_template")
    snap["filings"] = _filings(sym)
    fund, note = await _fundamentals(sym)
    snap["fundamentals"] = fund
    if note:
        snap["fundamentals_note"] = note
    news = _service().news
    snap["news"] = []
    if news.news_provider is None:
        snap["news_note"] = "news provider not configured"
    return snap


def _technical(details: dict[str, Any]) -> dict[str, Any]:
    return {
        "rvol": details.get("rvol"),
        "rvol_source": details.get("rvol_source"),
        "change_pct": details.get("change_pct"),
        "dollar_volume": details.get("dollar_volume"),
        "vwap": details.get("vwap"),
        "vwap_distance_pct": details.get("vwap_distance_pct"),
        "rsi_14": details.get("rsi_14"),
        "stoch_k": details.get("stoch_k"),
        "stoch_d": details.get("stoch_d"),
        "stoch_cross": details.get("stoch_cross"),
        "atr": details.get("atr"),
        "atr_pct": details.get("atr_pct"),
        "squeeze_active": details.get("squeeze_active"),
        "spread_pct": details.get("spread_pct"),
        "rsi_divergence": details.get("rsi_divergence"),
        "stoch_divergence": details.get("stoch_divergence"),
        "donchian_gate": details.get("donchian_gate"),
        "accumulation": details.get("accumulation"),
        "climax": details.get("climax"),
        "markup_ready": details.get("markup_ready"),
        "facts": details.get("technical_facts", {}),
        "technical_reasons": details.get("technical_reasons", []),
    }


@router.get("/stocks/{symbol}/technicals")
async def get_technicals(symbol: str) -> dict[str, Any]:
    """Technical indicators from a live evaluation."""
    sym = symbol.strip().upper()
    _, details = await _evaluate(sym)
    return {"symbol": sym, "indicators": _technical(details)}


@router.get("/stocks/{symbol}/fundamentals")
async def get_fundamentals(symbol: str) -> dict[str, Any]:
    """Fundamental data (live yfinance; null + note when unavailable)."""
    sym = symbol.strip().upper()
    if not sym:
        raise HTTPException(status_code=400, detail="empty symbol")
    fund, note = await _fundamentals(sym)
    out: dict[str, Any] = {"symbol": sym, "fundamentals": fund}
    if note:
        out["note"] = note
    return out


@router.get("/stocks/{symbol}/news")
async def get_news(
    symbol: str,
    limit: int = Query(20, ge=1, le=100),
    since: str | None = Query(None),
) -> dict[str, Any]:
    """Recent news (requires a configured news provider)."""
    sym = symbol.strip().upper()
    if _service().news.news_provider is None:
        return {"symbol": sym, "news": [], "note": "news provider not configured"}
    try:
        from datetime import datetime as _dt

        start = _dt.fromisoformat(since) if since else None
        result = await _service().news.ingest_news(symbols=[sym], start=start, limit=limit)
        return {
            "symbol": sym,
            "news": [
                {
                    "headline": a.headline,
                    "source": str(getattr(a, "source", "")),
                    "url": getattr(a, "url", None),
                    "published_at": a.published_at.isoformat()
                    if getattr(a, "published_at", None)
                    else None,
                }
                for a in result.articles
            ],
        }
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"news failed: {exc}") from exc


def _filings(symbol: str) -> dict[str, Any]:
    decision = _service().filings.get(symbol)
    if decision is None:
        return {"filings": [], "note": "no cached filings (sync_filings_fast warms this)"}
    return {
        "freeze_buys": decision.freeze_buys,
        "atm_active": decision.atm_active,
        "reasons": decision.reasons,
        "checked_at": decision.checked_at.isoformat(),
    }


@router.get("/stocks/{symbol}/filings")
async def get_filings(symbol: str) -> dict[str, Any]:
    """Cached SEC filings + dilution-freeze decision for the symbol."""
    sym = symbol.strip().upper()
    if not sym:
        raise HTTPException(status_code=400, detail="empty symbol")
    return {"symbol": sym, **_filings(sym)}


@router.get("/stocks/{symbol}/risks")
async def get_risks(symbol: str) -> dict[str, Any]:
    """Risk flags from a live evaluation."""
    sym = symbol.strip().upper()
    event, details = await _evaluate(sym)
    return {
        "symbol": sym,
        "risk_flags": details.get("risk_flags", []),
        "halted": details.get("halted"),
        "dollar_rule": details.get("dollar_rule"),
        "dilution_frozen": details.get("dilution_frozen"),
        "vetoed": details.get("vetoed"),
        "kill_switch": details.get("kill_switch"),
        "stale": details.get("stale"),
        "score": event.score,
    }


@router.get("/stocks/{symbol}/score")
async def get_score(symbol: str) -> dict[str, Any]:
    """Deterministic score with full explanation."""
    sym = symbol.strip().upper()
    event, details = await _evaluate(sym)
    return {
        "symbol": sym,
        "action": event.action.value,
        "score": event.score,
        "reasons": event.reasons,
        "score_breakdown": details.get("score_breakdown"),
        "disclaimer": "ranking metric, not a probability forecast",
        "evaluated_at": datetime.now(UTC).isoformat(),
    }


@router.get("/stocks/{symbol}/history")
async def get_history(
    symbol: str,
    days: int = Query(120, ge=5, le=730),
) -> dict[str, Any]:
    """Daily OHLCV bars (live provider; empty list + note when unavailable)."""
    sym = symbol.strip().upper()
    if not sym:
        raise HTTPException(status_code=400, detail="empty symbol")
    start = datetime.now(UTC) - timedelta(days=days)
    provider = _bars_provider()
    try:
        bars = await asyncio.wait_for(provider.get_daily_bars(sym, start=start), timeout=25)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"history failed: {exc}") from exc
    # Daily history is cached; rebuild today's candle from intraday bars so
    # the chart shows the live session (same merge the monitor uses).
    if bars and hasattr(provider, "get_bars"):
        try:
            from app.jobs.monitor.live import build_live_session

            intraday = await asyncio.wait_for(
                provider.get_bars(sym, "5m", start=datetime.now(UTC) - timedelta(days=5)),
                timeout=15,
            )
            bars = build_live_session(list(bars), list(intraday or []), 0.0).bars
        except Exception:
            pass  # fail-soft: plain daily history is still correct up to yesterday
    out = []
    for b in bars or []:
        out.append(
            {
                "date": b.date.isoformat() if getattr(b, "date", None) is not None else None,
                "open": float(b.open),
                "high": float(b.high),
                "low": float(b.low),
                "close": float(b.close),
                "volume": int(b.volume),
            }
        )
    body: dict[str, Any] = {"symbol": sym, "days": days, "count": len(out), "bars": out}
    if not out:
        body["note"] = "no history available for this symbol/window"
    return body


@router.get("/stocks/{symbol}/intraday")
async def get_intraday(
    symbol: str,
    interval: str = Query("5m", pattern="^(1m|5m|15m)$"),
) -> dict[str, Any]:
    """Latest session intraday bars (incl. extended hours) + running VWAP."""
    from app.core.market_calendar import group_by_et_day
    from app.jobs.monitor.live import _is_regular

    sym = symbol.strip().upper()
    if not sym:
        raise HTTPException(status_code=400, detail="empty symbol")
    try:
        bars = await asyncio.wait_for(
            _bars_provider().get_bars(sym, interval, start=datetime.now(UTC) - timedelta(days=5)),
            timeout=25,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"intraday failed: {exc}") from exc
    by_day = group_by_et_day(list(bars or []))
    if not by_day:
        return {"symbol": sym, "interval": interval, "bars": [], "note": "no intraday data"}
    day = max(by_day)
    out: list[dict[str, Any]] = []
    num = den = 0.0
    for b in by_day[day]:
        regular = _is_regular(b.timestamp)
        vol = float(b.volume or 0)
        if regular and vol > 0:
            num += (float(b.high) + float(b.low) + float(b.close)) / 3 * vol
            den += vol
        out.append(
            {
                "ts": b.timestamp.isoformat(),
                "open": float(b.open),
                "high": float(b.high),
                "low": float(b.low),
                "close": float(b.close),
                "volume": int(b.volume),
                "regular": regular,
                "vwap": round(num / den, 6) if den > 0 else None,
            }
        )
    return {"symbol": sym, "interval": interval, "session": day.isoformat(), "bars": out}


@router.get("/universe")
async def get_universe(
    exchange: str | None = Query(None),
    min_price: float = Query(0.10, ge=0.01),
    max_price: float = Query(5.00, ge=0.01),
    min_volume: int = Query(500000, ge=0),
    min_dollar_volume: float = Query(1000000.0, ge=0),
    min_score: int = Query(70, ge=0, le=100),
    limit: int = Query(200, ge=1, le=2000),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Batched eligibility scan over the securities master.

    Fetches quotes (+latest daily volume) with an explicit request
    budget: 2 requests/symbol, capped by `limit`. Full 6k scans need
    repeated calls, not one giant request.
    """
    from app.providers.market_data import YFinanceMarketDataProvider
    from app.scanners.universe_scan import scan_universe

    _ = (min_volume, min_dollar_volume, min_score)  # device-level knobs live in config
    try:
        return await scan_universe(
            session,
            YFinanceMarketDataProvider(),
            exchanges=[exchange] if exchange else None,
            limit=limit,
            min_price=min_price,
            max_price=max_price,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"universe scan failed: {exc}") from exc
