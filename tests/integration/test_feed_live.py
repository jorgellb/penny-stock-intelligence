"""Integration: SIP feed wiring in the live monitor.

- Quotes/bars flow through SipFeed (lag measured per fetch).
- Excessive lag marks the symbol STALE (no signals).
- kind=direct without entitlement falls back to SIP with a warning.
"""

from __future__ import annotations

import asyncio

import pytest

from app.config import get_settings
from app.jobs.monitor import MonitorService
from app.providers.market_data import MockMarketDataProvider


@pytest.mark.asyncio
async def test_monitor_uses_sip_feed_by_default() -> None:
    provider = MockMarketDataProvider()
    provider.set_quote("ABCD", 2.20)
    svc = MonitorService(market_data_provider=provider)
    event, details = await svc.evaluate_symbol("ABCD")
    assert details["feed_kind"] == "sip"
    assert details["feed_lag_ms"] >= 0.0
    assert svc.feed_kind == "sip"
    assert "feed" in svc.status()


@pytest.mark.asyncio
async def test_slow_feed_marks_stale_and_blocks_signals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = MockMarketDataProvider()
    provider.set_quote("ABCD", 2.20)

    async def _slow_quote(symbol: str):  # type: ignore[no-untyped-def]
        await asyncio.sleep(0.05)
        return await MockMarketDataProvider.get_quote(provider, symbol)

    monkeypatch.setattr(provider, "get_quote", _slow_quote)
    settings = get_settings()
    monkeypatch.setattr(settings.feed, "max_fetch_lag_ms", 1)  # force STALE
    svc = MonitorService(market_data_provider=provider)
    event, details = await svc.evaluate_symbol("ABCD")
    assert details["stale"] is True
    assert event.action.value == "hold"
    assert any("STALE" in r or "lag" in r for r in event.reasons)


@pytest.mark.asyncio
async def test_direct_without_entitlement_falls_back_to_sip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = MockMarketDataProvider()
    provider.set_quote("ABCD", 2.20)
    settings = get_settings()
    monkeypatch.setattr(settings.feed, "kind", "direct")
    monkeypatch.setattr(settings.feed, "direct_entitlement", None)
    svc = MonitorService(market_data_provider=provider)
    _, details = await svc.evaluate_symbol("ABCD")
    assert details["feed_kind"] == "sip"
    assert svc.feed_warning is not None and "SIP" in svc.feed_warning


@pytest.mark.asyncio
async def test_unknown_feed_kind_falls_back_to_sip(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = MockMarketDataProvider()
    provider.set_quote("ABCD", 2.20)
    settings = get_settings()
    monkeypatch.setattr(settings.feed, "kind", "quantum")
    svc = MonitorService(market_data_provider=provider)
    _, details = await svc.evaluate_symbol("ABCD")
    assert details["feed_kind"] == "sip"
    assert svc.feed_warning is not None
