"""Minimal async repositories over SQLAlchemy sessions."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import List, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import Fundamentals as FundamentalsDomain
from app.models import (
    Alerts,
    CircuitEvents,
    DailyBars,
    MonitorSnapshots,
    PaperPositions,
    PaperTrades,
    ScannerSnapshots,
    Scores,
    Securities,
    WatchlistItems,
)
from app.models import (
    Fundamentals as FundamentalsRow,
)
from app.risk.paper import PaperTrade


class SecurityRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def upsert(
        self,
        symbol: str,
        exchange: str = "NASDAQ",
        name: str | None = None,
        is_etf: bool = False,
        is_preferred: bool = False,
        is_warrant: bool = False,
        is_spac_unit: bool = False,
        is_fund: bool = False,
        is_active: bool = True,
    ) -> Securities:
        res = await self.session.execute(select(Securities).where(Securities.symbol == symbol))
        obj = res.scalar_one_or_none()
        if obj is None:
            obj = Securities(
                symbol=symbol,
                exchange=exchange,
                name=name,
                is_etf=is_etf,
                is_preferred=is_preferred,
                is_warrant=is_warrant,
                is_spac_unit=is_spac_unit,
                is_fund=is_fund,
                is_active=is_active,
            )
            self.session.add(obj)
            await self.session.flush()
        else:
            obj.exchange = exchange
            obj.name = name
            obj.is_etf = is_etf
            obj.is_preferred = is_preferred
            obj.is_warrant = is_warrant
            obj.is_spac_unit = is_spac_unit
            obj.is_fund = is_fund
            obj.is_active = is_active
            await self.session.flush()
        return obj

    async def list_active(self, limit: int = 5000) -> list[Securities]:
        res = await self.session.execute(
            select(Securities).where(Securities.is_active.is_(True)).limit(limit)
        )  # noqa: E712
        return list(res.scalars().all())


class ScoreRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def latest(self, symbol: str) -> Scores | None:
        res = await self.session.execute(
            select(Scores).where(Scores.symbol == symbol).order_by(Scores.timestamp.desc()).limit(1)
        )
        return res.scalar_one_or_none()


class AlertRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def save(
        self,
        *,
        symbol: str,
        action: str,
        signal_type: str,
        price: float,
        score: int,
        change_pct: float = 0.0,
        message: str = "",
        risk_flags: list[str] | None = None,
        reasons: list[str] | None = None,
        catalyst_summary: str | None = None,
        sent: bool = False,
        providers: list[str] | None = None,
    ) -> Alerts:
        """Persist one signal event. Only actionable (buy/sell) events qualify."""
        row = Alerts(
            symbol=symbol.upper(),
            score_id=None,
            action=action,
            signal_type=signal_type,
            price=price,
            score=score,
            change_pct=change_pct,
            message=message,
            risk_flags=risk_flags or [],
            reasons=reasons or [],
            catalyst_summary=catalyst_summary,
            providers=providers or [],
            sent_at=datetime.now(UTC) if sent else None,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def recent(
        self,
        symbol: str | None = None,
        limit: int = 50,
        since: datetime | None = None,
        sent: bool | None = None,
    ) -> list[Alerts]:
        q = select(Alerts)
        if symbol:
            q = q.where(Alerts.symbol == symbol.upper())
        if since is not None:
            q = q.where(Alerts.created_at >= since)
        if sent is True:
            q = q.where(Alerts.sent_at.is_not(None))
        elif sent is False:
            q = q.where(Alerts.sent_at.is_(None))
        q = q.order_by(Alerts.created_at.desc()).limit(limit)
        res = await self.session.execute(q)
        return list(res.scalars().all())


def _to_int(value: object) -> int | None:
    try:
        return int(float(str(value))) if value is not None else None
    except (TypeError, ValueError):
        return None


class DailyBarRepository:
    """Daily OHLCV storage (idempotent per symbol+date)."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def upsert_batch(self, symbol: str, bars: list) -> int:
        """Insert bars not already present. `bars` are domain DailyBar."""
        sym = symbol.upper()
        saved = 0
        for b in bars:
            day = b.date if isinstance(b.date, datetime) else datetime.now(UTC)
            res = await self.session.execute(
                select(DailyBars).where(DailyBars.symbol == sym, DailyBars.date == day)
            )
            if res.scalar_one_or_none() is not None:
                continue
            self.session.add(
                DailyBars(
                    symbol=sym,
                    date=day,
                    open=str(b.open),
                    high=str(b.high),
                    low=str(b.low),
                    close=str(b.close),
                    volume=int(b.volume),
                    provider=b.provider,
                )
            )
            saved += 1
        if saved:
            await self.session.flush()
        return saved

    async def count(self, symbol: str) -> int:
        from sqlalchemy import func as _func

        res = await self.session.execute(
            select(_func.count()).select_from(DailyBars).where(DailyBars.symbol == symbol.upper())
        )
        return int(res.scalar() or 0)


