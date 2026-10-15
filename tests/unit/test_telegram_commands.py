"""Unit: telegram command builders + dispatch + poll loop (no network)."""

from types import SimpleNamespace

import httpx
import pytest

from app.alerts.telegram_commands import (
    TelegramCommander,
    circuits_text,
    dispatch,
    events_text,
    help_text,
    paper_text,
    status_text,
)


def _svc() -> SimpleNamespace:
    return SimpleNamespace(
        status=lambda: {
            "regime": "chop",
            "tracked_symbols": 3,
            "stats": {"signals": 1, "sent": 1},
            "kill_switch": False,
            "vetoed_symbols": [],
            "circuit_events": [{"level": "symbol", "key": "AAA", "reason": "veto"}],
        },
        recent_events=lambda limit=50: [
            {"symbol": "AAA", "action": "buy", "price": 2.2, "score": 80}
        ],
        paper=SimpleNamespace(
            summary=lambda: {
                "equity": 10100.0,
                "starting_equity": 10000.0,
                "open_positions": 1,
                "closed_trades": 0,
                "realized_today": 0.0,
                "daily_pnl_pct": 1.0,
                "positions": {"AAA": {"shares": 100, "unrealized_pct": 1.0}},
            }
        ),
    )


def test_help_and_unknown() -> None:
    assert "/status" in help_text()
    assert "desconocido" in (dispatch("/foo", _svc()) or "")
    assert dispatch("hola", _svc()) is None  # not a command: ignored


def test_dispatch_all_commands() -> None:
    svc = _svc()
    assert "chop" in (dispatch("/status", svc) or "")
    assert "AAA" in (dispatch("/events", svc) or "")
    assert "AAA" in (dispatch("/events 3", svc) or "")
    assert "10100" in (dispatch("/paper", svc) or "")
    assert "veto" in (dispatch("/circuits", svc) or "")
    assert "/status" in (dispatch("/help", svc) or "")
    assert dispatch("/status@mybot", svc) is not None  # group mention tolerated


def test_builders_empty() -> None:
    assert events_text([]) == "sin señales recientes"
    assert circuits_text([]) == "sin trips de circuito recientes"
    assert "off" in status_text({})
    assert "equity" in paper_text({})


@pytest.mark.asyncio
async def test_poll_once_answers_own_chat_only() -> None:
    sent: list[dict] = []

    def _h(request: httpx.Request) -> httpx.Response:
        if "getUpdates" in str(request.url):
            return httpx.Response(
                200,
                json={
                    "result": [
                        {
                            "update_id": 7,
                            "message": {"chat": {"id": 123}, "text": "/status"},
                        },
                        {
                            "update_id": 8,
                            "message": {"chat": {"id": 999}, "text": "/status"},
                        },
                        {
                            "update_id": 9,
                            "message": {"chat": {"id": 123}, "text": "hola"},
                        },
                    ]
                },
            )
        sent.append(dict(request.url.params) if hasattr(request.url, "params") else {})
        return httpx.Response(200, json={"ok": True})

    posted: list[dict] = []

    def _cap(request: httpx.Request) -> httpx.Response:
        import json as _json

        posted.append(_json.loads(request.content.decode()))
        return httpx.Response(200, json={"ok": True})

    def _router(request: httpx.Request) -> httpx.Response:
        if "getUpdates" in str(request.url):
            return _h(request)
        return _cap(request)

    cmd = TelegramCommander("TOK", "123")
    async with httpx.AsyncClient(transport=httpx.MockTransport(_router)) as client:
        handled = await cmd.poll_once(client, _svc())
    assert handled == 1  # stranger ignored, non-command ignored
    assert cmd.offset == 10
    assert len(posted) == 1 and "chop" in posted[0]["text"]
    assert posted[0]["chat_id"] == "123"
