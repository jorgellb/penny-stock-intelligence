"""Backtest endpoints (historical rvol-momentum bundle, informational)."""

from typing import Any

from fastapi import APIRouter, HTTPException, Query

router = APIRouter()


@router.get("/backtest")
async def get_backtests() -> dict[str, Any]:
    """Runs are not persisted; execute POST /backtest/run for fresh results."""
    return {"results": [], "note": "runs are not persisted; use POST /backtest/run"}


@router.post("/backtest/run")
async def run_backtest(
    symbols: str = Query(..., description="Comma-separated symbols, e.g. ABCD,EFGH"),
    days: int = Query(120, ge=30, le=730),
    min_rvol: float = Query(2.0, ge=0.5),
    min_change_pct: float = Query(5.0, ge=0.0),
    holding_days: int = Query(5, ge=1, le=60),
    stop_pct: float = Query(-8.0, le=0.0),
    target_pct: float | None = Query(None, gt=0.0),
    min_score: int = Query(0, ge=0, le=100),
    entry: str = Query("next_open", pattern="^(next_open|close)$"),
) -> dict[str, Any]:
    """Run the historical bundle over symbols (daily bars, yfinance)."""
    from app.backtesting import BacktestConfig
    from app.backtesting.history import BundleRule, fetch_series, run_bundle
    from app.config import get_settings

    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not syms:
        raise HTTPException(status_code=400, detail="empty symbol list")
    bt = get_settings().backtesting
    series = await fetch_series(syms[:50], days=days)
    if not series:
        raise HTTPException(status_code=503, detail="no usable history fetched")
    result = run_bundle(
        series,
        rule=BundleRule(
            min_rvol=min_rvol,
            min_change_pct=min_change_pct,
            holding_days=holding_days,
            stop_pct=stop_pct,
            target_pct=target_pct,
            min_score=min_score,
            entry=entry,
        ),
        costs=BacktestConfig(
            commission_pct=bt.default_commission_pct,
            slippage_pct=bt.default_slippage_pct,
            min_volume=bt.min_liquidity_for_execution,
            spread_penalty_threshold_pct=bt.default_spread_threshold_pct,
            spread_penalty_pct=bt.default_spread_penalty_pct,
        ),
    )
    return {
        "symbols": sorted(series),
        "skipped": result.skipped,
        "metrics": result.metrics,
        "walk_forward": result.walk_forward,
        "equity_curve": result.equity_curve,
        "calibration": result.calibration,
        "trades": [
            {
                "symbol": t.symbol,
                "entry": t.entry_date.isoformat() if t.entry_date else None,
                "exit": t.exit_date.isoformat() if t.exit_date else None,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "return_pct": t.return_pct,
                "score": t.score_at_entry,
                "exit_reason": result.exit_reasons.get(
                    f"{t.symbol}:{t.entry_date.isoformat()}" if t.entry_date else ""
                ),
            }
            for t in result.trades
        ],
        "disclaimer": "informational only; past returns do not predict future ones",
    }


@router.get("/backtest/{backtest_id}")
async def get_backtest_result(backtest_id: str) -> dict[str, Any]:
    """Runs are not persisted; re-execute POST /backtest/run."""
    raise HTTPException(
        status_code=404,
        detail=f"unknown backtest {backtest_id}: runs are not persisted",
    )
