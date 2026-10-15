"""Penny Stock Intelligence — research desk UI over the live FastAPI backend.

Every number comes from the API. Offline shows an explicit banner,
never zero-filled demo tables.
"""

from __future__ import annotations

import asyncio
import os

import pandas as pd
import streamlit as st

from dashboard.api_client import (
    ApiOfflineError,
    add_symbol,
    alerts_history,
    health,
    make_client,
    monitor_config,
    monitor_events,
    monitor_status,
    opportunities,
    opportunity_setups,
    remove_symbol,
    run_backtest,
    run_monitor_pass,
    run_radar,
    scanner_rankings,
    send_test_alert,
    stock,
    stock_history,
    universe_scan,
    watchlist_symbols,
    watchlists,
)

st.set_page_config(
    page_title="PSI · Research Desk",
    page_icon="P",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Design tokens — Filing Desk
# Paper stone · steel stamp · forest signal · brick alert · plex data
# ---------------------------------------------------------------------------

_THEME_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=Newsreader:opsz,wght@6..72,500;6..72,600&family=Source+Sans+3:wght@400;500;600;700&display=swap');

:root {
  --paper: #EEF1F4;
  --surface: #F7F9FB;
  --ink: #121A24;
  --slate: #5A6675;
  --muted: #7A8694;
  --rule: #C5CDD6;
  --mark: #2F5D8C;
  --mark-soft: #E4ECF5;
  --up: #0B6E4F;
  --up-soft: #D8EDE4;
  --down: #B33A3A;
  --down-soft: #F3E0E0;
  --warn: #9A6700;
  --warn-soft: #F3EBD4;
  --tape: #1A2838;
}

html, body, [class*="css"] {
  font-family: "Source Sans 3", "Segoe UI", sans-serif;
  color: var(--ink);
}

.stApp {
  background:
    linear-gradient(180deg, #E6EBEF 0%, var(--paper) 28%, var(--paper) 100%);
}

.block-container {
  padding-top: 1.1rem;
  padding-bottom: 2.5rem;
  max-width: 1180px;
}

/* —— Masthead —— */
.psi-masthead {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 1rem;
  align-items: end;
  padding-bottom: .85rem;
  border-bottom: 2px solid var(--ink);
  margin-bottom: .55rem;
}
.psi-brand-mark {
  font-family: "Newsreader", Georgia, serif;
  font-size: 2.35rem;
  font-weight: 600;
  letter-spacing: -.02em;
  line-height: .95;
  color: var(--ink);
  margin: 0;
}
.psi-brand-sub {
  font-family: "IBM Plex Mono", monospace;
  font-size: .68rem;
  letter-spacing: .18em;
  text-transform: uppercase;
  color: var(--mark);
  margin-top: .35rem;
}
.psi-brand-lede {
  font-size: .92rem;
  color: var(--slate);
  max-width: 28rem;
  line-height: 1.35;
  margin: 0;
  text-align: right;
}

/* —— Tape strip —— */
.psi-tape {
  display: flex;
  flex-wrap: wrap;
  gap: .45rem .7rem;
  align-items: center;
  background: var(--tape);
  color: #D7DEE7;
  padding: .42rem .75rem;
  margin: 0 0 1.25rem 0;
  font-family: "IBM Plex Mono", monospace;
  font-size: .72rem;
  letter-spacing: .04em;
}
.psi-tape .seg { opacity: .55; }
.psi-tape .live { color: #7DCEA0; }
.psi-tape .dead { color: #E08A8A; }
.psi-tape .env {
  margin-left: auto;
  background: rgba(255,255,255,.08);
  padding: .1rem .45rem;
}

/* —— Section titles —— */
.psi-section {
  display: flex;
  align-items: baseline;
  gap: .75rem;
  margin: 1.4rem 0 .65rem;
  border-bottom: 1px solid var(--rule);
  padding-bottom: .35rem;
}
.psi-section h2 {
  font-family: "Newsreader", Georgia, serif;
  font-size: 1.35rem;
  font-weight: 600;
  margin: 0;
  color: var(--ink);
}
.psi-section .lede {
  font-size: .82rem;
  color: var(--muted);
}

/* —— KPI filing cards —— */
.psi-kpi {
  background: var(--surface);
  border: 1px solid var(--rule);
  border-left: 3px solid var(--mark);
  padding: .75rem .9rem .7rem;
  margin-bottom: .55rem;
  min-height: 5.2rem;
}
.psi-kpi.warn { border-left-color: var(--warn); }
.psi-kpi.danger { border-left-color: var(--down); }
.psi-kpi.ok { border-left-color: var(--up); }
.psi-kpi .label {
  font-family: "IBM Plex Mono", monospace;
  font-size: .62rem;
  letter-spacing: .14em;
  text-transform: uppercase;
  color: var(--muted);
}
.psi-kpi .value {
  font-family: "Newsreader", Georgia, serif;
  font-size: 1.55rem;
  font-weight: 600;
  color: var(--ink);
  margin: .15rem 0 .1rem;
  line-height: 1.1;
}
.psi-kpi .hint { font-size: .75rem; color: var(--slate); }

/* —— Stamps (actions) —— */
.psi-stamp {
  display: inline-block;
  font-family: "IBM Plex Mono", monospace;
  font-size: .68rem;
  font-weight: 600;
  letter-spacing: .12em;
  padding: .2rem .55rem;
  border: 1.5px solid currentColor;
  margin-right: .35rem;
  vertical-align: middle;
}
.psi-stamp.buy { color: var(--up); background: var(--up-soft); }
.psi-stamp.sell { color: var(--down); background: var(--down-soft); }
.psi-stamp.hold { color: var(--warn); background: var(--warn-soft); }

/* —— Symbol chips —— */
.psi-chip {
  background: var(--surface);
  border: 1px solid var(--rule);
  padding: .65rem .75rem;
  margin-bottom: .5rem;
}
.psi-chip .sym {
  font-family: "IBM Plex Mono", monospace;
  font-weight: 600;
  font-size: .95rem;
  letter-spacing: .04em;
}

/* —— Score readout —— */
.psi-score {
  font-family: "Newsreader", Georgia, serif;
  font-size: 2rem;
  font-weight: 600;
  line-height: 1;
}
.psi-score span {
  font-family: "IBM Plex Mono", monospace;
  font-size: .75rem;
  color: var(--muted);
  font-weight: 500;
  margin-left: .25rem;
}

/* —— Footer —— */
.psi-footer {
  margin-top: 2.2rem;
  padding-top: .85rem;
  border-top: 1px solid var(--rule);
  font-family: "IBM Plex Mono", monospace;
  font-size: .68rem;
  color: var(--muted);
  letter-spacing: .02em;
  line-height: 1.5;
}

/* —— Streamlit chrome —— */
section[data-testid="stSidebar"] {
  background: #E4E9EF;
  border-right: 1px solid var(--rule);
}
section[data-testid="stSidebar"] .block-container { padding-top: 1.2rem; }
.psi-nav-title {
  font-family: "Newsreader", Georgia, serif;
  font-size: 1.15rem;
  font-weight: 600;
  margin: 0 0 .15rem;
}
.psi-nav-meta {
  font-family: "IBM Plex Mono", monospace;
  font-size: .62rem;
  letter-spacing: .14em;
  text-transform: uppercase;
  color: var(--mark);
  margin-bottom: 1rem;
}
div[data-testid="stMetric"] {
  background: var(--surface);
  border: 1px solid var(--rule);
  border-left: 3px solid var(--mark);
  padding: .65rem .8rem;
}
div[data-testid="stMetric"] label { color: var(--muted) !important; }
.stButton > button[kind="primary"],
.stButton > button[data-testid="baseButton-primary"] {
  background: var(--mark) !important;
  border: 1px solid var(--mark) !important;
  color: #fff !important;
  font-family: "Source Sans 3", sans-serif !important;
  font-weight: 600 !important;
  border-radius: 2px !important;
}
.stButton > button {
  border-radius: 2px !important;
  border-color: var(--rule) !important;
}
div[data-baseweb="tab-list"] {
  gap: .15rem;
  border-bottom: 1px solid var(--rule);
}
button[data-baseweb="tab"] {
  font-family: "IBM Plex Mono", monospace !important;
  font-size: .72rem !important;
  letter-spacing: .06em !important;
  text-transform: uppercase !important;
}

@media (max-width: 768px) {
  .psi-masthead { grid-template-columns: 1fr; }
  .psi-brand-lede { text-align: left; max-width: none; }
  .psi-brand-mark { font-size: 1.85rem; }
  .psi-tape .env { margin-left: 0; }
}
@media (prefers-reduced-motion: reduce) {
  * { animation: none !important; transition: none !important; }
}
</style>
"""

st.markdown(_THEME_CSS, unsafe_allow_html=True)

API_URL = st.sidebar.text_input(
    "API endpoint",
    os.getenv("API_BASE_URL", "http://localhost:8000"),
    help="FastAPI base URL for this desk session.",
)


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


def _client(timeout: float = 15.0):  # type: ignore[no-untyped-def]
    return make_client(base_url=API_URL, timeout=timeout)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _score_color(score: float) -> str:
    if score >= 80:
        return "#0B6E4F"
    if score >= 70:
        return "#2F5D8C"
    if score >= 50:
        return "#9A6700"
    return "#B33A3A"


def _action_stamp(action: str) -> str:
    a = (action or "").lower()
    cls = {"buy": "buy", "sell": "sell", "hold": "hold"}.get(a, "hold")
    return f"<span class='psi-stamp {cls}'>{(a or '—').upper()}</span>"


def _section(title: str, lede: str = "") -> None:
    lede_html = f"<span class='lede'>{lede}</span>" if lede else ""
    st.markdown(
        f"<div class='psi-section'><h2>{title}</h2>{lede_html}</div>",
        unsafe_allow_html=True,
    )


def _masthead(health_payload: dict | None) -> None:
    live = bool(health_payload) and health_payload.get("status") == "healthy"
    env = (health_payload or {}).get("environment", "unknown")
    status_cls = "live" if live else "dead"
    status_txt = "API LIVE" if live else "API OFFLINE"
    st.markdown(
        """
        <div class="psi-masthead">
          <div>
            <p class="psi-brand-mark">Penny Stock Intelligence</p>
            <div class="psi-brand-sub">Research desk · US micro-caps</div>
          </div>
          <p class="psi-brand-lede">
            Ranking scores for manual review — never forecasts,
            never auto-execution.
          </p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        f"""
        <div class="psi-tape">
          <span class="{status_cls}">{status_txt}</span>
          <span class="seg">|</span>
          <span>ENDPOINT {API_URL}</span>
          <span class="seg">|</span>
          <span>TRADING OFF</span>
          <span class="env">{env}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _offline_banner() -> bool:
    try:
        _run(health(_client()))
        return False
    except ApiOfflineError as exc:
        st.error(f"Backend unreachable: {exc}. Start with `make dev` or compose.")
        return True


def _kpi(label: str, value: str, hint: str = "", tone: str = "") -> None:
    cls = f"psi-kpi {tone}".strip()
    st.markdown(
        f"<div class='{cls}'><div class='label'>{label}</div>"
        f"<div class='value'>{value}</div>"
        f"<div class='hint'>{hint}</div></div>",
        unsafe_allow_html=True,
    )


def _signals_frame(events: list[dict]) -> pd.DataFrame:
    if not events:
        return pd.DataFrame()
    df = pd.DataFrame(events)
    for col in ("symbol", "action", "score", "price"):
        if col not in df.columns:
            df[col] = None
    df["score"] = pd.to_numeric(df["score"], errors="coerce")
    return df.sort_values("score", ascending=False, na_position="last")


def _dataframe(df: pd.DataFrame, score: bool = True) -> None:
    cfg: dict = {
        "price": st.column_config.NumberColumn("Price", format="$%.2f"),
    }
    if score:
        cfg["score"] = st.column_config.ProgressColumn(
            "Score", min_value=0, max_value=100, format="%d"
        )
    st.dataframe(df, use_container_width=True, column_config=cfg)


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------


def _safe_health() -> dict | None:
    try:
        return _run(health(_client()))
    except ApiOfflineError:
        return None


def show_dashboard() -> None:
    payload = _safe_health()
    _masthead(payload)
    if payload is None:
        st.error("Backend offline. Start backend (`make dev` / compose).")
        return
    try:
        status = _run(monitor_status(_client()))
        events = _run(monitor_events(_client(), limit=100))
    except ApiOfflineError as exc:
        st.error(str(exc))
        return

    stats = status.get("stats", {})
    paper = status.get("paper", {})
    buys = sum(1 for e in events if str(e.get("action", "")).lower() == "buy")
    sells = sum(1 for e in events if str(e.get("action", "")).lower() == "sell")
    kill = bool(status.get("kill_switch"))

    _section("Floor status", "Current regime and risk controls")
    k1, k2, k3, k4 = st.columns(4)
    with k1:
        _kpi("Regime", str(status.get("regime", "unknown")).upper(), "market filter")
    with k2:
        _kpi("Tracked", str(status.get("tracked_symbols", 0)), "symbols on lists")
    with k3:
        _kpi(
            "Signals",
            f"{buys} buy · {sells} sell",
            f"{stats.get('signals', len(events))} last round",
        )
    with k4:
        _kpi(
            "Kill switch",
            "ACTIVE" if kill else "Off",
            "blocks new buys",
            tone="danger" if kill else "ok",
        )
    if paper:
        p1, p2 = st.columns(2)
        with p1:
            _kpi("Paper equity", f"${paper.get('equity', 0):,.2f}", "simulated book")
        with p2:
            _kpi("Open paper", str(len(paper.get("open", []))), "positions")

    if kill:
        st.error("Kill switch is ACTIVE — new buys blocked. Review risk before continuing.")
    if status.get("vetoed_symbols"):
        st.warning(f"Vetoed 24h: {', '.join(status['vetoed_symbols'])}")

    _section("Recent signals", "For manual review only — not recommendations")
    df = _signals_frame(events)
    if df.empty:
        st.info("No signals yet. Run a monitor pass from Scanner.")
        return
    _dataframe(df)


def show_scanner() -> None:
    _masthead(_safe_health())
    _section("Scanner", "One live monitor round over a stock list")
    st.caption(
        "Score, risk, regime, correlation and circuits in one pass. "
        "Outputs are for human review."
    )
    if _offline_banner():
        return
    try:
        lists = _run(watchlists(_client()))
    except ApiOfflineError as exc:
        st.error(str(exc))
        return
    names = [str(item.get("name")) for item in lists] or ["default"]
    c1, c2 = st.columns([3, 1])
    with c1:
        list_name = st.selectbox("List", names)
    with c2:
        st.write("")
        run = st.button("Run monitor pass", type="primary")
    if not run:
        return
    with st.spinner(f"Evaluating {list_name}…"):
        try:
            result = _run(run_monitor_pass(_client(timeout=180.0), list_name))
        except ApiOfflineError as exc:
            st.error(str(exc))
            return
    st.success(f"{result.get('symbols', 0)} symbols evaluated")
    signals = list(result.get("signals", []))
    with st.expander("Thresholds and display filters", expanded=False):
        try:
            cfg = _run(monitor_config(_client()))
        except ApiOfflineError as exc:
            st.error(str(exc))
            return
        t1, t2, t3 = st.columns(3)
        with t1:
            st.caption(
                f"BUY score≥{cfg.get('buy_min_score')} · RVOL≥{cfg.get('buy_min_rvol')}x · "
                f"spread≤{cfg.get('buy_max_spread_pct')}%"
            )
            st.caption(
                f"Dollar gate: {cfg.get('buy_min_dollar_volume') or 'off'} · "
                f"Day change: {cfg.get('buy_min_change_pct') or 'off'} · "
                f"Catalyst: {cfg.get('buy_require_catalyst')}"
            )
        with t2:
            st.caption(
                f"Exits: take-profit {cfg.get('sell_take_profit_pct') or 'off'} · "
                f"stop {cfg.get('sell_stop_loss_pct') or 'off'} · "
                f"score drop {cfg.get('sell_score_drop')}"
            )
            st.caption(f"Max BUYs/round: {cfg.get('max_buys_per_round') or 'unlimited'}")
        with t3:
            st.caption(
                f"Regime CHOP {cfg.get('regime_chop_min_score')}/"
                f"{cfg.get('regime_chop_min_rvol')}x · RISK_OFF "
                f"{cfg.get('regime_riskoff_min_score')}/"
                f"{cfg.get('regime_riskoff_min_rvol')}x"
            )
        f1, f2 = st.columns(2)
        with f1:
            min_score = st.slider("Display min score", 0, 100, 0)
        with f2:
            actions = st.multiselect(
                "Actions", ["buy", "sell", "hold"], default=["buy", "sell", "hold"]
            )
    signals = [
        s
        for s in signals
        if s.get("score", 0) >= min_score and s.get("action") in actions
    ]
    df = _signals_frame(signals)
    if df.empty:
        st.info("No signals match these filters.")
    else:
        _dataframe(df)


def show_watchlist() -> None:
    _masthead(_safe_health())
    _section("Watchlists", "Persistent symbol lists for the monitor")
    if _offline_banner():
        return
    try:
        lists = _run(watchlists(_client()))
    except ApiOfflineError as exc:
        st.error(str(exc))
        return
    names = [str(item.get("name")) for item in lists] or ["default"]
    list_name = st.selectbox("List", names, key="wl_list")
    with st.form("add_symbol_form", clear_on_submit=True):
        c1, c2 = st.columns([3, 1])
        with c1:
            symbol = st.text_input("Add symbol", placeholder="ABCD")
        with c2:
            st.write("")
            submitted = st.form_submit_button("Add")
        if submitted:
            if not symbol.strip():
                st.warning("Enter a symbol first.")
            else:
                try:
                    res = _run(add_symbol(_client(), list_name, symbol))
                    st.success(f"{res.get('status')}: {res.get('symbol')}")
                except ApiOfflineError as exc:
                    st.error(str(exc))
    try:
        syms = _run(watchlist_symbols(_client(), list_name))
    except ApiOfflineError as exc:
        st.error(str(exc))
        return
    st.caption(f"{list_name} · {len(syms)} symbols")
    if not syms:
        st.info("List is empty. Add symbols above.")
        return
    cols = st.columns(4)
    for i, s in enumerate(syms):
        with cols[i % 4]:
            st.markdown(
                f"<div class='psi-chip'><div class='sym'>{s}</div></div>",
                unsafe_allow_html=True,
            )
            if st.button("Remove", key=f"rm_{s}"):
                try:
                    _run(remove_symbol(_client(), list_name, s))
                    st.rerun()
                except ApiOfflineError as exc:
                    st.error(str(exc))


def _fmt_money(value: object) -> str:
    try:
        num = float(value or 0)
    except (TypeError, ValueError):
        return "—"
    for unit, div in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if abs(num) >= div:
            return f"${num / div:,.1f}{unit}"
    return f"${num:,.0f}"


def _price_chart(bars: list[dict], symbol: str):  # type: ignore[no-untyped-def]
    if not bars:
        return None
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    dates = [b.get("date", "")[:10] for b in bars]
    opens = [b.get("open") for b in bars]
    highs = [b.get("high") for b in bars]
    lows = [b.get("low") for b in bars]
    closes = [b.get("close") for b in bars]
    vols = [b.get("volume") or 0 for b in bars]
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.72, 0.28]
    )
    fig.add_trace(
        go.Candlestick(
            x=dates,
            open=opens,
            high=highs,
            low=lows,
            close=closes,
            name=symbol,
            increasing_line_color="#0B6E4F",
            decreasing_line_color="#B33A3A",
            increasing_fillcolor="#0B6E4F",
            decreasing_fillcolor="#B33A3A",
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Bar(
            x=dates,
            y=vols,
            name="Volume",
            marker_color="rgba(47,93,140,0.45)",
        ),
        row=2,
        col=1,
    )
    fig.update_layout(
        template="plotly_white",
        height=460,
        showlegend=False,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="#F7F9FB",
        font={"family": "Source Sans 3, sans-serif", "color": "#121A24", "size": 12},
        margin={"l": 8, "r": 8, "t": 36, "b": 8},
        title={
            "text": f"{symbol} · daily",
            "font": {"family": "IBM Plex Mono, monospace", "size": 12, "color": "#5A6675"},
        },
        xaxis_rangeslider_visible=False,
    )
    fig.update_xaxes(gridcolor="#E4E9EF", zeroline=False)
    fig.update_yaxes(gridcolor="#E4E9EF", zeroline=False)
    return fig


_SCORE_WEIGHTS = {
    "momentum": 20,
    "volume": 20,
    "catalyst": 20,
    "technical": 15,
    "liquidity": 10,
    "fundamentals": 10,
    "data_quality": 5,
}

_FUND_LABELS = [
    ("market_cap", "Market cap", True),
    ("revenue_ttm", "Revenue TTM", True),
    ("net_income", "Net income", True),
    ("eps", "EPS", False),
    ("cash", "Cash", True),
    ("total_debt", "Total debt", True),
    ("shares_outstanding", "Shares out.", False),
    ("float_shares", "Float", False),
]


def _rsi_zone(rsi: object) -> tuple[str, str]:
    try:
        val = float(rsi)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return ("n/d", "#7A8694")
    if val >= 70:
        return (f"{val:.1f} · overbought", "#B33A3A")
    if val <= 30:
        return (f"{val:.1f} · oversold", "#0B6E4F")
    return (f"{val:.1f} · neutral", "#2F5D8C")


def _div_text(value: object) -> str:
    v = str(value or "").lower()
    if v == "bullish":
        return "bullish"
    if v == "bearish":
        return "bearish"
    return "none"


def _num(value: object, money: bool = False) -> str:
    if value is None:
        return "—"
    try:
        num = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "—"
    return _fmt_money(num) if money else f"{num:,.2f}".rstrip("0").rstrip(".")


def _component_bar(name: str, value: float, weight: int) -> None:
    st.markdown(f"**{name}** · {value:.0f}/{weight}")
    st.progress(min(max(value / weight if weight else 0.0, 0.0), 1.0))


def show_analysis() -> None:
    _masthead(_safe_health())
    _section("Ticker desk", "Live snapshot and daily chart")
    st.caption("Scores rank setups against the model — they do not forecast price.")
    if _offline_banner():
        return
    c1, c2 = st.columns([3, 1])
    with c1:
        symbol = st.text_input("Ticker", placeholder="ABCD")
    with c2:
        days = st.selectbox("History", [30, 60, 120, 250], index=2)
    if not symbol.strip():
        return
    sym = symbol.strip().upper()
    with st.spinner(f"Loading {sym}…"):
        try:
            snap = _run(stock(_client(timeout=120.0), sym))
            hist = _run(stock_history(_client(timeout=120.0), sym, days=days))
        except ApiOfflineError as exc:
            st.error(str(exc))
            return
    try:
        score_f = float(snap.get("score", 0) or 0)
    except (TypeError, ValueError):
        score_f = 0.0
    color = _score_color(score_f)
    h1, h2, h3 = st.columns([2, 1, 1])
    with h1:
        st.markdown(
            f"{_action_stamp(str(snap.get('action', '')))} "
            f"**{sym}** · ${float(snap.get('price', 0) or 0):.2f} "
            f"({float(snap.get('change_pct', 0) or 0):+.2f}%)",
            unsafe_allow_html=True,
        )
    with h2:
        st.markdown(
            f"<div class='psi-score' style='color:{color}'>"
            f"{score_f:.0f}<span>/100</span></div>",
            unsafe_allow_html=True,
        )
    with h3:
        st.progress(min(max(score_f / 100.0, 0.0), 1.0))
    if snap.get("stale"):
        st.warning("Stale market data — treat this snapshot with caution.")

    fig = _price_chart(list(hist.get("bars", [])), sym)
    if fig is None:
        st.info(hist.get("note", "No history available for this window."))
    else:
        st.plotly_chart(fig, use_container_width=True)

    k1, k2, k3, k4 = st.columns(4)
    with k1:
        _kpi("RVOL", f"{snap.get('rvol') or '—'}x", str(snap.get("rvol_source", "")))
    with k2:
        _kpi("Dollar volume", _fmt_money(snap.get("dollar_volume")), "liquidity")
    with k3:
        _kpi("VWAP distance", f"{snap.get('vwap_distance_pct') or '—'}%", "intraday")
    with k4:
        fund = snap.get("fundamentals") or {}
        _kpi("Market cap", _fmt_money(fund.get("market_cap")), "fundamentals")

    tech = snap.get("technical", {}) or {}
    bd = snap.get("score_breakdown", {}) or {}
    tab_score, tab_mom, tab_cat, tab_dil, tab_fun, tab_news = st.tabs(
        [
            "Score & signal",
            "Momentum",
            "Catalyst & flow",
            "Dilution & risk",
            "Fundamentals",
            "News",
        ]
    )
    with tab_score:
        comps = bd.get("components", {}) or {}
        for name, weight in _SCORE_WEIGHTS.items():
            _component_bar(
                name.replace("_", " ").title(),
                float(comps.get(name, 0) or 0),
                weight,
            )
        st.markdown(
            f"Base **{bd.get('raw', '—')}** − penalty "
            f"**{bd.get('penalty', '—')}** = **{bd.get('final', '—')}**"
        )
        for k, v in (bd.get("penalties", {}) or {}).items():
            st.write(f"−{v} · {k}")
        st.caption(f"Data quality: {bd.get('data_quality', '—')}")
        st.divider()
        for r in snap.get("reasons", []):
            st.write(f"- {r}")
        if snap.get("order_template"):
            with st.expander("Manual order template (review in DEGIRO)"):
                st.json(snap["order_template"])
    with tab_mom:
        m1, m2, m3 = st.columns(3)
        with m1:
            label, color = _rsi_zone(tech.get("rsi_14"))
            st.markdown(
                f"**RSI 14** · <span style='color:{color};font-weight:700'>"
                f"{label}</span>",
                unsafe_allow_html=True,
            )
            st.write(f"RSI divergence: {_div_text(tech.get('rsi_divergence'))}")
        with m2:
            st.markdown(
                f"**Stochastic** K {_num(tech.get('stoch_k'))} / "
                f"D {_num(tech.get('stoch_d'))}"
            )
            st.write(f"Cross: {tech.get('stoch_cross') or '—'}")
            st.write(f"Divergence: {_div_text(tech.get('stoch_divergence'))}")
        with m3:
            st.markdown(
                f"**ATR** {_num(tech.get('atr'))} ({_num(tech.get('atr_pct'))}%)"
            )
            st.write(
                f"Squeeze: {'active' if tech.get('squeeze_active') else 'inactive'}"
            )
            st.write(f"Markup ready: {'yes' if tech.get('markup_ready') else 'no'}")
        st.caption(
            f"VWAP {_num(tech.get('vwap'))} · distance "
            f"{_num(tech.get('vwap_distance_pct'))}% · spread "
            f"{_num(tech.get('spread_pct'))}% · RVOL {snap.get('rvol') or '—'}x "
            f"({snap.get('rvol_source', '')})"
        )
    with tab_cat:
        cat = snap.get("catalyst") or {}
        if cat:
            st.markdown(f"**{cat.get('summary', 'Catalyst')}**")
            st.caption(
                f"Impact {cat.get('impact')} · confidence {cat.get('confidence')} · "
                f"{float(cat.get('age_hours', 0) or 0):.1f}h ago · "
                f"primary source: {cat.get('primary')}"
            )
        else:
            st.info("No catalyst detected in the last 48h.")
        acc = snap.get("accumulation") or {}
        if acc:
            st.markdown(f"**Quiet accumulation** (score {acc.get('score')})")
            for r in acc.get("reasons", []):
                st.write(f"- {r}")
        climax = tech.get("climax") or {}
        if climax:
            st.warning(
                f"Distribution climax: volume {climax.get('volume_multiple')}x "
                f"after +{climax.get('runup_pct')}% — do not chase"
            )
        gate = snap.get("donchian_gate")
        st.caption(
            "Donchian gate: " + ("passed" if gate else "not passed / n/a")
        )
    with tab_dil:
        d1, d2 = st.columns(2)
        with d1:
            frozen = bool(snap.get("dilution_frozen"))
            _kpi(
                "Dilution freeze",
                "YES" if frozen else "No",
                "offerings / ATM / shelf",
                tone="danger" if frozen else "ok",
            )
            halted = bool(snap.get("halted"))
            _kpi(
                "Halt",
                "YES" if halted else "No",
                "trading",
                tone="danger" if halted else "ok",
            )
        with d2:
            _kpi("Dollar rule", str(snap.get("dollar_rule", "—")), "closes under $1.00")
            vetoed = bool(snap.get("vetoed"))
            kill = bool(snap.get("kill_switch"))
            _kpi(
                "Veto / kill",
                f"{'YES' if vetoed else 'No'} / {'ACTIVE' if kill else 'off'}",
                "circuits",
                tone="danger" if vetoed or kill else "",
            )
        fil = snap.get("filings", {}) or {}
        if fil.get("reasons"):
            for r in fil["reasons"]:
                st.write(f"- {r}")
        elif fil.get("note"):
            st.caption(f"Filings: {fil['note']}")
        flags = snap.get("risk_flags", []) or []
        if flags:
            for f in flags:
                st.warning(str(f))
        else:
            st.success("No active risk flags on this snapshot.")
    with tab_fun:
        fund = snap.get("fundamentals") or {}
        if fund:
            rows = [
                {"Metric": label, "Value": _num(fund.get(key), money)}
                for key, label, money in _FUND_LABELS
            ]
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            st.info(snap.get("fundamentals_note", "No fundamentals."))
    with tab_news:
        news = snap.get("news", []) or []
        if news:
            for n in news:
                st.markdown(f"- **{n.get('headline')}** ({n.get('source', '')})")
                if n.get("url"):
                    st.caption(n["url"])
        else:
            st.info(snap.get("news_note", "No recent news."))


def show_radar() -> None:
    _masthead(_safe_health())
    _section("Opportunity radar", "Ranked movers and multi-setup playbooks")
    st.caption(
        "Aggregates monitor evaluations into a ranked list and can sync top "
        "names into the radar watchlist for continuous evaluation."
    )
    if _offline_banner():
        return
    c1, c2 = st.columns([1, 1])
    with c1:
        if st.button("Refresh opportunities", type="primary"):
            st.rerun()
    with c2:
        if st.button("Sync into radar list"):
            with st.spinner("Running radar pass…"):
                try:
                    res = _run(run_radar(_client(timeout=60.0)))
                    st.success(
                        f"{res.get('status')}: +{res.get('added', 0)} → list "
                        f"{res.get('list')} ({res.get('ranked', 0)} ranked)"
                    )
                except ApiOfflineError as exc:
                    st.error(str(exc))
    try:
        body = _run(opportunities(_client(), limit=40))
        setups = _run(opportunity_setups(_client()))
    except ApiOfflineError as exc:
        st.error(str(exc))
        return
    enabled = [k for k, v in (setups.get("enabled") or {}).items() if v]
    st.caption(f"Active setups: {', '.join(enabled) or 'none'}")
    rows = body.get("opportunities", []) or []
    if not rows:
        st.info("No ranked opportunities yet. Run a monitor pass, then refresh.")
        return
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True)


def show_backtest() -> None:
    _masthead(_safe_health())
    _section("Backtest", "Historical RVOL-momentum bundle")
    st.caption("Informational only — past returns do not predict future ones.")
    if _offline_banner():
        return
    with st.form("backtest_form"):
        symbols = st.text_input("Symbols (comma-separated)", placeholder="ABCD,EFGH")
        c1, c2 = st.columns(2)
        with c1:
            days = st.slider("History days", 30, 730, 120)
        with c2:
            min_rvol = st.slider("Min RVOL", 1.0, 10.0, 2.0, step=0.5)
        run = st.form_submit_button("Run backtest", type="primary")
    if not run:
        return
    if not symbols.strip():
        st.warning("Enter at least one symbol.")
        return
    with st.spinner("Running bundle…"):
        try:
            result = _run(
                run_backtest(_client(timeout=240.0), symbols, days=days, min_rvol=min_rvol)
            )
        except ApiOfflineError as exc:
            st.error(str(exc))
            return
    m = result.get("metrics", {})
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        _kpi("Trades", str(int(m.get("number_of_signals", 0))), "matched rules")
    with col2:
        _kpi("Win rate", f"{m.get('win_rate', 0):.1f}%", "closed trades")
    with col3:
        _kpi("Avg return", f"{m.get('average_return', 0):+.2f}%", "per trade")
    with col4:
        _kpi("Max drawdown", f"{m.get('max_drawdown', 0):.2f}%", "peak to trough")
    _section("Trades")
    trades = result.get("trades", [])
    if trades:
        st.dataframe(pd.DataFrame(trades), use_container_width=True)
    else:
        st.info("No trades matched the rule in this window.")
    wf = result.get("walk_forward", {}).get("mean")
    if wf:
        st.caption(
            f"Walk-forward mean: win {wf.get('win_rate', 0):.1f}% | "
            f"avg {wf.get('average_return', 0):+.2f}%"
        )
    if result.get("skipped"):
        st.warning(f"Skipped: {', '.join(result['skipped'])}")


def show_rankings() -> None:
    _masthead(_safe_health())
    _section("Rankings", "Universe eligibility and monitor order")
    if _offline_banner():
        return
    with st.form("universe_form"):
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            limit = st.selectbox("Symbols to scan", [25, 50, 100, 200], index=1)
        with c2:
            min_price = st.number_input("Min price", value=0.10, step=0.10)
        with c3:
            max_price = st.number_input("Max price", value=5.00, step=0.50)
        with c4:
            exchange = st.selectbox("Exchange", ["All", "NASDAQ", "NYSE", "AMEX"])
        go = st.form_submit_button("Run universe scan", type="primary")
    if go:
        if min_price >= max_price:
            st.warning("Min price must be below max price.")
            return
        with st.spinner(f"Scanning {limit} symbols with live quotes…"):
            try:
                body = _run(
                    universe_scan(
                        _client(timeout=240.0),
                        limit=int(limit),
                        min_price=float(min_price),
                        max_price=float(max_price),
                        exchange=None if exchange == "All" else exchange,
                    )
                )
            except ApiOfflineError as exc:
                st.error(str(exc))
                return
        stats = body.get("stats", {})
        k1, k2, k3 = st.columns(3)
        with k1:
            _kpi("Scanned", str(body.get("total", 0)), f"{body.get('duration_ms', 0)} ms")
        with k2:
            _kpi("Eligible", str(body.get("eligible_count", 0)), "price + liquidity")
        with k3:
            _kpi(
                "With quotes",
                str(stats.get("quotes_ok", stats.get("ok", "—"))),
                "provider",
            )
        elig = body.get("eligible", []) or []
        if elig:
            st.caption(f"Eligible ({len(elig)})")
            st.dataframe(pd.DataFrame(elig), use_container_width=True)
        else:
            st.info("No eligible symbols in this slice. Widen the price range.")
    st.divider()
    st.caption("Monitor rankings (already evaluated symbols)")
    kind = st.selectbox("Ranking", ["intraday", "premarket", "overall"], index=0)
    try:
        rank = _run(scanner_rankings(_client(), kind=kind))
    except ApiOfflineError as exc:
        st.error(str(exc))
        return
    rows = rank.get("rankings", rank.get("results", [])) or []
    if rank.get("market_status"):
        st.caption(f"Market session: {rank['market_status']}")
    if not rows:
        st.info("Nothing evaluated yet — run a monitor pass from Scanner.")
        return
    _dataframe(_signals_frame(rows))


def show_alerts_page() -> None:
    _masthead(_safe_health())
    _section("Alerts", "Persisted history and delivery test")
    if _offline_banner():
        return
    if st.button("Send test alert", type="primary"):
        try:
            res = _run(send_test_alert(_client()))
            st.success(f"{res.get('status')}: {res.get('message')}")
        except ApiOfflineError as exc:
            st.error(str(exc))
    try:
        body = _run(alerts_history(_client()))
    except ApiOfflineError as exc:
        st.error(str(exc))
        return
    rows = body.get("alerts", []) or []
    st.caption(f"History ({body.get('total', len(rows))})")
    if not rows:
        st.info("No alerts persisted yet. Buy/sell signals land here.")
        return
    df = pd.DataFrame(rows)
    if "score" in df.columns:
        df["score"] = pd.to_numeric(df["score"], errors="coerce")
    _dataframe(df)


def show_settings() -> None:
    _masthead(_safe_health())
    _section("Settings", "Read-only monitor thresholds")
    if _offline_banner():
        return
    try:
        cfg = _run(monitor_config(_client()))
    except ApiOfflineError as exc:
        st.error(str(exc))
        return
    c1, c2 = st.columns(2)
    with c1:
        _kpi("Buy min score", str(cfg.get("buy_min_score", "—")), "threshold")
        _kpi("Buy min RVOL", f"{cfg.get('buy_min_rvol', '—')}x", "volume filter")
        _kpi(
            "Dollar gate",
            str(cfg.get("buy_min_dollar_volume") or "off"),
            "entry liquidity",
        )
        _kpi(
            "Catalyst required",
            str(cfg.get("buy_require_catalyst", False)),
            "entry conviction",
        )
    with c2:
        _kpi("Max spread", f"{cfg.get('buy_max_spread_pct', '—')}%", "liquidity guard")
        _kpi("Interval", f"{cfg.get('interval_seconds', '—')}s", "monitor loop")
        _kpi(
            "Take-profit / stop",
            f"{cfg.get('sell_take_profit_pct') or 'off'} / "
            f"{cfg.get('sell_stop_loss_pct') or 'off'}",
            "position exits",
        )
        _kpi(
            "Max BUYs / round",
            str(cfg.get("max_buys_per_round") or "unlimited"),
            "breadth cap",
        )
    with st.expander("Raw config"):
        st.json(cfg)
    st.caption("Edit values in config/settings.yaml — this page is read-only.")


_PAGES = {
    "Overview": show_dashboard,
    "Radar": show_radar,
    "Rankings": show_rankings,
    "Scanner": show_scanner,
    "Watchlists": show_watchlist,
    "Ticker desk": show_analysis,
    "Alerts": show_alerts_page,
    "Backtest": show_backtest,
    "Settings": show_settings,
}


def main() -> None:
    st.sidebar.markdown(
        "<p class='psi-nav-title'>PSI Desk</p>"
        "<div class='psi-nav-meta'>Index</div>",
        unsafe_allow_html=True,
    )
    page = st.sidebar.radio("Navigate", list(_PAGES.keys()), label_visibility="collapsed")
    _PAGES[page]()
    st.markdown(
        "<div class='psi-footer'>"
        "Analytical research tool · scores are ranking metrics, not probability "
        "forecasts · live trading disabled · review manually before acting in DEGIRO"
        "</div>",
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
