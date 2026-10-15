"""Multi-setup opportunity detectors.

Each setup is an independent, explainable playbook. A symbol may match
several; ``evaluate`` picks the highest-priority match for the BUY action
and tags the event with ``setup``.

Setups never replace risk blocks (halt / dilution / stale / frozen).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class SetupMatch:
    """One matched playbook with human-readable reasons."""

    name: str
    priority: int
    reasons: list[str] = field(default_factory=list)


# Higher priority wins when several setups fire on the same bar.
SETUP_PRIORITY: dict[str, int] = {
    "donchian_breakout": 100,
    "catalyst_impulse": 90,
    "gap_and_go": 85,
    "squeeze_continuation": 80,
    "accumulation_markup": 75,
    "momentum_vwap": 70,
}


def _enabled(cfg: Any, name: str) -> bool:
    setups = getattr(cfg, "setups", None)
    if setups is None:
        return True
    return bool(getattr(setups, name, True))


def hard_blocked(inp: Any, cfg: Any) -> bool:
    """Shared risk vetoes — no setup may override these."""
    if inp.stale or inp.halted or inp.buys_frozen:
        return True
    return bool(set(inp.blocking_flags) & set(cfg.block_flags))


def global_entry_blocked(inp: Any, cfg: Any) -> bool:
    """Optional monitor-wide entry gates (apply to every setup when set)."""
    min_dollar = getattr(cfg, "buy_min_dollar_volume", None)
    if min_dollar is not None and (inp.dollar_volume or 0.0) < min_dollar:
        return True
    min_change = getattr(cfg, "buy_min_change_pct", None)
    if min_change is not None and inp.change_pct < min_change:
        return True
    if getattr(cfg, "buy_require_catalyst", False) and not inp.has_catalyst:
        return True
    return False


def setup_momentum_vwap(inp: Any, cfg: Any) -> list[str] | None:
    """Classic monitor setup: score + RVOL + VWAP + spread."""
    reasons: list[str] = []
    if inp.score < cfg.buy_min_score:
        return None
    reasons.append(f"score {inp.score} >= {cfg.buy_min_score}")
    if inp.rvol < cfg.buy_min_rvol:
        return None
    reasons.append(f"RVOL {inp.rvol:.1f}x >= {cfg.buy_min_rvol}x")
    if inp.spread_pct is not None and inp.spread_pct > cfg.buy_max_spread_pct:
        return None
    if inp.spread_pct is not None:
        reasons.append(f"spread {inp.spread_pct:.2f}% <= {cfg.buy_max_spread_pct}%")
    if cfg.buy_require_above_vwap:
        if inp.vwap_distance_pct is None:
            reasons.append("VWAP n/d (chequeo omitido)")
        elif inp.vwap_distance_pct <= 0:
            return None
        else:
            reasons.append(f"sobre VWAP (+{inp.vwap_distance_pct:.2f}%)")
    min_dollar = getattr(cfg, "buy_min_dollar_volume", None)
    if min_dollar is not None and (inp.dollar_volume or 0.0) < min_dollar:
        return None
    if min_dollar is not None:
        reasons.append(f"dollar volume ${inp.dollar_volume:,.0f} >= ${min_dollar:,.0f}")
    min_change = getattr(cfg, "buy_min_change_pct", None)
    if min_change is not None and inp.change_pct < min_change:
        return None
    if min_change is not None:
        reasons.append(f"cambio día {inp.change_pct:+.2f}% >= {min_change:+.2f}%")
    if getattr(cfg, "buy_require_catalyst", False) and not inp.has_catalyst:
        return None
    if getattr(cfg, "buy_require_catalyst", False):
        reasons.append("catalizador detectado (noticia/filing ≤48h)")
    reasons.insert(0, "setup momentum_vwap")
    return reasons


def setup_gap_and_go(inp: Any, cfg: Any) -> list[str] | None:
    """Premarket/intraday gap runner: strong day change + volume + VWAP hold."""
    min_gap = float(getattr(cfg, "gap_min_change_pct", 5.0))
    min_score = int(getattr(cfg, "gap_min_score", 60))
    min_rvol = float(getattr(cfg, "gap_min_rvol", 2.0))
    if inp.change_pct < min_gap:
        return None
    if inp.score < min_score:
        return None
    if inp.rvol < min_rvol:
        return None
    if inp.spread_pct is not None and inp.spread_pct > cfg.buy_max_spread_pct:
        return None
    # When VWAP is known, require holding above it (same discipline as momentum).
    if inp.vwap_distance_pct is not None and inp.vwap_distance_pct <= 0:
        return None
    reasons = [
        "setup gap_and_go",
        f"gap/cambio {inp.change_pct:+.2f}% >= {min_gap:+.2f}%",
        f"score {inp.score} >= {min_score}",
        f"RVOL {inp.rvol:.1f}x >= {min_rvol}x",
    ]
    if inp.vwap_distance_pct is not None:
        reasons.append(f"sobre VWAP (+{inp.vwap_distance_pct:.2f}%)")
    return reasons


def setup_donchian_breakout(inp: Any, cfg: Any) -> list[str] | None:
    """20d Donchian breakout already validated by monitor gates."""
    if not inp.donchian_pass:
        return None
    min_score = int(getattr(cfg, "donchian_min_score", 65))
    if inp.score < min_score:
        return None
    if inp.spread_pct is not None and inp.spread_pct > cfg.buy_max_spread_pct:
        return None
    return [
        "setup donchian_breakout",
        f"ruptura Donchian validada · score {inp.score} >= {min_score}",
        f"RVOL {inp.rvol:.1f}x",
    ]


def setup_accumulation_markup(inp: Any, cfg: Any) -> list[str] | None:
    """Wyckoff-style base + volume expansion into markup."""
    if not inp.markup_ready:
        return None
    min_score = int(getattr(cfg, "markup_min_score", 65))
    min_rvol = float(getattr(cfg, "markup_min_rvol", 1.5))
    if inp.score < min_score or inp.rvol < min_rvol:
        return None
    if inp.spread_pct is not None and inp.spread_pct > cfg.buy_max_spread_pct:
        return None
    return [
        "setup accumulation_markup",
        f"markup ready · score {inp.score} >= {min_score}",
        f"RVOL {inp.rvol:.1f}x >= {min_rvol}x",
    ]


def setup_squeeze_continuation(inp: Any, cfg: Any) -> list[str] | None:
    """Parabolic squeeze still expanding — momentum-long only."""
    if not inp.squeeze_active:
        return None
    min_score = int(getattr(cfg, "squeeze_min_score", 65))
    min_rvol = float(getattr(cfg, "squeeze_min_rvol", 2.0))
    if inp.score < min_score or inp.rvol < min_rvol:
        return None
    if inp.vwap_distance_pct is not None and inp.vwap_distance_pct <= 0:
        return None
    if inp.spread_pct is not None and inp.spread_pct > cfg.buy_max_spread_pct:
        return None
    return [
        "setup squeeze_continuation",
        f"squeeze activo · score {inp.score} >= {min_score}",
        f"RVOL {inp.rvol:.1f}x >= {min_rvol}x",
        "solo momentum-long (sin short)",
    ]


def setup_catalyst_impulse(inp: Any, cfg: Any) -> list[str] | None:
    """High-impact news/filing with volume confirmation."""
    if not inp.has_catalyst:
        return None
    impact = (inp.catalyst_impact or "").lower()
    if impact not in {"high", "medium"}:
        return None
    conf = float(inp.catalyst_confidence or 0.0)
    min_conf = float(getattr(cfg, "catalyst_setup_min_confidence", 0.6))
    if conf < min_conf:
        return None
    min_score = int(getattr(cfg, "catalyst_min_score", 60))
    min_rvol = float(getattr(cfg, "catalyst_min_rvol", 2.5))
    if inp.score < min_score or inp.rvol < min_rvol:
        return None
    if inp.spread_pct is not None and inp.spread_pct > cfg.buy_max_spread_pct:
        return None
    return [
        "setup catalyst_impulse",
        f"catalizador {impact} · conf {conf:.2f} >= {min_conf:.2f}",
        f"score {inp.score} >= {min_score}",
        f"RVOL {inp.rvol:.1f}x >= {min_rvol}x",
    ]


_SETUP_FNS: list[tuple[str, Callable[[Any, Any], list[str] | None]]] = [
    ("donchian_breakout", setup_donchian_breakout),
    ("catalyst_impulse", setup_catalyst_impulse),
    ("gap_and_go", setup_gap_and_go),
    ("squeeze_continuation", setup_squeeze_continuation),
    ("accumulation_markup", setup_accumulation_markup),
    ("momentum_vwap", setup_momentum_vwap),
]


def match_setups(inp: Any, cfg: Any) -> list[SetupMatch]:
    """Return all enabled setups that match, highest priority first."""
    if hard_blocked(inp, cfg) or global_entry_blocked(inp, cfg):
        return []
    matches: list[SetupMatch] = []
    for name, fn in _SETUP_FNS:
        if not _enabled(cfg, name):
            continue
        reasons = fn(inp, cfg)
        if reasons:
            matches.append(
                SetupMatch(name=name, priority=SETUP_PRIORITY.get(name, 0), reasons=reasons)
            )
    matches.sort(key=lambda m: m.priority, reverse=True)
    return matches


def best_setup(inp: Any, cfg: Any) -> SetupMatch | None:
    matches = match_setups(inp, cfg)
    return matches[0] if matches else None
