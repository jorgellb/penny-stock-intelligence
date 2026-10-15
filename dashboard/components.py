"""HTML fragments for the desk (pure: dict in, escaped HTML string out)."""

from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Any
from zoneinfo import ZoneInfo

from dashboard import theme as t

NY = ZoneInfo("America/New_York")


def fnum(
    value: Any, digits: int = 2, prefix: str = "", suffix: str = "", sign: bool = False
) -> str:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return "—"
    body = f"{num:+,.{digits}f}" if sign else f"{num:,.{digits}f}"
    return f"{prefix}{body}{suffix}"


def fprice(value: Any) -> str:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return "—"
    return f"${num:,.4f}" if num < 1 else f"${num:,.2f}"


def fmoney(value: Any) -> str:
    try:
        num = float(value or 0)
    except (TypeError, ValueError):
        return "—"
    for unit, div in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if abs(num) >= div:
            return f"${num / div:,.1f}{unit}"
    return f"${num:,.0f}"


def tone_class(value: Any) -> str:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return "muted"
    return "up" if num > 0 else ("down" if num < 0 else "muted")


def market_phase(now: datetime | None = None) -> tuple[str, str]:
    """(label, pill tone) for the US equity session in New York time."""
    ny = (now or datetime.now(NY)).astimezone(NY)
    if ny.weekday() >= 5:
        return "CLOSED · WEEKEND", "bad"
    mins = ny.hour * 60 + ny.minute
    if 4 * 60 <= mins < 9 * 60 + 30:
        return "PREMARKET", "warn"
    if 9 * 60 + 30 <= mins < 16 * 60:
        return "REGULAR SESSION", "ok"
    if 16 * 60 <= mins < 20 * 60:
        return "AFTER HOURS", "info"
    return "CLOSED", "bad"


def top_bar(api_live: bool, env: str, regime: str | None = None, kill: bool = False) -> str:
    phase, phase_tone = market_phase()
    clock = datetime.now(NY).strftime("%H:%M ET")
    pills = [
        f"<span class='nt-pill {'ok' if api_live else 'bad'}'><i></i>"
        f"{'API LIVE' if api_live else 'API OFFLINE'}</span>",
        f"<span class='nt-pill {phase_tone}'><i></i>{phase} · {clock}</span>",
    ]
    if regime:
        tone = {"risk_on": "ok", "chop": "warn", "risk_off": "bad", "halt_storm": "bad"}.get(
            regime.lower(), "info"
        )
        pills.append(f"<span class='nt-pill {tone}'><i></i>REGIME {escape(regime.upper())}</span>")
    if kill:
        pills.append("<span class='nt-pill bad'><i></i>KILL SWITCH</span>")
    pills.append("<span class='nt-pill'><i></i>TRADING OFF · MANUAL ONLY</span>")
    pills.append(f"<span class='nt-pill'>{escape(env)}</span>")
    return (
        "<div class='nt-bar'><div class='nt-logo'><b>PSI</b>//desk"
        "<span>penny stock intelligence</span></div>"
        f"<div class='nt-pills'>{''.join(pills)}</div></div>"
    )


def section(title: str, lede: str = "") -> str:
    lede_html = f"<span class='lede'>{escape(lede)}</span>" if lede else ""
    return f"<div class='nt-h'><h2>{escape(title)}</h2>{lede_html}<span class='rule'></span></div>"


def kpi(label: str, value: str, hint: str = "", tone: str = "") -> str:
    colors = {"up": t.UP, "down": t.DOWN, "warn": t.WARN, "info": t.INFO, "accent": t.ACCENT}
    color = colors.get(tone)
    style = f" style='--tone:{color};--tone-text:{color}'" if color else ""
    return (
        f"<div class='nt-kpi'{style}><div class='l'>{escape(label)}</div>"
        f"<div class='v'>{escape(value)}</div><div class='h'>{escape(hint)}</div></div>"
    )


def kpi_row(items: list[str]) -> str:
    return f"<div class='nt-kpis'>{''.join(items)}</div>"


def score_ring(score: Any) -> str:
    try:
        val = max(0.0, min(100.0, float(score)))
    except (TypeError, ValueError):
        val = 0.0
    color = t.UP if val >= 80 else (t.INFO if val >= 70 else (t.WARN if val >= 50 else t.DOWN))
    return f"<div class='nt-ring' style='--p:{val:.0f};--c:{color}'><span>{val:.0f}</span></div>"


def grade_badge(grade: str | None) -> str:
    if not grade:
        return ""
    color = t.GRADE_COLORS.get(grade.upper(), t.MUTED)
    return f"<span class='nt-grade' style='color:{color}' title='grado'>{escape(grade)}</span>"


