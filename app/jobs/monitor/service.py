"""Realtime list monitor: watches user stock lists and emits buy/sell signals.

Loop: load list symbols from DB -> fetch quotes/bars concurrently ->
score + risk + signal rules -> deliver via AlertEngine (cooldown/dedup).
Signals are for human review, never recommendations.
"""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

import numpy as _np

from app.alerts import AlertEngine
from app.brokers.templates import build_limit_template
from app.config import get_settings
from app.core.database import get_db_manager
from app.core.logging import get_logger
from app.domain.models import Alert, SignalType
from app.providers.news import CatalystDetector, NewsEngine
from app.repositories import WatchlistRepository
from app.risk.circuit import CircuitBreaker
from app.risk.freeze import DollarRuleTracker
from app.risk.halt import HaltGuardian
from app.risk.paper import PaperTracker
from app.risk.sizing import PositionSizer, SizingInput
from app.scanners.rvol import RVOLCalculator
from app.scoring import (
    ScoringEngine,
    data_quality_from_completeness,
    fundamentals_health_score,
    map_catalyst_strength,
)
from app.scoring.risk import RiskEngine
from app.signals import SignalAction, SignalEvent, SignalInput, evaluate
from app.signals.gates import DonchianInput, detect_squeeze, donchian_entry_gate

from . import persistence as persist
from .round_gates import (
    apply_breadth_cap,
    apply_correlation_gate,
    apply_exit_rules,
    apply_regime_gate,
    compute_regime,
)
from .types import (
    MarketData,
    MonitoredEvent,
    SymbolState,
    enum_val,
    impact_rank,
    liquidity_score,
    momentum_score,
)

log = get_logger(__name__)


