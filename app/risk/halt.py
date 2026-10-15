"""HaltGuardian: LULD volatility-halt safety module (NASDAQ/NYSE).

State machine per symbol:
    TRADING -> LIMIT_STATE -> HALTED -> RESUME_AUCTION -> TRADING

While HALTED (or cooling down after resume) every signal for the symbol
is frozen to HOLD: pending order templates must be cancelled by the
caller and risk must be recomputed from scratch after resume.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum


class HaltState(str, Enum):
    TRADING = "trading"
    LIMIT_STATE = "limit_state"
    HALTED = "halted"
    RESUME_AUCTION = "resume_auction"


@dataclass
class HaltRecord:
    symbol: str
    state: HaltState = HaltState.TRADING
    halted_at: datetime | None = None
    resume_at: datetime | None = None
    reason: str = ""
    halts_today: int = 0


class HaltGuardian:
    """Tracks LULD halt state and freezes signals while frozen.

    Args:
        halt_minutes: nominal halt duration (LULD = 5 min, can extend to 10).
        cooldown_seconds: post-resume quiet period before re-arming signals.
        score_penalty: score penalty applied while a symbol is halt-tainted.
    """

    def __init__(
        self,
        halt_minutes: int = 5,
        cooldown_seconds: int = 60,
        score_penalty: int = 50,
    ) -> None:
        self.halt_minutes = halt_minutes
        self.cooldown_seconds = cooldown_seconds
        self.score_penalty = score_penalty
        self._records: dict[str, HaltRecord] = {}

    def record(self, symbol: str) -> HaltRecord:
        return self._records.setdefault(symbol.upper(), HaltRecord(symbol=symbol.upper()))

    def report_limit_state(self, symbol: str, reason: str = "limit up-down") -> HaltRecord:
        rec = self.record(symbol)
        if rec.state == HaltState.TRADING:
            rec.state = HaltState.LIMIT_STATE
            rec.reason = reason
        return rec

    def report_halt(self, symbol: str, reason: str = "LULD halt") -> HaltRecord:
        """Enter HALTED. Caller MUST cancel pending order templates."""
        rec = self.record(symbol)
        now = datetime.now(UTC)
        rec.state = HaltState.HALTED
        rec.halted_at = now
        rec.reason = reason
        rec.halts_today += 1
        return rec

    def report_resume(self, symbol: str) -> HaltRecord:
        rec = self.record(symbol)
        rec.state = HaltState.RESUME_AUCTION
        rec.resume_at = datetime.now(UTC)
        return rec

    def is_frozen(self, symbol: str, now: datetime | None = None) -> bool:
        """True while halted or inside the post-resume cooldown."""
        rec = self._records.get(symbol.upper())
        if rec is None or rec.state == HaltState.TRADING:
            return False
        if rec.state in (HaltState.HALTED, HaltState.LIMIT_STATE):
            return True
        now = now or datetime.now(UTC)
        if rec.resume_at is None:
            return True
        elapsed = (now - rec.resume_at).total_seconds()
        if elapsed >= self.cooldown_seconds:
            rec.state = HaltState.TRADING
            rec.reason = ""
            return False
        return True

    def freeze_reasons(self, symbol: str) -> list[str]:
        if not self.is_frozen(symbol):
            return []
        rec = self.record(symbol)
        return [f"halt activo ({rec.state.value}): señales congeladas, cancelar plantillas"]

    def penalty(self, symbol: str) -> int:
        """Score penalty while halt-tainted (decays once back to TRADING)."""
        rec = self._records.get(symbol.upper())
        if rec is None or rec.state == HaltState.TRADING:
            return 0
        return self.score_penalty

    def halts_today(self, symbol: str) -> int:
        return self.record(symbol).halts_today