def plan_block(plan: dict | None, order: dict | None = None) -> str:
    if not plan:
        return ""
    entry = float(plan.get("entry") or 0)
    stop = float(plan.get("stop") or 0)
    targets = [float(x) for x in plan.get("targets") or []]
    lo, hi = stop, (targets[-1] if targets else entry)
    span = (hi - lo) or 1.0

    def pos(x: float) -> float:
        return max(0.0, min(100.0, (x - lo) / span * 100))

    marks = f"<i style='left:{pos(entry):.1f}%'></i>" + "".join(
        f"<i class='t' style='left:{pos(x):.1f}%'></i>" for x in targets
    )
    tgt = " / ".join(fprice(x) for x in targets)
    rows = [
        ("ENTRY", fprice(entry)),
        (
            "STOP",
            f"{fprice(stop)} · -{fnum(plan.get('risk_pct'), 1)}% · {plan.get('stop_basis', '')}",
        ),
        ("TARGETS", tgt),
        (
            "R:R",
            f"{fnum(plan.get('reward_risk'), 1)}"
            + (f" · resist {fprice(plan['resistance'])}" if plan.get("resistance") else ""),
        ),
    ]
    body = "".join(
        f"<div class='row'><span>{k}</span><span>{escape(str(v))}</span></div>" for k, v in rows
    )
    order_html = ""
    if order:
        size = f"{order.get('quantity', '—')} sh · {fmoney(order.get('notional'))}"
        risk = fmoney(order.get("risk_dollars"))
        order_html = (
            f"<div class='row'><span>SIZE</span><span>{escape(size)} · riesgo {risk}</span></div>"
            f"<div class='nt-order'>{escape(str(order.get('instruction', '')))}</div>"
        )
    foot = ""
    if plan.get("grade_reasons"):
        foot = f"<div class='foot'>{escape(' · '.join(plan['grade_reasons']))}</div>"
    return (
        f"<div class='nt-plan'>{body}"
        f"<div class='nt-ladder' style='--e:{pos(entry):.1f}%'>{marks}</div>"
        f"{order_html}{foot}</div>"
    )


def signal_card(sig: dict) -> str:
    action = str(sig.get("action", "hold")).lower()
    sym = escape(str(sig.get("symbol", "?")))
    chips = []
    setup = sig.get("setup")
    if setup:
        chips.append(f"<span class='nt-chip main'>{escape(str(setup))}</span>")
    for s in sig.get("matched_setups") or []:
        if s != setup:
            chips.append(f"<span class='nt-chip'>{escape(str(s))}</span>")
    for f in (sig.get("risk_flags") or [])[:4]:
        chips.append(f"<span class='nt-chip risk'>{escape(str(f))}</span>")
    stats = [
        (
            "CHG",
            fnum(sig.get("change_pct"), 1, suffix="%", sign=True),
            tone_class(sig.get("change_pct")),
        ),
        ("RVOL", fnum(sig.get("rvol"), 1, suffix="x"), "up" if (sig.get("rvol") or 0) >= 3 else ""),
        (
            "VWAP",
            fnum(sig.get("vwap_distance_pct"), 1, suffix="%", sign=True),
            tone_class(sig.get("vwap_distance_pct")),
        ),
        ("$VOL", fmoney(sig.get("dollar_volume")), ""),
    ]
    stats_html = "".join(
        f"<div class='nt-stat'><div class='l'>{lbl}</div><div class='v {cls}'>{val}</div></div>"
        for lbl, val, cls in stats
    )
    reasons = sig.get("reasons") or []
    why = ""
    if reasons:
        items = "".join(f"<li>{escape(str(r))}</li>" for r in reasons[:14])
        why = (
            f"<details class='nt-why'><summary>por qué · {len(reasons)}</summary>"
            f"<ul>{items}</ul></details>"
        )
    catalyst = sig.get("catalyst_summary")
    cat_html = (
        "<div class='h muted' style='font-size:.74rem;margin:.1rem 0 .4rem'>"
        f"📰 {escape(str(catalyst))}</div>"
        if catalyst
        else ""
    )
    return (
        f"<div class='nt-card {action}'>"
        f"<div class='top'>{score_ring(sig.get('score'))}<span class='sym'>{sym}</span>"
        f"<span class='nt-act {action}'>{action.upper()}</span>{grade_badge(sig.get('grade'))}"
        f"<span class='px'><b>{fprice(sig.get('price'))}</b></span></div>"
        f"<div class='nt-stats'>{stats_html}</div>"
        f"<div class='nt-chips'>{''.join(chips)}</div>{cat_html}"
        f"{plan_block(sig.get('trade_plan'), sig.get('order_template'))}{why}</div>"
    )


def cards(signals: list[dict]) -> str:
    return f"<div class='nt-cards'>{''.join(signal_card(s) for s in signals)}</div>"


def empty(message: str) -> str:
    return f"<div class='nt-empty'>{escape(message)}</div>"
