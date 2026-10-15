"""Circuit breakers: symbol / strategy / portfolio kill-switches.

Levels:
- symbol: intraday drawdown from entry or halt -> total exit + 24h veto.
- strategy: daily strategy loss -> strategy off until tomorrow.
- portfolio: daily loss or N suffered halts -> KILL SWITCH: cancel
  everything, read-only monitor, critical Telegram alert.

Events are kept in memory (`events`); persist to DB (`circuit_events`)
when wiring to a live account.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class CircuitEvent:
    level: str  # symbol|strategy|portfolio
    key: str
    reason: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


class CircuitBreaker:
    def __init__(
        self,
        symbol_max_loss_pct: float = 8.0,
        strategy_max_daily_loss_pct: float = 3.0,
        portfolio_max_daily_loss_pct: float = 5.0,
        max_halts_per_day: int = 3,
    ) -> None:
        self.symbol_max_loss_pct = symbol_max_loss_pct
        self.strategy_max_daily_loss_pct = strategy_max_daily_loss_pct
        self.portfolio_max_daily_loss_pct = portfolio_max_daily_loss_pct
        self.max_halts_per_day = max_halts_per_day
        self.vetoed_symbols: dict[str, datetime] = {}
        self.disabled_strategies: set[str] = set()
        self.killed = False
        self.events: list[CircuitEvent] = []

    def _trip(self, level: str, key: str, reason: str) -> CircuitEvent:
        ev = CircuitEvent(level=level, key=key, reason=reason)
        self.events.append(ev)
        return ev

    def check_symbol(
        self, symbol: str, pnl_pct: float, halted: bool = False
    ) -> CircuitEvent | None:
        """Trip on intraday loss or halt: exit + 24h veto."""
        if halted or pnl_pct <= -abs(self.symbol_max_loss_pct):
            self.vetoed_symbols[symbol.upper()] = datetime.now(UTC)
            cause = (
                "halt sufrido" if halted else f"pnl {pnl_pct:.1f}% <= -{self.symbol_max_loss_pct}%"
            )
            return self._trip("symbol", symbol.upper(), f"salida total + veto 24h: {cause}")
        return None

    def is_vetoed(self, symbol: str, now: datetime | None = None) -> bool:
        ts = self.vetoed_symbols.get(symbol.upper())
        if ts is None:
            return False
        now = now or datetime.now(UTC)
        if (now - ts).total_seconds() >= 24 * 3600:
            del self.vetoed_symbols[symbol.upper()]
            return False
        return True

    def check_strategy(self, strategy: str, daily_pnl_pct: float) -> CircuitEvent | None:
        if daily_pnl_pct <= -abs(self.strategy_max_daily_loss_pct):
            self.disabled_strategies.add(strategy)
            return self._trip(
                "strategy", strategy, f"estrategia apagada hasta mañana: {daily_pnl_pct:.1f}%"
            )
        return None

    def check_portfolio(self, daily_pnl_pct: float, halts_suffered: int) -> CircuitEvent | None:
        portfolio_hit = daily_pnl_pct <= -abs(self.portfolio_max_daily_loss_pct)
        if portfolio_hit or halts_suffered >= self.max_halts_per_day:
            self.killed = True
            return self._trip(
                "portfolio",
                "ALL",
                f"KILL SWITCH: pnl {daily_pnl_pct:.1f}% / halts {halts_suffered}: "
                "cancelar todo, solo lectura",
            )
        return None

    def reset_day(self) -> None:
        self.disabled_strategies.clear()
        self.killed = False