class FundamentalsRepository:
    """Fundamental snapshots (append-only; latest wins by period_end)."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def save_snapshot(self, fund: FundamentalsDomain) -> FundamentalsRow:
        row = FundamentalsRow(
            symbol=fund.symbol.upper(),
            period_end=fund.period_end,
            period_type=fund.period_type,
            market_cap=_to_int(fund.market_cap),
            enterprise_value=_to_int(fund.enterprise_value),
            shares_outstanding=_to_int(fund.shares_outstanding),
            float_shares=_to_int(fund.float_shares),
            insider_ownership_pct=fund.insider_ownership_pct,
            institutional_ownership_pct=fund.institutional_ownership_pct,
            revenue=_to_int(fund.revenue),
            gross_profit=_to_int(fund.gross_profit),
            operating_income=_to_int(fund.operating_income),
            net_income=_to_int(fund.net_income),
            eps_diluted=fund.eps_diluted,
            cash=_to_int(fund.cash),
            total_cash=_to_int(fund.total_cash),
            total_debt=_to_int(fund.total_debt),
            operating_cash_flow=_to_int(fund.operating_cash_flow),
            free_cash_flow=_to_int(fund.free_cash_flow),
            revenue_yoy_growth=fund.revenue_yoy_growth,
            data_quality_score=fund.data_quality_score,
            provider=fund.provider,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def latest(self, symbol: str) -> FundamentalsRow | None:
        res = await self.session.execute(
            select(FundamentalsRow)
            .where(FundamentalsRow.symbol == symbol.upper())
            .order_by(FundamentalsRow.period_end.desc())
            .limit(1)
        )
        return res.scalar_one_or_none()


class CircuitEventRepository:
    """Audit trail for circuit-breaker trips (symbol/strategy/portfolio)."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def save_batch(self, events: list[dict]) -> int:
        """Persist breaker events ({level, key, reason[, timestamp]})."""
        saved = 0
        for e in events:
            ts = e.get("timestamp")
            row = CircuitEvents(
                level=str(e["level"]),
                key=str(e["key"]),
                reason=str(e["reason"]),
                created_at=ts if isinstance(ts, datetime) else datetime.now(UTC),
            )
            self.session.add(row)
            saved += 1
        if saved:
            await self.session.flush()
        return saved

    async def recent(self, level: str | None = None, limit: int = 50) -> list[CircuitEvents]:
        q = select(CircuitEvents)
        if level:
            q = q.where(CircuitEvents.level == level)
        q = q.order_by(CircuitEvents.created_at.desc()).limit(limit)
        res = await self.session.execute(q)
        return list(res.scalars().all())


class PaperPositionRepository:
    """Open paper positions (upsert on open, delete on close)."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def upsert(
        self, symbol: str, shares: int, entry_price: float, entry_time: datetime
    ) -> PaperPositions:
        sym = symbol.upper()
        res = await self.session.execute(select(PaperPositions).where(PaperPositions.symbol == sym))
        obj = res.scalar_one_or_none()
        if obj is None:
            obj = PaperPositions(
                symbol=sym, shares=shares, entry_price=entry_price, entry_time=entry_time
            )
            self.session.add(obj)
        else:
            obj.shares = shares
            obj.entry_price = entry_price
            obj.entry_time = entry_time
            obj.updated_at = datetime.now(UTC)
        await self.session.flush()
        return obj

    async def remove(self, symbol: str) -> bool:
        res = await self.session.execute(
            delete(PaperPositions).where(PaperPositions.symbol == symbol.upper())
        )
        return int(getattr(res, "rowcount", 0) or 0) > 0

    async def list_all(self) -> list[PaperPositions]:
        res = await self.session.execute(select(PaperPositions).order_by(PaperPositions.symbol))
        return list(res.scalars().all())


class PaperTradeRepository:
    """Closed paper trades (one row per SELL close)."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def save(self, trade: PaperTrade) -> PaperTrades:
        row = PaperTrades(
            symbol=trade.symbol,
            shares=trade.shares,
            entry_price=trade.entry_price,
            exit_price=trade.exit_price,
            pnl_dollars=trade.pnl_dollars,
            pnl_pct=trade.pnl_pct,
            entry_time=trade.entry_time,
            exit_time=trade.exit_time,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def recent(self, symbol: str | None = None, limit: int = 50) -> list[PaperTrades]:
        q = select(PaperTrades)
        if symbol:
            q = q.where(PaperTrades.symbol == symbol.upper())
        q = q.order_by(PaperTrades.exit_time.desc()).limit(limit)
        res = await self.session.execute(q)
        return list(res.scalars().all())


class MonitorSnapshotRepository:
    """Per-symbol round evaluations (calibration dataset, no future data)."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def save_batch(self, rows: list[dict]) -> int:
        for r in rows:
            self.session.add(MonitorSnapshots(**r))
        if rows:
            await self.session.flush()
        return len(rows)

    async def recent(self, symbol: str | None = None, limit: int = 100) -> list[MonitorSnapshots]:
        q = select(MonitorSnapshots)
        if symbol:
            q = q.where(MonitorSnapshots.symbol == symbol.upper())
        q = q.order_by(MonitorSnapshots.created_at.desc()).limit(limit)
        res = await self.session.execute(q)
        return list(res.scalars().all())


class ScannerRunRepository:
    """Round summaries (one row per run_once)."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def save_run(
        self,
        *,
        run_type: str,
        symbols_scanned: int,
        eligible_count: int,
        alerts_generated: int,
        duration_ms: int,
        status: str = "completed",
        error: str | None = None,
        config_hash: str = "",
    ) -> ScannerSnapshots:
        now = datetime.now(UTC)
        row = ScannerSnapshots(
            run_type=run_type,
            started_at=now,
            completed_at=now,
            symbols_scanned=symbols_scanned,
            eligible_count=eligible_count,
            alerts_generated=alerts_generated,
            duration_ms=duration_ms,
            status=status,
            error=error,
            config_hash=config_hash,
        )
        self.session.add(row)
        await self.session.flush()
        return row


