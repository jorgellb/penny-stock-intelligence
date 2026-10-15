"""Broker abstraction. Live trading disabled by design (DEGIRO = manual execution)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional

from app.core.exceptions import TradingDisabledError


class DisabledBrokerAdapter:
    name = "disabled"

    async def get_account(self) -> dict[str, Any]:
        raise TradingDisabledError()

    async def get_positions(self) -> list[dict[str, Any]]:
        raise TradingDisabledError()

    async def place_order(
        self,
        symbol: str,
        qty: int,
        side: str,
        order_type: str,
        limit_price: Decimal | None = None,
        stop_price: Decimal | None = None,
        time_in_force: str = "day",
    ) -> dict[str, Any]:
        raise TradingDisabledError("Live trading is disabled in this project.")

    async def cancel_order(self, order_id: str) -> bool:
        raise TradingDisabledError()

    async def get_order(self, order_id: str) -> dict[str, Any]:
        raise TradingDisabledError()

    async def get_orders(self, status: str | None = None) -> list[dict[str, Any]]:
        raise TradingDisabledError()

    async def health_check(self) -> bool:
        return False
