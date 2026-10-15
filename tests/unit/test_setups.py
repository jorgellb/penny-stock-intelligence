"""Tests for multi-setup signal engine and opportunity radar."""

from app.config import MonitorConfig, SetupToggles
from app.scanners.opportunity import rank_opportunities
from app.signals import SignalAction, SignalInput, evaluate
from app.signals.setups import best_setup, match_setups


def _only(**enabled: bool) -> SetupToggles:
    """Enable only the named setups (others off)."""
    base = {k: False for k in SetupToggles.model_fields}
    base.update(enabled)
    return SetupToggles(**base)


def _base(**overrides: object) -> SignalInput:
    data: dict = {
        "symbol": "ABCD",
        "price": 2.20,
        "score": 78,
        "rvol": 5.8,
        "change_pct": 3.0,
        "vwap_distance_pct": 0.5,
        "spread_pct": 1.2,
        "blocking_flags": [],
        "stale": False,
    }
    data.update(overrides)
    return SignalInput(**data)


def test_classic_momentum_still_buys() -> None:
    event = evaluate(_base())
    assert event.action == SignalAction.BUY
    assert event.setup == "momentum_vwap"
    assert "momentum_vwap" in event.matched_setups


def test_gap_and_go_fires_without_full_momentum_score() -> None:
    cfg = MonitorConfig(buy_min_score=70, setups=_only(gap_and_go=True))
    match = best_setup(_base(score=62, change_pct=8.0, rvol=3.0), cfg)
    assert match is not None
    assert match.name == "gap_and_go"


def test_donchian_setup() -> None:
    cfg = MonitorConfig(setups=_only(donchian_breakout=True))
    match = best_setup(_base(score=68, donchian_pass=True, rvol=3.5), cfg)
    assert match is not None
    assert match.name == "donchian_breakout"


def test_accumulation_markup_setup() -> None:
    cfg = MonitorConfig(setups=_only(accumulation_markup=True))
    match = best_setup(_base(score=66, markup_ready=True, rvol=2.0), cfg)
    assert match is not None
    assert match.name == "accumulation_markup"


def test_squeeze_continuation_setup() -> None:
    cfg = MonitorConfig(setups=_only(squeeze_continuation=True))
    match = best_setup(
        _base(score=66, squeeze_active=True, rvol=3.0, vwap_distance_pct=1.0), cfg
    )
    assert match is not None
    assert match.name == "squeeze_continuation"


def test_catalyst_impulse_setup() -> None:
    cfg = MonitorConfig(setups=_only(catalyst_impulse=True))
    match = best_setup(
        _base(
            score=62,
            rvol=3.0,
            has_catalyst=True,
            catalyst_impact="high",
            catalyst_confidence=0.85,
        ),
        cfg,
    )
    assert match is not None
    assert match.name == "catalyst_impulse"


def test_multiple_setups_pick_highest_priority() -> None:
    matches = match_setups(
        _base(
            score=80,
            rvol=5.0,
            change_pct=10.0,
            donchian_pass=True,
            has_catalyst=True,
            catalyst_impact="high",
            catalyst_confidence=0.9,
        ),
        MonitorConfig(),
    )
    assert matches[0].name == "donchian_breakout"
    assert "gap_and_go" in [m.name for m in matches]


def test_hard_block_still_blocks_all_setups() -> None:
    event = evaluate(
        _base(
            blocking_flags=["RECENT_OFFERING"],
            prev_blocking_flags=["RECENT_OFFERING"],
            donchian_pass=True,
        )
    )
    assert event.action == SignalAction.HOLD


def test_rank_opportunities_orders_by_composite() -> None:
    rows = [
        {
            "symbol": "AAA",
            "price": 1.5,
            "change_pct": 3.0,
            "rvol": 2.0,
            "volume": 100_000,
            "score_proxy": 60,
        },
        {
            "symbol": "BBB",
            "price": 2.0,
            "change_pct": 12.0,
            "rvol": 6.0,
            "volume": 2_000_000,
            "score_proxy": 90,
        },
        {"symbol": "CCC", "price": 0.8, "change_pct": 1.0, "rvol": 1.0, "volume": 10_000},
    ]
    ranked = rank_opportunities(rows, min_score=50, min_rvol=1.5, min_change_pct=2.0)
    assert [o.symbol for o in ranked] == ["BBB", "AAA"]
    assert "gap_and_go" in ranked[0].setups_hint
    assert ranked[0].dollar_volume == 4_000_000.0


def test_rank_opportunities_dollar_volume_bonus() -> None:
    rows = [
        {
            "symbol": "LIQ",
            "price": 2.0,
            "change_pct": 5.0,
            "rvol": 3.0,
            "volume": 600_000,
            "score_proxy": 70,
        },
        {
            "symbol": "DRY",
            "price": 2.0,
            "change_pct": 5.0,
            "rvol": 3.0,
            "volume": 50_000,
            "score_proxy": 70,
        },
    ]
    ranked = rank_opportunities(rows, min_score=50, min_rvol=1.5, min_change_pct=2.0)
    assert ranked[0].symbol == "LIQ"
    assert ranked[0].rank_score > ranked[1].rank_score