class WatchlistRepository:
    """Persistent user stock lists (watchlists)."""

    DEFAULT_LIST = "default"

    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def normalize(symbol: str) -> str:
        return symbol.strip().upper()

    async def add(
        self,
        symbol: str,
        user_id: str = "default",
        list_name: str = DEFAULT_LIST,
        notes: str | None = None,
    ) -> tuple[WatchlistItems, bool]:
        """Add a symbol. Returns (item, created). Idempotent."""
        sym = self.normalize(symbol)
        if not sym:
            raise ValueError("empty symbol")
        res = await self.session.execute(
            select(WatchlistItems).where(
                WatchlistItems.user_id == user_id,
                WatchlistItems.list_name == list_name,
                WatchlistItems.symbol == sym,
            )
        )
        obj = res.scalar_one_or_none()
        if obj is not None:
            return obj, False
        obj = WatchlistItems(user_id=user_id, list_name=list_name, symbol=sym, notes=notes)
        self.session.add(obj)
        await self.session.flush()
        return obj, True

    async def remove(
        self, symbol: str, user_id: str = "default", list_name: str = DEFAULT_LIST
    ) -> bool:
        """Remove a symbol. Returns True if something was deleted."""
        res = await self.session.execute(
            delete(WatchlistItems).where(
                WatchlistItems.user_id == user_id,
                WatchlistItems.list_name == list_name,
                WatchlistItems.symbol == self.normalize(symbol),
            )
        )
        return int(getattr(res, "rowcount", 0) or 0) > 0

    async def symbols(self, user_id: str = "default", list_name: str = DEFAULT_LIST) -> list[str]:
        res = await self.session.execute(
            select(WatchlistItems.symbol)
            .where(WatchlistItems.user_id == user_id, WatchlistItems.list_name == list_name)
            .order_by(WatchlistItems.symbol)
        )
        return [r for r in res.scalars().all()]

    async def items(
        self, user_id: str = "default", list_name: str = DEFAULT_LIST
    ) -> list[WatchlistItems]:
        res = await self.session.execute(
            select(WatchlistItems)
            .where(WatchlistItems.user_id == user_id, WatchlistItems.list_name == list_name)
            .order_by(WatchlistItems.symbol)
        )
        return list(res.scalars().all())

    async def user_ids(self) -> list[str]:
        res = await self.session.execute(select(WatchlistItems.user_id).distinct())
        return [r for r in res.scalars().all()]

    async def lists(self, user_id: str = "default") -> list[dict[str, object]]:
        res = await self.session.execute(
            select(WatchlistItems.list_name, WatchlistItems.symbol).where(
                WatchlistItems.user_id == user_id
            )
        )
        counts: dict[str, int] = {}
        for name, _sym in res.all():
            counts[name] = counts.get(name, 0) + 1
        return [{"name": n, "count": c} for n, c in sorted(counts.items())]

    async def delete_list(self, user_id: str = "default", list_name: str = DEFAULT_LIST) -> int:
        res = await self.session.execute(
            delete(WatchlistItems).where(
                WatchlistItems.user_id == user_id, WatchlistItems.list_name == list_name
            )
        )
        return int(getattr(res, "rowcount", 0) or 0)
