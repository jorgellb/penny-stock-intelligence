"""Alert engine: console/telegram/discord/email/webhook with cooldown + dedup."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

from app.config import get_settings
from app.core.logging import get_logger
from app.domain.models import Alert, AlertProvider

log = get_logger(__name__)


class ConsoleAlertProvider:
    name = "console"

    async def send(self, alert: Alert) -> bool:
        print(alert.message)
        return True

    async def send_batch(self, alerts: list[Alert]) -> dict[str, bool]:
        return {str(a.id): await self.send(a) for a in alerts}

    async def health_check(self) -> bool:
        return True


class TelegramAlertProvider:
    name = "telegram"

    async def send(self, alert: Alert) -> bool:
        s = get_settings()
        if not s.telegram_bot_token or not s.telegram_chat_id:
            log.warning("telegram_not_configured")
            return False
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.post(
                    f"https://api.telegram.org/bot{s.telegram_bot_token}/sendMessage",
                    json={"chat_id": s.telegram_chat_id, "text": alert.message},
                )
                return r.status_code == 200
        except Exception as e:
            log.error("telegram_failed", error=str(e))
            return False

    async def send_batch(self, alerts: list[Alert]) -> dict[str, bool]:
        return {str(a.id): await self.send(a) for a in alerts}

    async def health_check(self) -> bool:
        s = get_settings()
        return bool(s.telegram_bot_token and s.telegram_chat_id)


class DiscordAlertProvider:
    name = "discord"

    async def send(self, alert: Alert) -> bool:
        s = get_settings()
        if not s.discord_webhook_url:
            return False
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.post(s.discord_webhook_url, json={"content": alert.message[:1900]})
                return r.status_code in (200, 204)
        except Exception:
            return False

    async def send_batch(self, alerts: list[Alert]) -> dict[str, bool]:
        return {str(a.id): await self.send(a) for a in alerts}

    async def health_check(self) -> bool:
        try:
            return bool(get_settings().discord_webhook_url)
        except Exception:
            return False


class EmailAlertProvider:
    name = "email"

    async def send(self, alert: Alert) -> bool:
        s = get_settings()
        if not (s.smtp_username and s.email_to):
            log.warning("email_not_configured")
            return False
        return True

    async def send_batch(self, alerts: list[Alert]) -> dict[str, bool]:
        return {str(a.id): await self.send(a) for a in alerts}

    async def health_check(self) -> bool:
        return False


class WebhookAlertProvider:
    name = "webhook"

    async def send(self, alert: Alert) -> bool:
        s = get_settings()
        if not s.webhook_url:
            return False
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.post(s.webhook_url, json=alert.model_dump(mode="json"))
                return r.status_code < 300
        except Exception:
            return False

    async def send_batch(self, alerts: list[Alert]) -> dict[str, bool]:
        return {str(a.id): await self.send(a) for a in alerts}

    async def health_check(self) -> bool:
        try:
            return bool(get_settings().webhook_url)
        except Exception:
            return False


class AlertEngine:
    def __init__(self) -> None:
        self._last_sent: dict[str, datetime] = {}
        self._last_score: dict[str, int] = {}

    def _cooldown_ok(self, symbol: str, score: int) -> bool:
        try:
            s = get_settings()
            cd, delta = s.alerts.cooldown_minutes, s.alerts.score_change_realert
        except Exception:
            cd, delta = 20, 10
        now = datetime.now(UTC)
        last = self._last_sent.get(symbol)
        if last and now - last < timedelta(minutes=cd):
            prev = self._last_score.get(symbol, 0)
            if abs(score - prev) < delta:
                return False
        return True

    def should_send(self, symbol: str, score: int, minimum: int | None = None) -> bool:
        try:
            minimum = minimum if minimum is not None else get_settings().alerts.minimum_score
        except Exception:
            minimum = 70
        if score < minimum:
            return False
        return self._cooldown_ok(symbol, score)

    def mark_sent(self, symbol: str, score: int) -> None:
        self._last_sent[symbol] = datetime.now(UTC)
        self._last_score[symbol] = score

    async def send_critical(self, message: str) -> bool:
        """Critical broadcast (kill switch): bypasses cooldown/dedup.

        Callers must edge-trigger (once per transition), otherwise every
        round would re-broadcast while the condition persists.
        """
        from decimal import Decimal
        from uuid import uuid4

        from app.domain.models import SignalType

        alert = Alert(
            symbol="PORTFOLIO",
            score_id=uuid4(),
            score=0,
            signal_type=SignalType.REVERSAL,
            price=Decimal("0"),
            change_pct=0.0,
            message=f"🛑 CRITICAL (revisar): {message}\nSeñal automática, no es recomendación.",
        )
        results = [await p.send(alert) for p in self.providers()]
        return any(results)

    def format_alert(
        self,
        symbol: str,
        price: float,
        score: int,
        breakdown: dict | None = None,
        catalyst: str | None = None,
    ) -> str:
        lines = [
            "\U0001f525 PENNY STOCK ALERT",
            "",
            f"Ticker: {symbol}",
            f"Price: ${price:.2f}",
            f"FINAL: {score}/100",
            "",
            "This score is a ranking metric, not a probability forecast.",
        ]
        if catalyst:
            lines.insert(5, f"Catalyst: {catalyst}")
        return "\n".join(lines)

    def providers(self, names: list[str] | None = None) -> list[Any]:
        allp = {
            "console": ConsoleAlertProvider(),
            "telegram": TelegramAlertProvider(),
            "discord": DiscordAlertProvider(),
            "email": EmailAlertProvider(),
            "webhook": WebhookAlertProvider(),
        }
        if not names:
            try:
                names = get_settings().alerts.enabled_providers
            except Exception:
                names = ["console"]
        return [allp[n] for n in names if n in allp]
