"""End-to-end historical bundle: daily bars -> rule signals -> trades.

Rule (documented, simple, no fitting): signal on day T when
  rvol_daily(volume_T vs prior 20) >= min_rvol AND change_T >= min_change_pct
  (and optionally the point-in-time score >= min_score).

Execution realism:
- entry="next_open" (default): the signal is only known at the close of T,
  so the fill is the open of T+1 (gaps included). entry="close" keeps the
  legacy close-of-T fill.
- Stops/targets are checked against each bar's low/high when available;
  a gap through the level fills at the open (worse), never at the level.
- Exit at the close of T+H otherwise. Costs via apply_costs on both sides.
One position per symbol at a time. All decisions use data <= T only.

Each signal carries a point-in-time score (momentum + volume + technical
sub-scores computed on bars <= T) so results can be calibrated by score
band. Output feeds summarize()/walk_forward_report()/calibrate_by_score().
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np

from app.backtesting import (
    BacktestConfig,
    Trade,
    apply_costs,
    calibrate_by_score,
    summarize,
    walk_forward_report,
)


@dataclass
class BundleRule:
    min_rvol: float = 2.0
    min_change_pct: float = 5.0
    lookback_days: int = 20
    holding_days: int = 5
    stop_pct: float = -8.0
    min_price: float = 0.10
    max_price: float = 5.00
    entry: str = "next_open"  # next_open | close
    target_pct: float | None = None  # e.g. 20.0 = take profit at +20%
    min_score: int = 0
    position_fraction: float = 0.2  # equity fraction per trade (equity curve)


@dataclass
class BundleResult:
    trades: list[Trade] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)
    walk_forward: dict[str, Any] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)
    equity_curve: list[dict[str, Any]] = field(default_factory=list)
    calibration: dict[str, dict[str, float]] = field(default_factory=dict)
    exit_reasons: dict[str, str] = field(default_factory=dict)


def _closes(closes: np.ndarray, i: int) -> float:
    return float(closes[i])


def run_bundle(
    series: dict[str, list[dict]],
    rule: BundleRule | None = None,
    costs: BacktestConfig | None = None,
) -> BundleResult:
    """Run the rule over {symbol: [bars]}. Bars need date/close/volume (+open/high/low optional)."""
    rule = rule or BundleRule()
    costs = costs or BacktestConfig()
    out = BundleResult()
    for symbol, bars in series.items():
        try:
            trades, reasons = _symbol_trades(symbol.upper(), bars, rule, costs)
            out.trades.extend(trades)
            out.exit_reasons.update(reasons)
        except Exception:
            out.skipped.append(symbol.upper())
    out.trades.sort(key=lambda t: t.entry_date)
    dated = [
        {
            "date": t.entry_date.isoformat(),
            "symbol": t.symbol,
            "score": t.score_at_entry,
            "return_pct": t.return_pct,
        }
        for t in out.trades
        if t.return_pct is not None
    ]
    out.metrics = summarize(out.trades)
    out.metrics.update(extended_metrics(out.trades, rule.position_fraction))
    out.equity_curve = equity_curve(out.trades, rule.position_fraction)
    out.walk_forward = walk_forward_report(dated) if len(dated) >= 4 else {"folds": []}
    out.calibration = calibrate_by_score(dated, bands=(0, 40, 50, 60, 70, 80, 100))
    return out


def equity_curve(trades: list[Trade], fraction: float = 0.2) -> list[dict[str, Any]]:
    """Compounded equity (start 100) risking `fraction` of equity per trade, by exit date."""
    closed = sorted(
        (t for t in trades if t.return_pct is not None and t.exit_date is not None),
        key=lambda t: t.exit_date,  # type: ignore[arg-type,return-value]
    )
    eq = 100.0
    curve: list[dict[str, Any]] = []
    for t in closed:
        eq *= 1 + fraction * float(t.return_pct or 0.0) / 100
        curve.append(
            {
                "date": t.exit_date.isoformat() if t.exit_date else None,
                "equity": round(eq, 4),
                "symbol": t.symbol,
                "return_pct": round(float(t.return_pct or 0.0), 3),
            }
        )
    return curve


def extended_metrics(trades: list[Trade], fraction: float = 0.2) -> dict[str, float]:
    """Payoff, average win/loss, per-trade Sharpe, compounded return and drawdown."""
    rets = np.array([t.return_pct for t in trades if t.return_pct is not None], dtype=float)
    if rets.size == 0:
        return {
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "payoff_ratio": 0.0,
            "sharpe_per_trade": 0.0,
            "total_return_compounded": 0.0,
            "max_drawdown_equity": 0.0,
            "best_trade": 0.0,
            "worst_trade": 0.0,
        }
    wins, losses = rets[rets > 0], rets[rets <= 0]
    avg_win = float(wins.mean()) if wins.size else 0.0
    avg_loss = float(losses.mean()) if losses.size else 0.0
    curve = [c["equity"] for c in equity_curve(trades, fraction)]
    eq = np.array([100.0] + curve)
    peak = np.maximum.accumulate(eq)
    dd = float(((peak - eq) / peak).max() * 100)
    std = float(rets.std(ddof=1)) if rets.size > 1 else 0.0
    return {
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "payoff_ratio": float(avg_win / abs(avg_loss)) if avg_loss else 0.0,
        "sharpe_per_trade": float(rets.mean() / std) if std > 0 else 0.0,
        "total_return_compounded": float(eq[-1] - 100.0),
        "max_drawdown_equity": dd,
        "best_trade": float(rets.max()),
        "worst_trade": float(rets.min()),
    }


def _point_in_time_score(
    closes: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    change: float,
    rvol: float,
    i: int,
) -> int:
    """Score at bar i using bars <= i only (momentum, volume, technical)."""
    from app.indicators import atr as _atr
    from app.scoring.components import (
        momentum_component,
        technical_component,
        volume_component,
    )

    lo = max(0, i - 120)
    c, h, low = closes[lo : i + 1], highs[lo : i + 1], lows[lo : i + 1]
    atr_pct = None
    if len(c) >= 15:
        a = _atr(h, low, c)
        if not np.isnan(a[-1]) and c[-1] > 0:
            atr_pct = float(a[-1] / c[-1] * 100)
    roc5 = float((c[-1] / c[-6] - 1) * 100) if len(c) >= 6 and c[-6] > 0 else None
    mom = momentum_component(change, atr_pct, roc5, None)
    vol = volume_component(rvol)
    tv = technical_component(c, h, low)
    tech = tv.score if tv is not None else 50.0
    # Same relative weights as the live engine (20/20/15), normalized to 100.
    return int(round((mom * 20 + vol * 20 + tech * 15) / 55))


def _symbol_trades(
    symbol: str, bars: list[dict], rule: BundleRule, costs: BacktestConfig
) -> tuple[list[Trade], dict[str, str]]:
    closes = np.array([float(b["close"]) for b in bars], dtype=float)
    volumes = np.array([float(b["volume"]) for b in bars], dtype=float)
    opens = np.array([float(b.get("open", b["close"])) for b in bars], dtype=float)
    highs = np.array([float(b.get("high", b["close"])) for b in bars], dtype=float)
    lows = np.array([float(b.get("low", b["close"])) for b in bars], dtype=float)
    has_range = all("high" in b and "low" in b for b in bars)
    n = len(bars)
    trades: list[Trade] = []
    reasons: dict[str, str] = {}
    holding: Trade | None = None
    raw_entry = 0.0
    hold_entry_idx = 0
    pending: tuple[int, int] | None = None  # (signal idx, score) awaiting next open

    def _close_trade(i: int, px: float, why: str) -> None:
        nonlocal holding
        assert holding is not None
        holding.exit_date = _date(bars[i])
        holding.exit_price = apply_costs(px, "sell", costs)
        trades.append(holding)
        reasons[f"{symbol}:{holding.entry_date.isoformat()}"] = why
        holding = None

    def _open_trade(i: int, px: float, score: int) -> None:
        nonlocal holding, raw_entry, hold_entry_idx
        holding = Trade(
            symbol=symbol,
            entry_date=_date(bars[i]),
            entry_price=apply_costs(px, "buy", costs),
            score_at_entry=score,
        )
        raw_entry = px
        hold_entry_idx = i

    for i in range(1, n):
        if pending is not None and holding is None:
            _, score = pending
            pending = None
            if rule.min_price <= opens[i] <= rule.max_price * 1.5:
                _open_trade(i, float(opens[i]), score)
        if closes[i - 1] <= 0:
            continue
        change = (closes[i] - closes[i - 1]) / closes[i - 1] * 100
        hist = volumes[max(0, i - rule.lookback_days) : i]
        avg = float(hist.mean()) if len(hist) >= 5 else 0.0
        rvol = float(volumes[i] / avg) if avg > 0 else 0.0
        px = _closes(closes, i)
        if holding is not None:
            stop_px = raw_entry * (1 + rule.stop_pct / 100)
            tgt_px = raw_entry * (1 + rule.target_pct / 100) if rule.target_pct else None
            same_bar = i == hold_entry_idx and rule.entry == "close"
            if not same_bar:
                if has_range:
                    if lows[i] <= stop_px:
                        _close_trade(i, min(float(opens[i]), stop_px), "stop")
                        continue
                    if tgt_px is not None and highs[i] >= tgt_px:
                        _close_trade(i, max(float(opens[i]), tgt_px), "target")
                        continue
                else:
                    ret = (px - raw_entry) / raw_entry * 100
                    if ret <= rule.stop_pct:
                        _close_trade(i, px, "stop")
                        continue
                    if rule.target_pct and ret >= rule.target_pct:
                        _close_trade(i, px, "target")
                        continue
                if (i - hold_entry_idx) >= rule.holding_days:
                    _close_trade(i, px, "time")
            continue
        in_range = rule.min_price <= px <= rule.max_price
        if rvol >= rule.min_rvol and change >= rule.min_change_pct and in_range:
            score = _point_in_time_score(closes, highs, lows, change, rvol, i)
            if score < rule.min_score:
                continue
            if rule.entry == "close":
                _open_trade(i, px, score)
            else:
                pending = (i, score)
    if holding is not None and n:
        _close_trade(n - 1, _closes(closes, n - 1), "end")
    return trades, reasons


def _date(bar: dict) -> datetime:
    d = bar.get("date")
    if isinstance(d, datetime):
        return d
    try:
        return datetime.fromisoformat(str(d))
    except (ValueError, TypeError):
        return datetime.now(UTC)


async def fetch_series(
    symbols: list[str],
    days: int = 120,
    provider: Any | None = None,
) -> dict[str, list[dict]]:
    """Fetch daily OHLCV per symbol, fail-soft (skipped symbols reported)."""
    if provider is None:
        from app.providers.market_data import YFinanceMarketDataProvider

        provider = YFinanceMarketDataProvider()
    start = datetime.now(UTC) - timedelta(days=days * 2)  # margin for weekends/holidays
    out: dict[str, list[dict]] = {}
    for sym in dict.fromkeys(s.upper() for s in symbols):
        try:
            bars = await provider.get_daily_bars(sym, start=start)
            rows = [
                {
                    "date": b.date.isoformat() if hasattr(b.date, "isoformat") else str(b.date),
                    "open": float(b.open),
                    "high": float(b.high),
                    "low": float(b.low),
                    "close": float(b.close),
                    "volume": int(b.volume),
                }
                for b in (bars or [])[-days:]
            ]
            if len(rows) >= 8:
                out[sym] = rows
        except Exception:
            continue
    return out
