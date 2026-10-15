"""Telegram command bot (read-only, manual-review signals).

Long-polls Bot API getUpdates with httpx (no extra dependency, same style
as TelegramAlertProvider). Commands: /status /events [N] /paper /circuits
/help. Only the configured TELEGRAM_CHAT_ID is answered; every other chat
is ignored (no control surface for strangers). No trading, no order
placement — just the monitor state you could already see in the dashboard.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.core.logging import get_logger

log = get_logger(__name__)

COMMANDS = ("status", "events", "paper", "circuits", "help")


def help_text() -> str:
    return (
        "Penny Stock Intelligence (solo lectura)\n"
        "/status — régimen, kill switch, vetos, paper\n"
        "/events [N] — últimas señales (default 5, max 20)\n"
        "/paper — resumen del portfolio paper\n"
        "/circuits — últimos trips de circuito\n"
        "Señales para revisión manual, no son recomendaciones."
    )


def status_text(status: dict) -> str:
    stats = status.get("stats", {})
    paper = status.get("paper", {})
    lines = [
        f"régimen: {status.get('regime', '?')}",
        f"tracked: {status.get('tracked_symbols', 0)}",
        f"last round: {stats.get('signals', 0)} signals / {stats.get('sent', 0)} sent",
        f"kill switch: {'ACTIVE' if status.get('kill_switch') else 'off'}",
        f"vetoed: {', '.join(status.get('vetoed_symbols', [])) or 'none'}",
        f"paper equity: ${paper.get('equity', '?')} ({paper.get('daily_pnl_pct', '?')}% hoy)",
    ]
    return "\n".join(lines)


def events_text(events: list[dict], n: int = 5) -> str:
    n = max(1, min(20, n))
    rows = events[:n]
    if not rows:
        return "sin señales recientes"
    out = []
    for e in rows:
        out.append(
            f"[{str(e.get('action', '')).upper()}] {e.get('symbol')} "
            f"@ ${float(e.get('price', 0)):.2f} (score {e.get('score')})"
        )
    return "\n".join(out)


def paper_text(summary: dict) -> str:
    lines = [
        f"equity: ${summary.get('equity', '?')} (inicio ${summary.get('starting_equity', '?')})",
        f"abiertas: {summary.get('open_positions', 0)} | "
        f"cerradas: {summary.get('closed_trades', 0)}",
        f"PnL hoy: ${summary.get('realized_today', '?')} ({summary.get('daily_pnl_pct', '?')}%)",
    ]
    for sym, p in (summary.get("positions", {}) or {}).items():
        lines.append(f"  {sym}: {p.get('shares')} acc {p.get('unrealized_pct', '?')}%")
    return "\n".join(lines)


def circuits_text(events: list[dict], n: int = 5) -> str:
    rows = events[: max(1, min(20, n))]
    if not rows:
        return "sin trips de circuito recientes"
    return "\n".join(f"[{e.get('level')}] {e.get('key')}: {e.get('reason')}" for e in rows)


def dispatch(text: str, svc: Any) -> str | None:
    """Route one message to a reply. None = ignore (not a command)."""
    parts = text.strip().split()
    if not parts or not parts[0].startswith("/"):
        return None
    cmd = parts[0][1:].split("@")[0].lower()
    arg = parts[1] if len(parts) > 1 else ""
    if cmd == "status":
        return status_text(svc.status())
    if cmd == "events":
        try:
            n = int(arg) if arg else 5
        except ValueError:
            n = 5
        return events_text(svc.recent_events(limit=50), n)
    if cmd == "paper":
        return paper_text(svc.paper.summary())
    if cmd == "circuits":
        return circuits_text(svc.status().get("circuit_events", []))
    if cmd == "help":
        return help_text()
    return f"comando desconocido. {help_text()}"


class TelegramCommander:
    """Long-poll loop. Needs TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID."""

    def __init__(self, token: str, chat_id: str) -> None:
        self.token = token
        self.chat_id = str(chat_id)
        self.offset = 0
        self.running = False

    def _url(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self.token}/{method}"

    async def poll_once(self, client: httpx.AsyncClient, svc: Any) -> int:
        """Fetch updates, reply to commands from our chat. Returns handled count."""
        resp = await client.get(
            self._url("getUpdates"), params={"offset": self.offset, "timeout": 30}
        )
        resp.raise_for_status()
        handled = 0
        for upd in resp.json().get("result", []):
            self.offset = max(self.offset, int(upd.get("update_id", 0)) + 1)
            msg = upd.get("message", {})
            if str(msg.get("chat", {}).get("id")) != self.chat_id:
                continue
            reply = dispatch(str(msg.get("text", "")), svc)
            if reply is None:
                continue
            try:
                await client.post(
                    self._url("sendMessage"),
                    json={"chat_id": self.chat_id, "text": reply},
                )
                handled += 1
            except Exception as exc:
                log.error("telegram_reply_failed", error=str(exc))
        return handled

    async def run_forever(self, interval: float = 1.0) -> None:
        from app.jobs.monitor import get_monitor_service

        self.running = True
        log.info("telegram_commands_started")
        try:
            async with httpx.AsyncClient(timeout=45) as client:
                while self.running:
                    try:
                        await self.poll_once(client, get_monitor_service())
                    except Exception as exc:
                        log.error("telegram_poll_failed", error=str(exc))
                    await asyncio.sleep(interval)
        except asyncio.CancelledError:
            pass
        finally:
            self.running = False
            log.info("telegram_commands_stopped")
