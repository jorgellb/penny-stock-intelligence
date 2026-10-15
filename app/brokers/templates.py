"""Manual-assisted order templates (DEGIRO = manual execution only).

The bot never places orders. It generates LIMIT-only templates with a
suggested DMA venue (ARCA/BATS/EDGX). Market orders are rejected by
construction: slippage on penny-stock breaks averages 2-5%.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any


class MarketOrderForbiddenError(ValueError):
    """Raised when a market order template is requested."""


PREFERRED_VENUES = ("ARCA", "BATS", "EDGX")


@dataclass
class OrderTemplate:
    symbol: str
    side: str  # buy|sell
    order_type: str  # limit only
    quantity: int
    limit_price: Decimal
    venue: str = "ARCA"
    time_in_force: str = "day"
    reason: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_manual_instruction(self) -> str:
        return (
            f"DEGIRO manual: {self.side.upper()} {self.quantity}x {self.symbol} "
            f"LIMIT ${self.limit_price} via {self.venue} (TIF {self.time_in_force}). "
            f"Motivo: {self.reason}"
        )


def build_limit_template(
    symbol: str,
    side: str,
    quantity: int,
    reference_price: float,
    urgency_offset_bps: int = 10,
    venue: str = "ARCA",
    reason: str = "",
) -> OrderTemplate:
    """Build a LIMIT template. `side=buy` pays up, `side=sell` gives up."""
    if side not in ("buy", "sell"):
        raise ValueError(f"side must be buy|sell, got {side}")
    if quantity <= 0 or reference_price <= 0:
        raise ValueError("quantity and reference_price must be positive")
    if venue not in PREFERRED_VENUES:
        raise ValueError(f"venue must be one of {PREFERRED_VENUES}")
    offset = reference_price * urgency_offset_bps / 10_000
    limit = reference_price + offset if side == "buy" else reference_price - offset
    return OrderTemplate(
        symbol=symbol.upper(),
        side=side,
        order_type="limit",
        quantity=quantity,
        limit_price=Decimal(str(round(limit, 4))),
        venue=venue,
        reason=reason,
    )


def build_template(
    symbol: str, side: str, quantity: int, order_type: str, **kwargs: Any
) -> OrderTemplate:
    """Generic entry point: rejects anything that is not a limit order."""
    if order_type.lower() != "limit":
        raise MarketOrderForbiddenError(
            f"market orders prohibidas en penny stocks (pedida: {order_type})"
        )
    return build_limit_template(symbol, side, quantity, **kwargs)
