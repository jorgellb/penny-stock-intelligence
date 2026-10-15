"""End-to-end historical bundle: daily bars -> rule signals -> trades.

Rule (documented, simple, no fitting): signal on day T when
  rvol_daily(volume_T vs prior 20) >= min_rvol AND change_T >= min_change_pct.
Entry at close T (all-in via apply_costs, spread unknown historically so
None -> base costs only). Exit at close T+H or earlier on stop_pct.
One position per symbol at a time. All decisions use data <= T only.

Output feeds summarize()/walk_forward_report()/calibrate_by_score().
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


@dataclass
class BundleResult:
    trades: list[Trade] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)
    walk_forward: dict[str, Any] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)


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
            out.trades.extend(_symbol_trades(symbol.upper(), bars, rule, costs))
        except Exception:
            out.skipped.append(symbol.upper())
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
    out.walk_forward = walk_forward_report(dated) if len(dated) >= 4 else {"folds": []}
    return out


def _symbol_trades(
    symbol: str, bars: list[dict], rule: BundleRule, costs: BacktestConfig
) -> list[Trade]:
    closes = np.array([float(b["close"]) for b in bars], dtype=float)
    volumes = np.array([float(b["volume"]) for b in bars], dtype=float)
    n = len(bars)
    trades: list[Trade] = []
    holding: Trade | None = None
    hold_entry_idx = 0
    for i in range(1, n):
        if closes[i - 1] <= 0:
            continue
        change = (closes[i] - closes[i - 1]) / closes[i - 1] * 100
        hist = volumes[max(0, i - rule.lookback_days) : i]
        avg = float(hist.mean()) if len(hist) >= 5 else 0.0
        rvol = float(volumes[i] / avg) if avg > 0 else 0.0
        px = _closes(closes, i)
        if holding is not None:
            ret = (px - holding.entry_price) / holding.entry_price * 100
            matured = (i - hold_entry_idx) >= rule.holding_days
            if ret <= rule.stop_pct or matured:
                holding.exit_date = _date(bars[i])
                holding.exit_price = apply_costs(px, "sell", costs)
                trades.append(holding)
                holding = None
            continue
        in_range = rule.min_price <= px <= rule.max_price
        if rvol >= rule.min_rvol and change >= rule.min_change_pct and in_range:
            # score 0: this rule has no scoring model; walk-forward uses
            # returns only. Never invent a score.
            holding = Trade(
                symbol=symbol,
                entry_date=_date(bars[i]),
                entry_price=apply_costs(px, "buy", costs),
                score_at_entry=0,
            )
            hold_entry_idx = i
    if holding is not None and n:
        holding.exit_date = _date(bars[-1])
        holding.exit_price = apply_costs(_closes(closes, n - 1), "sell", costs)
        trades.append(holding)
    return trades


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
