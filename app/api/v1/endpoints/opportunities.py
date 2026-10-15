"""Opportunity radar API — ranked movers + multi-setup status."""

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.database import get_session
from app.jobs.monitor import get_monitor_service
from app.scanners.opportunity import rank_opportunities
from app.signals.setups import SETUP_PRIORITY

router = APIRouter()


@router.get("/opportunities")
async def list_opportunities(
    limit: int = Query(40, ge=1, le=200),
) -> dict[str, Any]:
    """Ranked opportunities from the latest monitor evaluations.

    Uses live monitor event/details cache — run a monitor or radar job first
    for fresh data. Falls back to ranking recent BUY/HOLD events by score×RVOL.
    """
    svc = get_monitor_service()
    events = svc.recent_events(limit=500)
    rows: list[dict[str, Any]] = []
    for e in events:
        rows.append(
            {
                "symbol": e.get("symbol"),
                "price": e.get("price"),
                "change_pct": e.get("change_pct"),
                "rvol": e.get("rvol"),
                "volume": e.get("volume") or 0,
                "score_proxy": e.get("score"),
            }
        )
    cfg = get_settings().monitor
    ranked = rank_opportunities(
        rows,
        min_score=float(cfg.radar_min_score),
        min_rvol=float(cfg.radar_min_rvol),
        min_change_pct=float(cfg.radar_min_change_pct),
        max_results=limit,
    )
    return {
        "count": len(ranked),
        "opportunities": [
            {
                "symbol": o.symbol,
                "rank_score": o.rank_score,
                "change_pct": o.change_pct,
                "rvol": o.rvol,
                "price": o.price,
                "dollar_volume": o.dollar_volume,
                "setups_hint": o.setups_hint,
                "reasons": o.reasons,
            }
            for o in ranked
        ],
        "setups_available": sorted(SETUP_PRIORITY.keys(), key=lambda k: -SETUP_PRIORITY[k]),
        "radar_list": cfg.radar_list_name,
    }


@router.get("/opportunities/setups")
async def list_setups() -> dict[str, Any]:
    """Describe enabled BUY playbooks and priorities."""
    cfg = get_settings().monitor
    toggles = cfg.setups.model_dump()
    return {
        "enabled": toggles,
        "priority": SETUP_PRIORITY,
        "thresholds": {
            "momentum_vwap": {
                "min_score": cfg.buy_min_score,
                "min_rvol": cfg.buy_min_rvol,
            },
            "gap_and_go": {
                "min_change_pct": cfg.gap_min_change_pct,
                "min_score": cfg.gap_min_score,
                "min_rvol": cfg.gap_min_rvol,
            },
            "donchian_breakout": {"min_score": cfg.donchian_min_score},
            "accumulation_markup": {
                "min_score": cfg.markup_min_score,
                "min_rvol": cfg.markup_min_rvol,
            },
            "squeeze_continuation": {
                "min_score": cfg.squeeze_min_score,
                "min_rvol": cfg.squeeze_min_rvol,
            },
            "catalyst_impulse": {
                "min_score": cfg.catalyst_min_score,
                "min_rvol": cfg.catalyst_min_rvol,
                "min_confidence": cfg.catalyst_setup_min_confidence,
            },
        },
    }


@router.post("/opportunities/radar/run")
async def run_radar(
    user_id: str = Query("default"),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Scan recent monitor state, rank opportunities, sync into radar list."""
    from app.jobs.radar import run_radar_pass

    result = await run_radar_pass(session=session, user_id=user_id)
    return result
