"""Unit: dashboard api_client shapes + offline honesty + symbol filter."""

import httpx
import pytest

from dashboard.api_client import (
    ApiOfflineError,
    add_symbol,
    events_for_symbol,
    health,
    make_client,
    monitor_events,
    remove_symbol,
    run_backtest,
    run_monitor_pass,
    watchlist_symbols,
    watchlists,
)


def _client(handler) -> httpx.AsyncClient:  # type: ignore[no-untyped-def]
    return make_client(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_health_ok() -> None:
    def _h(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/health"
        return httpx.Response(200, json={"status": "healthy"})

    assert (await health(_client(_h)))["status"] == "healthy"


@pytest.mark.asyncio
async def test_offline_raises_for_all_reads() -> None:
    def _boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    c = _client(_boom)
    for coro in (health(c), monitor_events(c), watchlists(c), watchlist_symbols(c, "x")):
        with pytest.raises(ApiOfflineError):
            await coro


@pytest.mark.asyncio
async def test_monitor_events_and_run_shapes() -> None:
    def _h(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/monitor/events":
            return httpx.Response(200, json={"events": [{"symbol": "ABCD"}], "count": 1})
        if request.url.path == "/api/v1/monitor/run":
            return httpx.Response(200, json={"list": "default", "signals": []})
        raise AssertionError(request.url.path)

    c = _client(_h)
    assert await monitor_events(c) == [{"symbol": "ABCD"}]
    assert (await run_monitor_pass(c))["signals"] == []


@pytest.mark.asyncio
async def test_watchlist_shapes() -> None:
    def _h(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/watchlists":
            return httpx.Response(200, json={"lists": [{"name": "bio", "count": 2}]})
        if request.url.path == "/api/v1/watchlists/bio":
            return httpx.Response(200, json={"items": [{"symbol": "ABCD"}, {"symbol": "EFGH"}]})
        if request.method == "POST":
            return httpx.Response(200, json={"status": "added"})
        if request.method == "DELETE":
            return httpx.Response(200, json={"status": "removed"})
        raise AssertionError(request.url.path)

    c = _client(_h)
    assert await watchlists(c) == [{"name": "bio", "count": 2}]
    assert await watchlist_symbols(c, "bio") == ["ABCD", "EFGH"]
    assert (await add_symbol(c, "bio", "ABCD"))["status"] == "added"
    assert (await remove_symbol(c, "bio", "ABCD"))["status"] == "removed"


def test_events_for_symbol_filter() -> None:
    events = [{"symbol": "abcd", "action": "buy"}, {"symbol": "EFGH", "action": "hold"}]
    assert events_for_symbol(events, "ABCD") == [{"symbol": "abcd", "action": "buy"}]
    assert events_for_symbol(events, "zzz") == []
    assert events_for_symbol(events, "  efgh ") == [{"symbol": "EFGH", "action": "hold"}]


@pytest.mark.asyncio
async def test_run_backtest_shape_and_params() -> None:
    seen: dict = {}

    def _h(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        assert request.url.path == "/api/v1/backtest/run"
        return httpx.Response(
            200,
            json={"metrics": {"number_of_signals": 2.0}, "trades": [], "walk_forward": {}},
        )

    out = await run_backtest(_client(_h), "ABCD,EFGH", days=60)
    assert out["metrics"]["number_of_signals"] == 2.0
    assert seen["symbols"] == "ABCD,EFGH" and seen["days"] == "60"


@pytest.mark.asyncio
async def test_run_backtest_offline() -> None:
    def _boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    with pytest.raises(ApiOfflineError):
        await run_backtest(_client(_boom), "ABCD")


@pytest.mark.asyncio
async def test_stock_and_history_shapes() -> None:
    from dashboard.api_client import stock, stock_history

    def _h(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/stocks/ABCD":
            return httpx.Response(200, json={"symbol": "ABCD", "score": 78})
        if request.url.path == "/api/v1/stocks/ABCD/history":
            assert dict(request.url.params)["days"] == "30"
            return httpx.Response(200, json={"symbol": "ABCD", "count": 0, "bars": []})
        raise AssertionError(request.url.path)

    c = _client(_h)
    assert (await stock(c, "abcd"))["score"] == 78
    assert (await stock_history(c, "ABCD", days=30))["bars"] == []


@pytest.mark.asyncio
async def test_rankings_alerts_and_universe_shapes() -> None:
    from dashboard.api_client import (
        alerts_history,
        scanner_rankings,
        send_test_alert,
        universe_scan,
    )

    def _h(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/universe":
            assert dict(request.url.params)["limit"] == "50"
            return httpx.Response(200, json={"total": 50, "eligible": [], "eligible_count": 0})
        if request.url.path == "/api/v1/scanner/intraday":
            return httpx.Response(200, json={"rankings": [], "market_status": "closed"})
        if request.url.path == "/api/v1/alerts":
            return httpx.Response(200, json={"alerts": [], "total": 0})
        if request.url.path == "/api/v1/alerts/test":
            return httpx.Response(200, json={"status": "sent", "message": "ok"})
        raise AssertionError(request.url.path)

    c = _client(_h)
    assert (await universe_scan(c))["total"] == 50
    assert (await scanner_rankings(c))["market_status"] == "closed"
    assert (await alerts_history(c))["total"] == 0
    assert (await send_test_alert(c))["status"] == "sent"