class MonitorService:
    """Monitors a set of symbols and emits buy/sell signal events."""

    def __init__(
        self,
        market_data_provider: Any | None = None,
        alert_engine: AlertEngine | None = None,
        halt_guardian: HaltGuardian | None = None,
        news_provider: Any | None = None,
        ai_provider: Any | None = None,
        sec_provider: Any | None = None,
        fundamentals_provider: Any | None = None,
    ) -> None:
        from app.jobs.filings import FilingsCache, get_filings_cache

        settings = get_settings()
        self.news = NewsEngine(news_provider)
        self.ai = ai_provider
        # Own cache when a SEC provider is injected (tests/isolation),
        # otherwise the shared singleton the scheduler job warms.
        if sec_provider is not None:
            self.filings = FilingsCache(sec_provider=sec_provider)
        else:
            self.filings = get_filings_cache()
        self.detector = CatalystDetector()
        self.fundamentals = fundamentals_provider
        self.halts = halt_guardian or HaltGuardian()
        self.dollar_rule = DollarRuleTracker()
        self.sizer = PositionSizer(
            risk_per_trade_pct=settings.sizing.risk_per_trade_pct,
            high_score_bonus_pct=settings.sizing.high_score_bonus_pct,
            high_score_threshold=settings.sizing.high_score_threshold,
            atr_multiple=settings.sizing.atr_multiple,
            max_volume_participation=settings.sizing.max_volume_participation,
            max_float_participation=settings.sizing.max_float_participation,
        )
        self.provider = market_data_provider
        self.alerts = alert_engine or AlertEngine()
        self.scoring = ScoringEngine()
        self.risk = RiskEngine()
        self.rvol = RVOLCalculator()
        circuit_cfg = settings.circuit
        self.breaker = CircuitBreaker(
            symbol_max_loss_pct=circuit_cfg.symbol_max_loss_pct,
            strategy_max_daily_loss_pct=circuit_cfg.strategy_max_daily_loss_pct,
            portfolio_max_daily_loss_pct=circuit_cfg.portfolio_max_daily_loss_pct,
            max_halts_per_day=circuit_cfg.max_halts_per_day,
        )
        from app.backtesting import BacktestConfig

        bt = settings.backtesting
        self.paper = PaperTracker(
            starting_equity=settings.sizing.paper_equity,
            costs=BacktestConfig(
                commission_pct=bt.default_commission_pct,
                slippage_pct=bt.default_slippage_pct,
                min_volume=bt.min_liquidity_for_execution,
                spread_penalty_threshold_pct=bt.default_spread_threshold_pct,
                spread_penalty_pct=bt.default_spread_penalty_pct,
            ),
        )
        self.state: dict[str, SymbolState] = {}
        self.events: deque[MonitoredEvent] = deque(maxlen=200)
        self.running = False
        self.last_run: datetime | None = None
        self.last_stats: dict[str, Any] = {}
        self.last_regime: str = "unknown"
        self.last_regime_thresholds: dict[str, float] = {}
        self.last_corr_dropped: list[str] = []
        self._feed: Any | None = None
        self.feed_kind: str = "sip"
        self.feed_warning: str | None = None
        self.last_feed_lag_ms: float = 0.0
        self._positions_loaded = False

    def _provider(self) -> Any:
        """Raw provider wrapped in the configured FeedAdapter (SIP default).

        Direct without entitlement falls back to SIP with an explicit
        warning — no code path may silently assume direct data.
        """
        if self._feed is not None:
            return self._feed
        if self.provider is None:
            from app.providers.market_data import YFinanceMarketDataProvider

            self.provider = YFinanceMarketDataProvider()
        from app.feeds import DirectFeed, SipFeed

        feed_cfg = get_settings().feed
        if feed_cfg.kind == "direct" and feed_cfg.direct_entitlement:
            self._feed = DirectFeed(feed_cfg.direct_entitlement)
            self.feed_kind = "direct"
        else:
            if feed_cfg.kind == "direct":
                self.feed_warning = (
                    "direct feed sin entitlement: fallback honesto a SIP "
                    "(latencia retail, sin co-location)"
                )
                log.warning("feed_direct_fallback_sip")
            elif feed_cfg.kind != "sip":
                self.feed_warning = f"feed kind '{feed_cfg.kind}' desconocido: usando SIP"
                log.warning("feed_unknown_kind", kind=feed_cfg.kind)
            self._feed = SipFeed(self.provider, max_fetch_lag_ms=feed_cfg.max_fetch_lag_ms)
            self.feed_kind = "sip"
        return self._feed

    def _feed_lag_ms(self) -> float:
        lag = getattr(self._feed, "last_lag_ms", 0.0)
        try:
            return float(lag)
        except (TypeError, ValueError):
            return 0.0

    async def _fetch_catalyst(self, symbol: str, rvol: float) -> dict[str, Any] | None:
        """Best recent catalyst via AI (heuristic fallback). None when unavailable.

        Cost control: AI is only called when RVOL >= 1.5 suggests something
        is actually happening.
        """
        if self.news.news_provider is None or rvol < 1.5:
            return None
        try:
            since = datetime.now(UTC) - timedelta(hours=48)
            result = await self.news.ingest_news(symbols=[symbol], start=since, limit=5)
        except Exception as exc:
            log.error("catalyst_ingest_failed", symbol=symbol, error=str(exc))
            return None
        best: dict[str, Any] | None = None
        for article in result.articles:
            if article.symbol != symbol:
                continue
            age_h = (datetime.now(UTC) - article.published_at).total_seconds() / 3600
            if age_h > 48:
                continue
            try:
                if self.ai is None:
                    raise RuntimeError("no AI provider")
                analysis = await self.ai.analyze_news(article)
                cand = {
                    "impact": enum_val(analysis.impact),
                    "confidence": float(analysis.confidence),
                    "age_hours": age_h,
                    "primary": bool(analysis.is_primary_source),
                    "summary": analysis.summary or article.headline,
                }
            except Exception:
                heur = await self.detector.detect(article)
                cand = {
                    "impact": enum_val(heur["impact"]),
                    "confidence": float(heur["confidence"]),
                    "age_hours": age_h,
                    "primary": False,
                    "summary": article.headline,
                }
            if best is None or (impact_rank(cand["impact"]), cand["confidence"]) > (
                impact_rank(best["impact"]),
                best["confidence"],
            ):
                best = cand
        return best

    async def _fetch_intraday(self, symbol: str) -> list:
        """5m bars, fail-soft to []."""
        try:
            bars = await self._provider().get_bars(
                symbol, "5m", start=datetime.now(UTC) - timedelta(days=7)
            )
            return list(bars or [])
        except Exception:
            return []

    @staticmethod
    def _group_by_day(bars: list) -> dict[Any, list]:
        """Group by ET session date (delegates to market calendar)."""
        from app.core.market_calendar import group_by_et_day

        return group_by_et_day(bars)

    async def _same_time_rvol(
        self, symbol: str, bars: list | None = None
    ) -> tuple[float | None, str]:
        """Real same-time-of-day RVOL from 5m bars (vs daily proxy fallback).

        Compares today's cumulative 5m volume against the average cumulative
        volume at the same time of day over prior sessions.
        """
        if bars is None:
            bars = await self._fetch_intraday(symbol)
        if not bars:
            return None, "unavailable"
        by_day = self._group_by_day(bars)
        if len(by_day) < 2:
            return None, "unavailable"
        days = sorted(by_day)
        today = by_day[days[-1]]
        from app.core.market_calendar import to_et

        now_t = to_et(datetime.now(UTC)).timetz()
        current_cum = sum(b.volume for b in today if to_et(b.timestamp).timetz() <= now_t)
        hist_cums = []
        for day in days[-6:-1]:
            cum = sum(b.volume for b in by_day[day] if to_et(b.timestamp).timetz() <= now_t)
            if cum > 0:
                hist_cums.append(cum)
        if current_cum <= 0 or len(hist_cums) < 2:
            return None, "unavailable"
        import numpy as _np

        return (
            self.rvol.rvol_same_time_of_day(int(current_cum), _np.array(hist_cums, dtype=float)),
            "intraday-5m",
        )

    @staticmethod
    def _today_vwap(bars: list) -> float | None:
        """Session VWAP from today's 5m bars (latest ET date group)."""
        from app.core.market_calendar import group_by_et_day
        from app.indicators import session_vwap

        if not bars:
            return None
        by_day = group_by_et_day(bars)
        if not by_day:
            return None
        return session_vwap(by_day[max(by_day)])

    @staticmethod
    def _returns_from_bars(bars_5m: list) -> list[float] | None:
        """5m close-to-close returns for the correlation filter (None if <10)."""
        if not bars_5m or len(bars_5m) < 11:
            return None
        try:
            closes = [float(b.close) for b in bars_5m]
        except Exception:
            return None
        rets: list[float] = []
        for prev_c, cur_c in zip(closes, closes[1:], strict=False):
            if prev_c > 0:
                rets.append((cur_c - prev_c) / prev_c)
        return rets if len(rets) >= 10 else None

    async def _fetch_fund_context(
        self, symbol: str, rvol: float
    ) -> tuple[Any | None, Any | None, float | None]:
        """Fundamentals + share stats + float for scoring/risk.

        Fetched when RVOL ≥ 1.0 (cost control on dead names). Fail-soft.
        """
        if self.fundamentals is None or rvol < 1.0:
            return None, None, None
        fundamentals = None
        share_stats = None
        float_shares: float | None = None
        try:
            share_stats = await self.fundamentals.get_share_statistics(symbol)
            if share_stats is not None and share_stats.float_shares:
                float_shares = float(share_stats.float_shares)
        except Exception as exc:
            log.error("share_stats_fetch_failed", symbol=symbol, error=str(exc))
        try:
            fundamentals = await self.fundamentals.get_fundamentals(symbol)
            if float_shares is None and fundamentals is not None and fundamentals.float_shares:
                float_shares = float(fundamentals.float_shares)
        except Exception as exc:
            log.error("fundamentals_fetch_failed", symbol=symbol, error=str(exc))
        return fundamentals, share_stats, float_shares

    async def _fetch_float(self, symbol: str, rvol: float) -> float | None:
        """Float shares for rotation math. Skipped when quiet (cost control)."""
        _, _, float_shares = await self._fetch_fund_context(symbol, rvol)
        return float_shares

    async def _fetch_market(self, symbol: str) -> MarketData:
        """All I/O for one evaluation: quote, daily/intraday bars, VWAP."""
        import numpy as np

        provider = self._provider()
        quote = await provider.get_quote(symbol)
        self.last_feed_lag_ms = self._feed_lag_ms()
        price = quote.last or quote.mid or Decimal("0")
        price_f = float(price)
        spread = quote.spread_pct
        feed_max_lag = get_settings().feed.max_fetch_lag_ms
        feed_lag_stale = self.last_feed_lag_ms > feed_max_lag

        bars = await provider.get_daily_bars(
            symbol, start=datetime.now(UTC) - timedelta(days=400)
        )
        closes = np.array([float(b.close) for b in bars], dtype=float) if bars else np.array([])
        volumes = np.array([b.volume for b in bars], dtype=float) if bars else np.array([])
        if len(closes) >= 2 and closes[-2]:
            change_pct = float((closes[-1] - closes[-2]) / closes[-2] * 100)
        else:
            change_pct = 0.0
        rvol = self.rvol.rvol_daily(int(volumes[-1]) if len(volumes) else 0, volumes[:-1])

        bars_5m = await self._fetch_intraday(symbol)
        vwap_now = self._today_vwap(bars_5m)
        vwap_distance: float | None = None
        if vwap_now and vwap_now > 0:
            vwap_distance = (price_f - vwap_now) / vwap_now * 100
        return MarketData(
            quote=quote,
            price_f=price_f,
            spread=spread,
            feed_lag_stale=feed_lag_stale,
            feed_max_lag_ms=feed_max_lag,
            bars=list(bars or []),
            closes=closes,
            volumes=volumes,
            change_pct=change_pct,
            rvol=rvol,
            bars_5m=bars_5m,
            vwap_now=vwap_now,
            vwap_distance=vwap_distance,
        )

    async def evaluate_symbol(self, symbol: str) -> tuple[SignalEvent, dict[str, Any]]:
        """Score and evaluate signal rules for one symbol (compute only)."""
        import numpy as np

        md = await self._fetch_market(symbol)
        quote = md.quote
        price_f = md.price_f
        spread = md.spread
        feed_lag_stale = md.feed_lag_stale
        feed_max_lag = md.feed_max_lag_ms
        bars = md.bars
        closes = md.closes
        volumes = md.volumes
        change_pct = md.change_pct
        rvol = md.rvol
        bars_5m = md.bars_5m
        vwap_now = md.vwap_now
        vwap_distance = md.vwap_distance

        fundamentals, share_stats, fund_float = await self._fetch_fund_context(symbol, rvol)
        float_int = int(fund_float) if fund_float else None
        assessment = self.risk.assess(
            symbol=symbol,
            quote=quote,
            fundamentals=fundamentals,
            share_stats=share_stats,
            float_shares=float_int,
        )
        blocking = [f.flag_type.value for f in assessment.flags]

        # HaltGuardian: frozen symbols only emit HOLD.
        halted = self.halts.is_frozen(symbol)
        halt_penalty = self.halts.penalty(symbol)

        # DollarRule ($1): track last close; critical blocks BUYs.
        dollar_state = self.dollar_rule.update(symbol, price_f) if price_f > 0 else None
        dollar_blocked, dollar_reason = self.dollar_rule.buy_blocked(symbol)
        dollar_pen = self.dollar_rule.score_penalty(symbol)

        momentum = momentum_score(change_pct)
        technical = None
        divergence: str | None = None
        stoch_cross_dir: str | None = None
        stoch_divergence: str | None = None
        rsi_last: float | None = None
        stoch_k_last: float | None = None
        stoch_d_last: float | None = None
        atr_now: float | None = None
        atr_pct_value: float | None = None
        squeeze_active = False
        if len(closes) >= 15:
            from app.indicators import detect_divergence, rsi, stoch_cross, stochastic

            rsi_vals = rsi(closes, 14)
            rsi_last = float(rsi_vals[-1]) if not np.isnan(rsi_vals[-1]) else None
            technical = float(rsi_vals[-1]) if not np.isnan(rsi_vals[-1]) else None
        if len(closes) >= 30:
            div = detect_divergence(closes, rsi_vals)
            if div["bearish"]:
                divergence = "bearish"
                technical = max(0.0, (technical if technical is not None else 50.0) - 20.0)
            elif div["bullish"]:
                divergence = "bullish"
                technical = min(100.0, (technical if technical is not None else 50.0) + 10.0)
        if len(closes) >= 20 and bars:
            highs = np.array([float(b.high) for b in bars], dtype=float)
            lows = np.array([float(b.low) for b in bars], dtype=float)
            stoch_k, stoch_d = stochastic(highs, lows, closes)
            stoch_k_last = float(stoch_k[-1]) if not np.isnan(stoch_k[-1]) else None
            stoch_d_last = float(stoch_d[-1]) if not np.isnan(stoch_d[-1]) else None
            stoch_cross_dir = stoch_cross(stoch_k, stoch_d)
            stoch_div = detect_divergence(closes, np.nan_to_num(stoch_d, nan=50.0))
            if stoch_div["bearish"] or stoch_cross_dir == "bearish":
                stoch_divergence = "bearish"
                technical = max(0.0, (technical if technical is not None else 50.0) - 10.0)
            elif stoch_div["bullish"] or stoch_cross_dir == "bullish":
                stoch_divergence = "bullish"
                technical = min(100.0, (technical if technical is not None else 50.0) + 5.0)
        if len(closes) >= 15 and bars:
            from app.indicators import atr as _atr

            try:
                atr_vals = _atr(
                    np.array([float(b.high) for b in bars], dtype=float),
                    np.array([float(b.low) for b in bars], dtype=float),
                    closes,
                )
                if not np.isnan(atr_vals[-1]) and closes[-1]:
                    atr_now = float(atr_vals[-1])
                    atr_pct_value = float(atr_now / float(closes[-1]) * 100)
            except Exception:
                atr_now = None
        dollar_volume = price_f * (float(volumes[-1]) if len(volumes) else 0)
        liquidity = liquidity_score(spread)

        # Stealth accumulation (Wyckoff footprints) + climax guard.
        acc_summary: dict[str, Any] | None = None
        climax_info: dict[str, Any] | None = None
        markup_ready = False
        markup_reasons: list[str] = []
        acc_float: float | None = None
        if len(closes) >= 21 and bars:
            from app.signals.accumulation import (
                detect_accumulation,
                detect_climax,
                detect_markup_readiness,
            )

            acc_highs = np.array([float(b.high) for b in bars], dtype=float)
            acc_lows = np.array([float(b.low) for b in bars], dtype=float)
            acc_float = fund_float
            acc = detect_accumulation(acc_highs, acc_lows, closes, volumes, acc_float)
            climax_info = detect_climax(acc_highs, acc_lows, closes, volumes)
            if acc.phase == "accumulation":
                technical = min(100.0, (technical if technical is not None else 50.0) + 5.0)
                acc_summary = {"score": acc.score, "reasons": acc.reasons, "metrics": acc.metrics}
            if climax_info is not None:
                technical = max(0.0, (technical if technical is not None else 50.0) - 10.0)
            markup_ready, markup_reasons = detect_markup_readiness(closes, volumes, acc)
            if markup_ready:
                technical = min(100.0, (technical if technical is not None else 50.0) + 5.0)

        # Donchian breakout gate with live AI catalyst (real same-time
        # RVOL when 5m bars exist, daily-RVOL proxy otherwise).
        donchian_pass: bool | None = None
        donchian_reasons: list[str] = []
        catalyst: dict[str, Any] | None = None
        same_time_rvol: float | None = None
        rvol_source = "daily-proxy"
        freeze_decision = self.filings.get(symbol)
        if len(closes) >= 21 and bars:
            catalyst = await self._fetch_catalyst(symbol, rvol)
            if catalyst is not None:
                same_time_rvol, rvol_source = await self._same_time_rvol(symbol, bars_5m)
                gate_rvol = same_time_rvol if same_time_rvol is not None else rvol
                if same_time_rvol is None:
                    rvol_source = "daily-proxy"
                cfg_gates = get_settings().gates
                prior_highs = np.array([float(b.high) for b in bars[-21:-1]], dtype=float)
                gate_ok, gate_reasons = donchian_entry_gate(
                    DonchianInput(
                        close=price_f,
                        high_20d=float(prior_highs.max()),
                        rvol_same_time=gate_rvol,
                        catalyst_impact=catalyst["impact"],
                        catalyst_confidence=catalyst["confidence"],
                        catalyst_age_hours=catalyst["age_hours"],
                        catalyst_primary_source=catalyst["primary"],
                        spread_pct=spread,
                        dollar_volume=dollar_volume,
                        dilution_frozen=(
                            freeze_decision.freeze_buys
                            if freeze_decision is not None
                            else any(
                                f in blocking
                                for f in ("RECENT_OFFERING", "ACTIVE_ATM", "SHELF_REGISTRATION")
                            )
                        ),
                        halted_recently=self.halts.halts_today(symbol) > 0,
                    ),
                    min_rvol=cfg_gates.donchian_min_rvol,
                    min_catalyst_confidence=cfg_gates.catalyst_min_confidence,
                    max_catalyst_age_hours=cfg_gates.catalyst_max_age_hours,
                    max_spread_pct=cfg_gates.max_spread_pct,
                    min_dollar_volume=cfg_gates.min_dollar_volume,
                )
                donchian_pass = gate_ok
                if gate_ok:
                    donchian_reasons = gate_reasons
                    technical = min(100.0, (technical if technical is not None else 50.0) + 5.0)

        # Prefer same-time RVOL for BUY scoring whenever intraday bars exist.
        if same_time_rvol is None and bars_5m:
            same_time_rvol, st_src = await self._same_time_rvol(symbol, bars_5m)
            if same_time_rvol is not None:
                rvol_source = st_src
        score_rvol = same_time_rvol if same_time_rvol is not None else rvol

        cat_strength = map_catalyst_strength(
            (catalyst or {}).get("impact") if catalyst else None
        )
        fund_score = fundamentals_health_score(fundamentals)
        dq_score = data_quality_from_completeness(
            assessment.data_completeness,
            feed_lag_stale=feed_lag_stale,
        )

        score = self.scoring.score_security(
            rvol=score_rvol,
            catalyst_strength=cat_strength,
            momentum_score=momentum,
            technical_score=technical,
            liquidity_score=liquidity,
            fundamentals_score=fund_score,
            data_quality_score=dq_score,
            risk_flags=assessment.flags,
        )
        # Squeeze annotation (no short side exists: momentum-long only).
        squeeze_note: str | None = None
        if len(closes) >= 5:
            sq = detect_squeeze(closes, volumes if len(volumes) else np.zeros_like(closes))
            squeeze_active = bool(sq.active)
            if sq.active:
                squeeze_note = (
                    "squeeze activo: prohibido cortos (no hay lado corto); solo momentum-long"
                )

        prev = self.state.get(symbol)
        sec_frozen = freeze_decision.freeze_buys if freeze_decision is not None else False
        monitor_cfg = get_settings().monitor
        circuit_on = bool(monitor_cfg.circuit_enabled)
        vetoed = circuit_on and self.breaker.is_vetoed(symbol)
        killed = circuit_on and self.breaker.killed
        inp = SignalInput(
            symbol=symbol,
            price=price_f,
            score=max(0, score.final_score - halt_penalty - dollar_pen),
            rvol=score_rvol,
            change_pct=change_pct,
            vwap_distance_pct=vwap_distance,
            spread_pct=spread,
            blocking_flags=blocking,
            stale=(assessment.stale_data or feed_lag_stale),
            halted=halted,
            buys_frozen=(dollar_blocked or sec_frozen or vetoed or killed),
            prev_score=prev.score if prev else None,
            prev_above_vwap=prev.above_vwap if prev else None,
            prev_blocking_flags=prev.blocking if prev else [],
            dollar_volume=dollar_volume,
            has_catalyst=catalyst is not None,
            donchian_pass=bool(donchian_pass),
            markup_ready=bool(markup_ready),
            squeeze_active=bool(squeeze_active),
            catalyst_impact=(catalyst or {}).get("impact") if catalyst else None,
            catalyst_confidence=(catalyst or {}).get("confidence") if catalyst else None,
            float_shares=acc_float,
        )
        event = evaluate(inp)
        if feed_lag_stale:
            event.reasons.append(
                f"feed {self.feed_kind.upper()} lag {self.last_feed_lag_ms:.0f}ms "
                f"> {feed_max_lag}ms: dato posiblemente obsoleto (STALE, sin señales)"
            )
        if vetoed:
            event.reasons.append("circuito: símbolo vetado 24h tras stop/halt (solo HOLD/SELL)")
        if killed:
            event.reasons.append("kill switch portfolio activo: solo lectura/exits")
        if halted:
            event.reasons.extend(self.halts.freeze_reasons(symbol))
        if freeze_decision is not None and freeze_decision.freeze_buys:
            event.reasons.extend(freeze_decision.reasons)
        if dollar_blocked:
            event.reasons.append(dollar_reason)
        elif dollar_state is not None and dollar_state.level == "warning":
            event.reasons.append(
                f"regla $1 en aviso: {dollar_state.consecutive_below} cierres bajo $1.00"
            )
        if squeeze_note:
            event.reasons.append(squeeze_note)
        if donchian_pass:
            event.reasons.append("ruptura Donchian validada (RVOL + catalizador IA):")
            event.reasons.extend(f"  · {r}" for r in donchian_reasons)
        if divergence == "bearish":
            event.reasons.append("divergencia bajista RSI (el precio sube sin fuerza, precaución)")
        elif divergence == "bullish":
            event.reasons.append("divergencia alcista RSI (el precio cae sin fuerza vendedora)")
        if stoch_divergence == "bearish" or stoch_cross_dir == "bearish":
            event.reasons.append("estocástico bajista (cruce/divergencia, precaución)")
        elif stoch_divergence == "bullish" or stoch_cross_dir == "bullish":
            event.reasons.append("estocástico alcista (cruce/divergencia)")
        if acc_summary is not None:
            event.reasons.append(f"acumulación sigilosa detectada (score {acc_summary['score']}):")
            event.reasons.extend(f"  · {r}" for r in acc_summary["reasons"])
        if climax_info is not None:
            event.reasons.append(
                f"clímax de distribución: volumen {climax_info['volume_multiple']}x "
                f"tras +{climax_info['runup_pct']}% — no perseguir"
            )
        if markup_ready:
            event.reasons.append("base de acumulación + ruptura con volumen: posible markup")
            event.reasons.extend(f"  · {r}" for r in markup_reasons)
        self.state[symbol] = SymbolState(
            score=event.score,
            above_vwap=(vwap_distance > 0 if vwap_distance is not None else None),
            blocking=blocking,
            price=price_f,
            last_signal=event.action.value,
        )
        order_template: dict[str, Any] | None = None
        if event.action == SignalAction.BUY:
            try:
                from app.indicators import atr

                atr_vals = atr(
                    np.array([float(b.high) for b in bars]),
                    np.array([float(b.low) for b in bars]),
                    closes,
                )
                atr_now = float(atr_vals[-1])
                sizing = self.sizer.compute(
                    SizingInput(
                        equity=get_settings().sizing.paper_equity,
                        score=event.score,
                        atr=atr_now,
                        price=price_f,
                        avg_vol_5m=float(volumes[-5:].mean()) if len(volumes) >= 5 else None,
                    )
                )
                cfg_exec = get_settings().execution
                template = build_limit_template(
                    symbol,
                    "buy",
                    max(sizing.shares, 0),
                    price_f,
                    urgency_offset_bps=cfg_exec.urgency_offset_bps,
                    venue=cfg_exec.default_venue,
                    reason=f"señal monitor score {event.score}",
                )
                order_template = {
                    "side": template.side,
                    "order_type": template.order_type,
                    "quantity": template.quantity,
                    "limit_price": str(template.limit_price),
                    "venue": template.venue,
                    "instruction": template.to_manual_instruction(),
                    "sizing_caps": sizing.capped_by,
                }
            except Exception as exc:  # sizing must never break the loop
                log.error("sizing_failed", symbol=symbol, error=str(exc))
        details = {
            "change_pct": round(change_pct, 2),
            "rvol": round(score_rvol, 2),
            "daily_rvol": round(rvol, 2),
            "score_rvol": round(score_rvol, 2),
            "rvol_source": rvol_source,
            "spread_pct": spread,
            "dollar_volume": round(dollar_volume, 2),
            "risk_flags": blocking,
            "rsi_14": round(rsi_last, 1) if rsi_last is not None else None,
            "stoch_k": round(stoch_k_last, 1) if stoch_k_last is not None else None,
            "stoch_d": round(stoch_d_last, 1) if stoch_d_last is not None else None,
            "atr": round(atr_now, 4) if atr_now is not None else None,
            "atr_pct": round(atr_pct_value, 2) if atr_pct_value is not None else None,
            "squeeze_active": squeeze_active,
            "score_breakdown": {
                "raw": score.raw_score,
                "penalty": score.risk_penalty,
                "final": score.final_score,
                "components": dict(score.components),
                "penalties": dict(score.penalties),
                "data_quality": score.data_quality,
                "catalyst_strength": cat_strength,
                "fundamentals_score": fund_score,
                "data_quality_score": dq_score,
                "data_completeness": assessment.data_completeness,
            },
            "rsi_divergence": divergence,
            "stoch_cross": stoch_cross_dir,
            "stoch_divergence": stoch_divergence,
            "halted": halted,
            "dollar_rule": dollar_state.level if dollar_state else "ok",
            "dilution_frozen": sec_frozen,
            "donchian_gate": donchian_pass,
            "catalyst": catalyst,
            "float_shares": float_int,
            "accumulation": acc_summary,
            "climax": climax_info,
            "markup_ready": markup_ready,
            "vwap": round(vwap_now, 4) if vwap_now else None,
            "vwap_distance_pct": round(vwap_distance, 2) if vwap_distance is not None else None,
            "order_template": order_template,
            "stale": (assessment.stale_data or feed_lag_stale),
            "feed_kind": self.feed_kind,
            "feed_lag_ms": round(self.last_feed_lag_ms, 1),
            "feed_warning": self.feed_warning,
            "returns_5m": self._returns_from_bars(bars_5m),
            "vetoed": vetoed,
            "kill_switch": killed,
            "setup": event.setup,
            "matched_setups": list(event.matched_setups),
        }
        return event, details

    def _to_alert(self, event: SignalEvent) -> Alert:
        kind = "COMPRA" if event.action == SignalAction.BUY else "VENTA"
        return Alert(
            symbol=event.symbol,
            score_id=uuid4(),
            score=event.score,
            signal_type=SignalType.MOMENTUM
            if event.action == SignalAction.BUY
            else SignalType.REVERSAL,
            price=Decimal(str(event.price)),
            change_pct=0.0,
            message=f"🔔 POSIBLE {kind} (revisar): {event.symbol} @ ${event.price:.2f} "
            f"[score {event.score}]\n"
            + "\n".join(f"- {r}" for r in event.reasons)
            + "\nSeñal automática para revisión manual, no es recomendación.",
        )

    async def run_once(self, symbols: list[str]) -> list[MonitoredEvent]:
        """Evaluate all symbols concurrently; send alerts for new signals.

        Two phases:
        1. per-symbol evaluation (score/risk/signals, fail-soft per symbol).
        2. round-level gates: market regime -> correlation filter ->
           circuit breakers. Demoted BUYs become HOLD with an explicit
           reason; SELLs (exits) are never blocked by these gates.
        """
        settings = get_settings()
        monitor_cfg = settings.monitor
        try:
            await self.filings.refresh(symbols)
        except Exception as exc:
            log.error("filings_refresh_failed", error=str(exc))
        await self._load_positions()
        sem = asyncio.Semaphore(settings.scanner.max_concurrent_requests)
        evaluated: list[tuple[SignalEvent, dict[str, Any]]] = []

        async def _one(sym: str) -> None:
            async with sem:
                try:
                    evaluated.append(await self.evaluate_symbol(sym))
                except Exception as exc:  # never kill the loop for one symbol
                    log.error("monitor_symbol_failed", symbol=sym, error=str(exc))

        await asyncio.gather(*(_one(s) for s in symbols[: monitor_cfg.max_symbols]))

        # ---- Round gates: regime -> correlation (circuits stay inline; async alerts)
        regime, thresholds = compute_regime(
            evaluated, monitor_cfg, self.halts.halts_today
        )
        self.last_regime = regime.value
        self.last_regime_thresholds = thresholds
        apply_regime_gate(evaluated, regime, thresholds, monitor_cfg.regime_enabled)
        self.last_corr_dropped = apply_correlation_gate(evaluated, monitor_cfg)

        # ---- Circuit breakers: symbol veto + portfolio kill switch ----
        # MtM first (never opens/closes); paper moves run after the gates
        # so a demoted BUY never opens a position.
        for event, _ in evaluated:
            self.paper.mark(event.symbol, event.price)
        circuits_before = len(self.breaker.events)
        was_killed = self.breaker.killed
        if monitor_cfg.circuit_enabled and evaluated:
            changes_all = [float(d.get("change_pct", 0.0)) for _, d in evaluated]
            median_all = float(_np.median(changes_all)) if changes_all else 0.0
            halts_suffered = sum(1 for _, d in evaluated if d.get("halted"))
            paper_active = bool(self.paper.positions or self.paper.closed)
            portfolio_pnl = self.paper.daily_pnl_pct if paper_active else median_all
            kill_ev = self.breaker.check_portfolio(portfolio_pnl, halts_suffered)
            if kill_ev is not None:
                log.error("circuit_kill_switch", reason=kill_ev.reason)
                if not was_killed:
                    # Edge-triggered: one critical broadcast per transition.
                    try:
                        await self.alerts.send_critical(
                            f"kill switch portfolio: {kill_ev.reason} "
                            f"(paper {portfolio_pnl:+.1f}%, halts {halts_suffered})"
                        )
                    except Exception as exc:
                        log.error("critical_alert_failed", error=str(exc))
                for event, _ in evaluated:
                    if event.action == SignalAction.BUY:
                        event.action = SignalAction.HOLD
                        event.reasons = [f"kill switch: {kill_ev.reason}"] + event.reasons
            for event, details in evaluated:
                pos_pnl = self.paper.position_pnl_pct(event.symbol)
                sym_ev = self.breaker.check_symbol(
                    event.symbol,
                    pos_pnl if pos_pnl is not None else float(details.get("change_pct", 0.0)),
                    halted=bool(details.get("halted")),
                )
                if sym_ev is not None:
                    log.error("circuit_symbol_trip", symbol=event.symbol, reason=sym_ev.reason)
                    if event.action == SignalAction.BUY:
                        event.action = SignalAction.HOLD
                        event.reasons = [f"circuito: {sym_ev.reason}"] + event.reasons

        # ---- Position exits + breadth cap ----
        apply_exit_rules(evaluated, monitor_cfg, self.paper.position_pnl_pct)
        buys_capped = apply_breadth_cap(evaluated, monitor_cfg.max_buys_per_round)

        # ---- Paper moves on final actions (post-gates) ----
        closed_this_round: list = []
        for event, details in evaluated:
            if event.action == SignalAction.BUY:
                qty = (details.get("order_template") or {}).get("quantity")
                opened = self.paper.on_buy(
                    event.symbol,
                    event.price,
                    shares=int(qty) if qty else None,
                    spread_pct=details.get("spread_pct"),
                )
                if opened is not None:
                    await self._store_position(opened)
                    event.reasons.append(
                        f"paper: abre {opened.shares} acc a ${opened.entry_price:.4f} "
                        "(all-in, sin piramidar)"
                    )
            elif event.action == SignalAction.SELL:
                trade = self.paper.on_sell(
                    event.symbol, event.price, spread_pct=details.get("spread_pct")
                )
                if trade is not None:
                    await self._drop_position(trade.symbol)
                    closed_this_round.append(trade)
                    event.reasons.append(
                        f"paper: cierra {trade.shares} acc a ${trade.exit_price:.4f} "
                        f"({trade.pnl_pct:+.2f}%, ${trade.pnl_dollars:+.2f})"
                    )

        out: list[MonitoredEvent] = []
        for event, details in evaluated:
            sent = False
            if event.is_actionable:
                key = f"{event.symbol}:{event.action.value}"
                if self.alerts.should_send(key, event.score):
                    alert = self._to_alert(event)
                    results = [await p.send(alert) for p in self.alerts.providers()]
                    sent = any(results)
                    if sent:
                        self.alerts.mark_sent(key, event.score)
            rec = MonitoredEvent(
                symbol=event.symbol,
                action=event.action.value,
                price=event.price,
                score=event.score,
                reasons=event.reasons,
                sent=sent,
                order_template=details.get("order_template"),
                change_pct=float(details.get("change_pct", 0.0)),
                rvol=float(details.get("rvol", 0.0)),
                dollar_volume=float(details.get("dollar_volume", 0.0) or 0.0),
                risk_flags=list(details.get("risk_flags", [])),
                catalyst_summary=(details.get("catalyst") or {}).get("summary"),
                vwap_distance_pct=details.get("vwap_distance_pct"),
                providers=[p.name for p in self.alerts.providers()] if sent else [],
                setup=event.setup,
                matched_setups=list(event.matched_setups),
            )
            out.append(rec)
            self.events.appendleft(rec)

        await self._persist_events(out)
        await self._persist_circuits(self.breaker.events[circuits_before:])
        await self._persist_paper(closed_this_round)
        await self._persist_snapshots(out)
        self.last_run = datetime.now(UTC)
        actionable = sum(1 for e in out if e.action != "hold")
        self.last_stats = {
            "symbols": len(out),
            "signals": actionable,
            "sent": sum(1 for e in out if e.sent),
            "regime": self.last_regime,
            "corr_dropped": list(self.last_corr_dropped),
            "buys_capped": buys_capped,
            "kill_switch": self.breaker.killed,
        }
        log.info("monitor_run_completed", **self.last_stats)
        return out

    async def _persist_events(self, events: list[MonitoredEvent]) -> int:
        return await persist.persist_events(events)

    async def _persist_circuits(self, events: list) -> int:
        return await persist.persist_circuits(events)

    async def _load_positions(self) -> int:
        if self._positions_loaded:
            return 0
        self._positions_loaded = True
        return await persist.load_positions(self.paper)

    async def _store_position(self, pos: Any) -> None:
        await persist.store_position(pos)

    async def _drop_position(self, symbol: str) -> None:
        await persist.drop_position(symbol)

    async def _persist_paper(self, trades: list) -> int:
        return await persist.persist_paper(trades)

    async def _persist_snapshots(self, events: list[MonitoredEvent]) -> int:
        return await persist.persist_snapshots(events, self.last_regime)

    async def load_symbols(self, user_id: str = "default", list_name: str = "default") -> list[str]:
        db = get_db_manager()
        async with db.session() as session:
            repo = WatchlistRepository(session)
            return await repo.symbols(user_id, list_name)

    async def loop_forever(
        self, user_id: str = "default", list_name: str = "default", interval: int | None = None
    ) -> None:
        """Run forever until cancelled; reloads the list each round."""
        interval = interval or get_settings().monitor.interval_seconds
        self.running = True
        log.info("monitor_loop_started", list=list_name, interval=interval)
        try:
            while self.running:
                symbols = await self.load_symbols(user_id, list_name)
                if symbols:
                    await self.run_once(symbols)
                else:
                    log.warning("monitor_empty_list", list=list_name)
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            pass
        finally:
            self.running = False
            log.info("monitor_loop_stopped")

    def status(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "stats": self.last_stats,
            "tracked_symbols": len(self.state),
            "regime": self.last_regime,
            "regime_thresholds": self.last_regime_thresholds,
            "corr_dropped": list(self.last_corr_dropped),
            "kill_switch": self.breaker.killed,
            "vetoed_symbols": sorted(self.breaker.vetoed_symbols),
            "paper": self.paper.summary(),
            "feed": {
                "kind": self.feed_kind,
                "last_lag_ms": round(self.last_feed_lag_ms, 1),
                "warning": self.feed_warning,
            },
            "circuit_events": [
                {
                    "level": e.level,
                    "key": e.key,
                    "reason": e.reason,
                    "timestamp": e.timestamp.isoformat(),
                }
                for e in self.breaker.events[-20:]
            ],
        }

    def recent_events(self, limit: int = 50) -> list[dict[str, Any]]:
        return [
            {
                "symbol": e.symbol,
                "action": e.action,
                "price": e.price,
                "score": e.score,
                "reasons": e.reasons,
                "sent": e.sent,
                "order_template": e.order_template,
                "rvol": e.rvol,
                "change_pct": e.change_pct,
                "dollar_volume": e.dollar_volume,
                "volume": (e.dollar_volume / e.price) if e.price > 0 and e.dollar_volume else 0.0,
                "risk_flags": e.risk_flags,
                "vwap_distance_pct": e.vwap_distance_pct,
                "setup": e.setup,
                "matched_setups": list(e.matched_setups),
                "timestamp": e.timestamp.isoformat(),
            }
            for e in list(self.events)[:limit]
        ]


_service: MonitorService | None = None


def get_monitor_service() -> MonitorService:
    """Process-wide singleton shared by API, radar, and scheduled scans."""
    global _service
    if _service is None:
        from app.providers.fundamentals import YFinanceFundamentalsProvider
        from app.providers.market_data import YFinanceMarketDataProvider

        _service = MonitorService(
            market_data_provider=YFinanceMarketDataProvider(),
            fundamentals_provider=YFinanceFundamentalsProvider(),
        )
    return _service


def reset_monitor_service() -> None:
    """Test helper: drop the singleton so the next get rebuilds it."""
    global _service
    _service = None
