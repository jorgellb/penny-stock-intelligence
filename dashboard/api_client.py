"""Thin async HTTP client for the dashboard (no streamlit dependency).

Every helper returns real API payloads or raises ApiOfflineError — the UI
must show an honest offline banner instead of zero-filled demo tables.
"""

from __future__ import annotations

from typing import Any

import httpx


class ApiOfflineError(RuntimeError):
    """Raised when the backend API cannot be reached."""


DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_TIMEOUT = 5.0


def make_client(
    base_url: str = DEFAULT_BASE_URL,
    timeout: float = DEFAULT_TIMEOUT,
    transport: httpx.AsyncBaseTransport | None = None,
    api_key: str | None = None,
) -> httpx.AsyncClient:
    import os

    key = api_key if api_key is not None else os.environ.get("API_KEY")
    headers: dict[str, str] = {}
    if key:
        headers["X-API-Key"] = key
    return httpx.AsyncClient(
        base_url=base_url, timeout=timeout, transport=transport, headers=headers
    )


async def _get(client: httpx.AsyncClient, path: str) -> Any:
    try:
        resp = await client.get(path)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        raise ApiOfflineError(f"GET {path}: {exc}") from exc


async def health(client: httpx.AsyncClient) -> dict:
    return await _get(client, "/health")


async def monitor_status(client: httpx.AsyncClient) -> dict:
    return await _get(client, "/api/v1/monitor/status")


async def monitor_events(client: httpx.AsyncClient, limit: int = 100) -> list[dict]:
    body = await _get(client, f"/api/v1/monitor/events?limit={limit}")
    return list(body.get("events", []))


async def monitor_config(client: httpx.AsyncClient) -> dict:
    return await _get(client, "/api/v1/monitor/config")


async def universe_scan(
    client: httpx.AsyncClient,
    limit: int = 50,
    min_price: float = 0.10,
    max_price: float = 5.00,
    exchange: str | None = None,
) -> dict:
    """Batched eligibility scan over the securities master (live quotes)."""
    params = f"limit={limit}&min_price={min_price}&max_price={max_price}"
    if exchange:
        params += f"&exchange={exchange}"
    return await _get(client, f"/api/v1/universe?{params}")


async def scanner_rankings(client: httpx.AsyncClient, kind: str = "intraday") -> dict:
    """Ranked monitor evaluations (run a monitor pass first)."""
    path = {
        "overall": "/api/v1/scanner",
        "premarket": "/api/v1/scanner/premarket",
        "intraday": "/api/v1/scanner/intraday",
    }.get(kind, "/api/v1/scanner/intraday")
    return await _get(client, path)


async def opportunities(client: httpx.AsyncClient, limit: int = 40) -> dict:
    return await _get(client, f"/api/v1/opportunities?limit={limit}")


async def opportunity_setups(client: httpx.AsyncClient) -> dict:
    return await _get(client, "/api/v1/opportunities/setups")


async def run_radar(client: httpx.AsyncClient) -> dict:
    try:
        resp = await client.post("/api/v1/opportunities/radar/run")
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        raise ApiOfflineError(f"POST opportunities/radar/run: {exc}") from exc


async def alerts_history(client: httpx.AsyncClient, limit: int = 50) -> dict:
    """Persisted alert history (buy/sell only)."""
    return await _get(client, f"/api/v1/alerts?limit={limit}")


async def send_test_alert(client: httpx.AsyncClient) -> dict:
    """Fire a test alert through configured providers."""
    try:
        resp = await client.post("/api/v1/alerts/test")
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        raise ApiOfflineError(f"POST alerts/test: {exc}") from exc


async def stock(client: httpx.AsyncClient, symbol: str) -> dict:
    """Full live snapshot for one symbol (pipeline + filings + fundamentals)."""
    return await _get(client, f"/api/v1/stocks/{symbol.strip().upper()}")


async def stock_history(client: httpx.AsyncClient, symbol: str, days: int = 120) -> dict:
    """Daily OHLCV bars for charting (empty list + note when unavailable)."""
    return await _get(client, f"/api/v1/stocks/{symbol.strip().upper()}/history?days={days}")


async def stock_intraday(client: httpx.AsyncClient, symbol: str, interval: str = "5m") -> dict:
    """Latest session intraday bars with running VWAP (extended hours included)."""
    return await _get(
        client, f"/api/v1/stocks/{symbol.strip().upper()}/intraday?interval={interval}"
    )


async def monitor_paper_trades(client: httpx.AsyncClient, limit: int = 100) -> dict:
    """Closed paper trades (persisted)."""
    return await _get(client, f"/api/v1/monitor/paper/trades?limit={limit}")


async def watchlists(client: httpx.AsyncClient, user_id: str = "default") -> list[dict]:
    body = await _get(client, f"/api/v1/watchlists?user_id={user_id}")
    items = body.get("lists", body.get("watchlists", []))
    return list(items)


async def watchlist_symbols(
    client: httpx.AsyncClient, name: str, user_id: str = "default"
) -> list[str]:
    body = await _get(client, f"/api/v1/watchlists/{name}?user_id={user_id}")
    if "symbols" in body:
        return list(body["symbols"])
    return [str(i.get("symbol", "")) for i in body.get("items", [])]


async def add_symbol(
    client: httpx.AsyncClient, name: str, symbol: str, user_id: str = "default"
) -> dict:
    try:
        resp = await client.post(
            f"/api/v1/watchlists/{name}/symbols?symbol={symbol}&user_id={user_id}"
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        raise ApiOfflineError(f"POST add {symbol}: {exc}") from exc


async def remove_symbol(
    client: httpx.AsyncClient, name: str, symbol: str, user_id: str = "default"
) -> dict:
    try:
        resp = await client.delete(f"/api/v1/watchlists/{name}/symbols/{symbol}?user_id={user_id}")
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        raise ApiOfflineError(f"DELETE {symbol}: {exc}") from exc


async def run_monitor_pass(
    client: httpx.AsyncClient, list_name: str = "default", user_id: str = "default"
) -> dict:
    try:
        resp = await client.post(f"/api/v1/monitor/run?list_name={list_name}&user_id={user_id}")
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        raise ApiOfflineError(f"POST monitor/run: {exc}") from exc


def events_for_symbol(events: list[dict], symbol: str) -> list[dict]:
    """Filter cached monitor events for one symbol (pure, unit-tested)."""
    sym = symbol.strip().upper()
    return [e for e in events if str(e.get("symbol", "")).upper() == sym]


async def run_backtest(
    client: httpx.AsyncClient,
    symbols: str,
    days: int = 120,
    min_rvol: float = 2.0,
    min_change_pct: float = 5.0,
    holding_days: int = 5,
    stop_pct: float = -8.0,
    target_pct: float | None = None,
    min_score: int = 0,
    entry: str = "next_open",
) -> dict:
    """Historical rvol-momentum bundle (informational, never a forecast)."""
    params: dict[str, object] = {
        "symbols": symbols,
        "days": days,
        "min_rvol": min_rvol,
        "min_change_pct": min_change_pct,
        "holding_days": holding_days,
        "stop_pct": stop_pct,
        "min_score": min_score,
        "entry": entry,
    }
    if target_pct:
        params["target_pct"] = target_pct
    try:
        resp = await client.post(
            "/api/v1/backtest/run",
            params=params,  # type: ignore[arg-type]
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        raise ApiOfflineError(f"POST backtest/run: {exc}") from exc
