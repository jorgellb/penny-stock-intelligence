"""Point-in-time backtest engine with slippage/commission/liquidity guards."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np


@dataclass
class BacktestConfig:
    commission_pct: float = 0.001
    slippage_pct: float = 0.01
    min_volume: int = 500000
    # Illiquidity spread term (docs/NASDAQ_NYSE_ADAPTATION.md §5): when the
    # quoted spread at entry/exit exceeds the threshold, crossing it costs
    # roughly half the spread on top of base slippage. Modelled as a flat
    # extra penalty per side (conservative, explicit, configurable).
    spread_penalty_threshold_pct: float = 3.0
    spread_penalty_pct: float = 0.01


@dataclass
class Trade:
    symbol: str
    entry_date: datetime
    entry_price: float
    exit_date: datetime | None = None
    exit_price: float | None = None
    score_at_entry: int = 0

    @property
    def return_pct(self) -> float | None:
        if self.exit_price is None or not self.entry_price:
            return None
        return (self.exit_price - self.entry_price) / self.entry_price * 100


@dataclass
class BacktestResult:
    trades: list[Trade] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)


def apply_costs(
    price: float, side: str, cfg: BacktestConfig, spread_pct: float | None = None
) -> float:
    """Adjust price for commission + slippage + illiquidity spread term.

    `spread_pct=None` (unknown spread) keeps legacy behavior: base costs
    only, no invented penalty. Pass the measured quote spread to model
    the extra crossing cost of wide-spread penny stocks.
    """
    extra = (
        cfg.spread_penalty_pct
        if spread_pct is not None and spread_pct > cfg.spread_penalty_threshold_pct
        else 0.0
    )
    total = cfg.slippage_pct + cfg.commission_pct + extra
    adj = price * (1 + total) if side == "buy" else price * (1 - total)
    return round(adj, 4)


def summarize(trades: list[Trade]) -> dict[str, float]:
    rets = np.array([t.return_pct for t in trades if t.return_pct is not None], dtype=float)
    if rets.size == 0:
        return {
            "number_of_signals": 0,
            "win_rate": 0.0,
            "average_return": 0.0,
            "median_return": 0.0,
            "expectancy": 0.0,
            "profit_factor": 0.0,
            "max_drawdown": 0.0,
        }
    wins = rets[rets > 0]
    losses = rets[rets <= 0]
    profit_factor = (
        float(wins.sum() / abs(losses.sum()))
        if losses.sum() != 0
        else float("inf")
        if wins.sum() > 0
        else 0.0
    )
    cum = np.cumsum(rets)
    peak = np.maximum.accumulate(cum)
    dd = float((peak - cum).max()) if cum.size else 0.0
    return {
        "number_of_signals": float(rets.size),
        "win_rate": float((rets > 0).mean() * 100),
        "average_return": float(rets.mean()),
        "median_return": float(np.median(rets)),
        "expectancy": float(rets.mean()),
        "profit_factor": profit_factor,
        "max_drawdown": dd,
    }


def post_signal_returns(
    entry_price: float,
    bars_5m: list[float] | None = None,
    close_price: float | None = None,
    next_day: float | None = None,
) -> dict[str, float | None]:
    def pct(px: float | None) -> float | None:
        if px is None or not entry_price:
            return None
        return (px - entry_price) / entry_price * 100

    out = {"return_close": pct(close_price), "return_next_day": pct(next_day)}
    if bars_5m:
        for i, label in [
            (1, "return_5m"),
            (3, "return_15m"),
            (6, "return_30m"),
            (12, "return_60m"),
        ]:
            out[label] = pct(bars_5m[i - 1] if len(bars_5m) >= i else None)
    return out


@dataclass
class WalkForwardFold:
    """One expanding-window fold: train on the past, test the next block."""

    fold: int
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    n_train: int
    n_test: int
    metrics: dict[str, float] = field(default_factory=dict)


def walk_forward_splits(
    items: list[dict], n_splits: int = 3, date_key: str = "date"
) -> list[tuple[list[dict], list[dict]]]:
    """Chronological expanding-window splits (no look-ahead by construction).

    Items are sorted by `date_key`; fold k trains on the first k blocks and
    tests block k+1. Each item needs a parseable date; items without one
    are dropped (reported via the fold counts, never silently used).
    """
    from datetime import datetime as _dt

    def _parse(v: object) -> datetime | None:
        if isinstance(v, datetime):
            return v
        try:
            return _dt.fromisoformat(str(v))
        except (ValueError, TypeError):
            return None

    dated = [(d, _parse(d.get(date_key))) for d in items]
    pairs: list[tuple[dict, datetime]] = [(d, ts) for d, ts in dated if ts is not None]
    pairs.sort(key=lambda pair: pair[1])
    clean = [d for d, _ in pairs]
    n = len(clean)
    if n_splits < 1 or n < n_splits + 1:
        return []
    block = n // (n_splits + 1)
    folds: list[tuple[list[dict], list[dict]]] = []
    for k in range(1, n_splits + 1):
        cut = k * block
        train, test = clean[:cut], clean[cut : cut + block]
        if train and test:
            folds.append((train, test))
    return folds


def walk_forward_report(
    items: list[dict],
    n_splits: int = 3,
    date_key: str = "date",
    return_key: str = "return_pct",
) -> dict[str, Any]:
    """Per-fold summarize() on out-of-sample blocks + aggregate means.

    This checks whether a rule carried information across time — it never
    optimizes parameters (that would need a separate train/validation step
    per fold). Returns are informational, not profit claims.
    """
    folds: list[WalkForwardFold] = []
    for i, (train, test) in enumerate(walk_forward_splits(items, n_splits, date_key)):
        trades = [
            Trade(
                symbol=str(t.get("symbol", "?")),
                entry_date=datetime.now(),
                entry_price=1.0,
                exit_date=datetime.now(),
                exit_price=1.0 * (1 + float(t.get(return_key, 0.0)) / 100),
                score_at_entry=int(t.get("score", 0)),
            )
            for t in test
            if t.get(return_key) is not None
        ]
        metrics = summarize(trades)
        folds.append(
            WalkForwardFold(
                fold=i + 1,
                train_start=str(train[0].get(date_key)),
                train_end=str(train[-1].get(date_key)),
                test_start=str(test[0].get(date_key)),
                test_end=str(test[-1].get(date_key)),
                n_train=len(train),
                n_test=len(test),
                metrics=metrics,
            )
        )
    agg: dict[str, Any] = {"folds": [f.__dict__ for f in folds]}
    if folds:
        keys = ["win_rate", "average_return", "median_return", "expectancy"]
        agg["mean"] = {k: float(np.mean([f.metrics.get(k, 0.0) for f in folds])) for k in keys}
    return agg


def calibrate_by_score(
    items: list[dict],
    bands: tuple[int, ...] = (50, 60, 70, 80, 90, 100),
    return_key: str = "return_pct",
) -> dict[str, dict[str, float]]:
    """Subsequent-return distribution per score band (informational only).

    Never a probability of winning: it only shows how past signals in each
    band behaved afterwards.
    """
    out: dict[str, dict[str, float]] = {}
    for lo, hi in zip(bands, bands[1:], strict=False):
        rets = [
            float(t[return_key])
            for t in items
            if lo <= float(t.get("score", -1)) < (hi if hi < 100 else 101)
            and t.get(return_key) is not None
        ]
        arr = np.array(rets, dtype=float)
        out[f"{lo}-{hi}"] = {
            "n": float(arr.size),
            "average_return": float(arr.mean()) if arr.size else 0.0,
            "median_return": float(np.median(arr)) if arr.size else 0.0,
            "win_rate": float((arr > 0).mean() * 100) if arr.size else 0.0,
        }
    return out
