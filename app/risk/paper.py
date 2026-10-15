"""Paper portfolio tracker for the monitor (no orders, no broker).

Semantics (deliberately simple, documented):
- One open position per symbol max. A BUY while one is open is ignored
  (no pyramiding in penny stocks).
- A SELL closes the whole position at the round price.
- Quantity comes from the BUY order template; when absent, a default
  notional (default_position_notional) is converted to shares.
- Costs use BacktestConfig via apply_costs with the round spread when
  known (spread_pct=None keeps legacy base costs).
- Day boundaries use America/New_York dates; daily PnL resets on day
  rollover. All timestamps stored in UTC.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.backtesting import BacktestConfig, apply_costs
from app.core.market_calendar import to_et


@dataclass
class PaperPosition:
    symbol: str
    shares: int
    entry_price: float  # all-in (costs included)
    entry_time: datetime
    last_price: float = 0.0

    @property
    def market_value(self) -> float:
        return self.shares * (self.last_price or self.entry_price)

    @property
    def cost_basis(self) -> float:
        return self.shares * self.entry_price

    @property
    def unrealized_pct(self) -> float:
        if not self.entry_price:
            return 0.0
        px = self.last_price or self.entry_price
        return (px - self.entry_price) / self.entry_price * 100


@dataclass
class PaperTrade:
    symbol: str
    shares: int
    entry_price: float
    exit_price: float
    entry_time: datetime
    exit_time: datetime
    pnl_dollars: float
    pnl_pct: float


@dataclass
class PaperTracker:
    starting_equity: float = 10_000.0
    default_position_notional: float = 2_000.0
    costs: BacktestConfig = field(default_factory=BacktestConfig)
    positions: dict[str, PaperPosition] = field(default_factory=dict)
    closed: list[PaperTrade] = field(default_factory=list)
    realized_today: float = 0.0
    _day: str = ""

    def _today(self, now: datetime) -> str:
        return to_et(now).date().isoformat()

    def _roll_day(self, now: datetime) -> None:
        day = self._today(now)
        if self._day and day != self._day:
            self.realized_today = 0.0
        self._day = day

    @property
    def equity(self) -> float:
        """Cash-settled equity: start + realized + unrealized."""
        open_pnl = sum(p.market_value - p.cost_basis for p in self.positions.values())
        closed_pnl = sum(t.pnl_dollars for t in self.closed)
        return self.starting_equity + closed_pnl + open_pnl

    @property
    def daily_pnl_pct(self) -> float:
        """Realized-today + unrealized, over starting equity."""
        open_pnl = sum(p.market_value - p.cost_basis for p in self.positions.values())
        base = self.starting_equity or 1.0
        return (self.realized_today + open_pnl) / base * 100

    def on_buy(
        self,
        symbol: str,
        price: float,
        shares: int | None = None,
        spread_pct: float | None = None,
        now: datetime | None = None,
    ) -> PaperPosition | None:
        """Open a paper position. None when one is already open (no pyramid)."""
        now = now or datetime.now(UTC)
        self._roll_day(now)
        sym = symbol.upper()
        if sym in self.positions or price <= 0:
            return None
        qty = shares or max(1, int(self.default_position_notional / price))
        entry = apply_costs(price, "buy", self.costs, spread_pct=spread_pct)
        pos = PaperPosition(
            symbol=sym, shares=qty, entry_price=entry, entry_time=now, last_price=price
        )
        self.positions[sym] = pos
        return pos

    def on_sell(
        self,
        symbol: str,
        price: float,
        spread_pct: float | None = None,
        now: datetime | None = None,
    ) -> PaperTrade | None:
        """Close the whole position. None when flat."""
        now = now or datetime.now(UTC)
        self._roll_day(now)
        pos = self.positions.pop(symbol.upper(), None)
        if pos is None or price <= 0:
            return None
        exit_px = apply_costs(price, "sell", self.costs, spread_pct=spread_pct)
        pnl = (exit_px - pos.entry_price) * pos.shares
        base = pos.cost_basis or 1.0
        trade = PaperTrade(
            symbol=pos.symbol,
            shares=pos.shares,
            entry_price=pos.entry_price,
            exit_price=exit_px,
            entry_time=pos.entry_time,
            exit_time=now,
            pnl_dollars=round(pnl, 2),
            pnl_pct=round(pnl / base * 100, 2),
        )
        self.closed.append(trade)
        self.realized_today += trade.pnl_dollars
        return trade

    def mark(self, symbol: str, price: float) -> None:
        """Update last price for MtM (never opens/closes anything)."""
        pos = self.positions.get(symbol.upper())
        if pos is not None and price > 0:
            pos.last_price = price

    def position_pnl_pct(self, symbol: str) -> float | None:
        pos = self.positions.get(symbol.upper())
        return pos.unrealized_pct if pos else None

    def summary(self) -> dict:
        return {
            "equity": round(self.equity, 2),
            "starting_equity": self.starting_equity,
            "open_positions": len(self.positions),
            "positions": {
                s: {
                    "shares": p.shares,
                    "entry": round(p.entry_price, 4),
                    "last": round(p.last_price, 4),
                    "unrealized_pct": round(p.unrealized_pct, 2),
                }
                for s, p in self.positions.items()
            },
            "closed_trades": len(self.closed),
            "realized_today": round(self.realized_today, 2),
            "daily_pnl_pct": round(self.daily_pnl_pct, 2),
        }
