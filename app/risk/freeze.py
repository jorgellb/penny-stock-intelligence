"""DilutionFreeze + DollarRule: SEC-driven buy gating for NASDAQ/NYSE.

- DilutionFreeze: S-1/S-3 effectiveness, offering pricing (424B2/424B5),
  or 8-K Item 1.01/3.02 (purchase agreement / ATM activation) freezes
  BUY signals for `freeze_days`. ATM-active names need RVOL >= 5.
- DollarRuleTracker: counts consecutive closes below $1.00 (Nasdaq bid
  price rule). Warning at 90 days, critical at 150: buys blocked, score
  penalized, spread requirement tightened.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.domain.models import Filing, FilingType

# Filing types whose *effectiveness/pricing* means dilution is imminent.
FREEZE_FILING_TYPES = frozenset(
    {
        FilingType.S_1,
        FilingType.S_3,
        FilingType.F_1,
        FilingType.F_3,
        FilingType.FORM_424B2,
        FilingType.FORM_424B5,
    }
)

# 8-K items that signal purchase agreements or ATM activation.
FREEZE_8K_ITEMS = frozenset({"1.01", "3.02", "8.01"})

DOLLAR_RULE_PRICE = 1.00
DOLLAR_WARN_DAYS = 90
DOLLAR_CRITICAL_DAYS = 150


@dataclass
class FreezeDecision:
    symbol: str
    freeze_buys: bool = False
    atm_active: bool = False
    reasons: list[str] = field(default_factory=list)
    checked_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class DilutionFreeze:
    """Decides whether BUYs must be frozen from recent SEC filings."""

    def __init__(self, freeze_days: int = 30, atm_min_rvol: float = 5.0) -> None:
        self.freeze_days = freeze_days
        self.atm_min_rvol = atm_min_rvol

    def evaluate(
        self, symbol: str, filings: list[Filing], now: datetime | None = None
    ) -> FreezeDecision:
        now = now or datetime.now(UTC)
        out = FreezeDecision(symbol=symbol.upper())
        for filing in filings:
            age_days = (now - filing.filing_date).days
            if age_days < 0 or age_days > self.freeze_days:
                continue
            ftype = filing.filing_type
            if ftype in FREEZE_FILING_TYPES:
                out.freeze_buys = True
                out.reasons.append(
                    f"dilución inminente: {ftype.value} del {filing.filing_date.date()} "
                    f"(hace {age_days}d) — compras congeladas"
                )
            elif ftype == FilingType.FORM_8K and set(filing.items or []) & FREEZE_8K_ITEMS:
                matched = sorted(set(filing.items or []) & FREEZE_8K_ITEMS)
                out.freeze_buys = True
                out.atm_active = out.atm_active or "3.02" in matched
                out.reasons.append(
                    f"8-K items {matched} del {filing.filing_date.date()} — compras congeladas"
                )
        if out.atm_active:
            out.reasons.append(
                f"ATM activo: exigir RVOL >= {self.atm_min_rvol}x para cualquier BUY"
            )
        return out


@dataclass
class DollarRuleState:
    symbol: str
    consecutive_below: int = 0
    last_close: float | None = None
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def level(self) -> str:
        if self.consecutive_below >= DOLLAR_CRITICAL_DAYS:
            return "critical"
        if self.consecutive_below >= DOLLAR_WARN_DAYS:
            return "warning"
        return "ok"


class DollarRuleTracker:
    """Tracks consecutive closes below $1.00 (Nasdaq bid-price rule)."""

    def __init__(self) -> None:
        self._states: dict[str, DollarRuleState] = {}

    def update(self, symbol: str, close: float) -> DollarRuleState:
        sym = symbol.upper()
        st = self._states.setdefault(sym, DollarRuleState(symbol=sym))
        st.last_close = close
        st.updated_at = datetime.now(UTC)
        st.consecutive_below = st.consecutive_below + 1 if close < DOLLAR_RULE_PRICE else 0
        return st

    def state(self, symbol: str) -> DollarRuleState:
        return self._states.setdefault(symbol.upper(), DollarRuleState(symbol=symbol.upper()))

    def buy_blocked(self, symbol: str) -> tuple[bool, str]:
        st = self.state(symbol)
        if st.level == "critical":
            return True, (
                f"regla $1 crítica: {st.consecutive_below} cierres bajo $1.00 "
                "(riesgo de deslistado) — compras bloqueadas"
            )
        return False, ""

    def score_penalty(self, symbol: str) -> int:
        level = self.state(symbol).level
        return 30 if level == "critical" else 10 if level == "warning" else 0

    def max_spread_pct(self, symbol: str, default: float = 5.0) -> float:
        """Tighten spread requirement as delisting risk grows."""
        return 2.0 if self.state(symbol).level == "critical" else default
