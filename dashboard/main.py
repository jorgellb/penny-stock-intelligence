"""Penny Stock Intelligence — Night Tape desk over the live FastAPI backend.

Every number comes from the API. Offline shows an explicit banner, never
zero-filled demo tables. Signals are for manual review, never orders.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import pandas as pd
import streamlit as st

from dashboard import charts
from dashboard import components as ui
from dashboard.api_client import (
    ApiOfflineError,
    add_symbol,
    alerts_history,
    health,
    make_client,
    monitor_config,
    monitor_events,
    monitor_paper_trades,
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
    stock_intraday,
    universe_scan,
    watchlist_symbols,
    watchlists,
)
from dashboard.theme import CSS

st.set_page_config(
    page_title="PSI · Night Tape",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.markdown(CSS, unsafe_allow_html=True)

API_URL = st.sidebar.text_input(
    "API endpoint",
    os.getenv("API_BASE_URL", "http://localhost:8000"),
    help="FastAPI base URL for this desk session.",
)

SCORE_WEIGHTS = {
    "momentum": 20,
    "volume": 20,
    "catalyst": 20,
    "technical": 15,
    "liquidity": 10,
    "fundamentals": 10,
    "data_quality": 5,
}


# ---------------------------------------------------------------------------
# plumbing
# ---------------------------------------------------------------------------


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


def _client(timeout: float = 15.0):  # type: ignore[no-untyped-def]
    return make_client(base_url=API_URL, timeout=timeout)


def html(fragment: str) -> None:
    st.markdown(fragment, unsafe_allow_html=True)


def md_safe(text: object) -> str:
    """Escape `$` so prices are not rendered as LaTeX by st.markdown."""
    return str(text).replace("$", "\\$")


@st.cache_data(ttl=5, show_spinner=False)
def _health_cached(base_url: str) -> dict | None:
    try:
        return _run(health(make_client(base_url=base_url, timeout=5.0)))
    except ApiOfflineError:
        return None


def _status_safe() -> dict:
    try:
        return _run(monitor_status(_client()))
    except ApiOfflineError:
        return {}


def header(status: dict | None = None) -> bool:
    """Top bar; returns False (and explains) when the API is offline."""
    payload = _health_cached(API_URL)
    live = bool(payload) and payload.get("status") == "healthy"  # type: ignore[union-attr]
    status = status or {}
    html(
        ui.top_bar(
            live,
            str((payload or {}).get("environment", "unknown")),
            regime=status.get("regime"),
            kill=bool(status.get("kill_switch")),
        )
    )
    if payload is None:
        html(
            ui.empty(
                f"Backend unreachable at {API_URL}. Start it with `make dev` or "
                "`docker compose up` and refresh."
            )
        )
        return False
    return True


def _signals_df(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    keep = [
        c
        for c in (
            "symbol",
            "action",
            "grade",
            "score",
            "setup",
            "price",
            "change_pct",
            "rvol",
            "vwap_distance_pct",
            "dollar_volume",
            "risk_flags",
            "timestamp",
        )
        if c in df.columns
    ]
    df = df[keep].copy()
    if "score" in df:
        df["score"] = pd.to_numeric(df["score"], errors="coerce")
        df = df.sort_values("score", ascending=False, na_position="last")
    if "risk_flags" in df:
        df["risk_flags"] = df["risk_flags"].apply(
            lambda v: ", ".join(v) if isinstance(v, list) else (v or "")
        )
    if "action" in df:
        df["action"] = df["action"].astype(str).str.upper()
    for col in ("grade", "setup"):
        if col in df:
            df[col] = df[col].fillna("").astype(str).replace("None", "")
    return df


def table(df: pd.DataFrame, height: int | None = None) -> None:
    cfg: dict[str, Any] = {
        "symbol": st.column_config.TextColumn("Symbol", width="small"),
        "action": st.column_config.TextColumn("Action", width="small"),
        "grade": st.column_config.TextColumn("Grade", width="small"),
        "setup": st.column_config.TextColumn("Setup"),
        "risk_flags": st.column_config.TextColumn("Risk flags"),
        "score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%d"),
        "price": st.column_config.NumberColumn("Price", format="$%.4f"),
        "change_pct": st.column_config.NumberColumn("Chg %", format="%+.2f%%"),
        "rvol": st.column_config.NumberColumn("RVOL", format="%.1fx"),
        "vwap_distance_pct": st.column_config.NumberColumn("vs VWAP", format="%+.2f%%"),
        "dollar_volume": st.column_config.NumberColumn("$ Vol", format="compact"),
        "rank_score": st.column_config.ProgressColumn("Rank", min_value=0, max_value=100),
        "timestamp": st.column_config.DatetimeColumn("Time", format="HH:mm:ss"),
    }
    kwargs: dict[str, Any] = {"use_container_width": True, "hide_index": True, "column_config": cfg}
    if height:
        kwargs["height"] = height
    st.dataframe(df, **kwargs)


def _actionable(rows: list[dict]) -> list[dict]:
    order = {"A": 0, "B": 1, "C": 2}
    acts = [r for r in rows if str(r.get("action", "")).lower() in ("buy", "sell")]
    return sorted(
        acts,
        key=lambda r: (
            0 if str(r.get("action")).lower() == "buy" else 1,
            order.get(str(r.get("grade") or "Z"), 3),
            -float(r.get("score") or 0),
        ),
    )


def _latest_per_symbol(events: list[dict]) -> list[dict]:
    seen: dict[str, dict] = {}
    for e in events:  # newest first
        seen.setdefault(str(e.get("symbol")), e)
    return list(seen.values())


# ---------------------------------------------------------------------------
# pages
# ---------------------------------------------------------------------------


def page_command() -> None:
    status = _status_safe()
    if not header(status):
        return
    c1, c2 = st.columns([4, 1])
    with c2:
        auto = st.toggle("Auto-refresh 30s", value=False, help="Re-reads monitor state every 30s")

    @st.fragment(run_every=30 if auto else None)
    def body() -> None:
        try:
            status_now = _run(monitor_status(_client()))
            events = _run(monitor_events(_client(), limit=200))
        except ApiOfflineError as exc:
            st.error(str(exc))
            return
        latest = _latest_per_symbol(events)
        paper = status_now.get("paper", {}) or {}
        stats = status_now.get("stats", {}) or {}
        buys = sum(1 for e in latest if str(e.get("action")).lower() == "buy")
        sells = sum(1 for e in latest if str(e.get("action")).lower() == "sell")
        graded_a = sum(1 for e in latest if e.get("grade") == "A")
        day_pnl = paper.get("daily_pnl_pct")
        kill = bool(status_now.get("kill_switch"))
        html(ui.section("Floor", "estado del monitor y del libro paper"))
        html(
            ui.kpi_row(
                [
                    ui.kpi(
                        "Regime",
                        str(status_now.get("regime", "unknown")).upper(),
                        "filtro de mercado",
                        tone={"risk_on": "up", "chop": "warn", "risk_off": "down"}.get(
                            str(status_now.get("regime")), ""
                        ),
                    ),
                    ui.kpi("Tracked", str(status_now.get("tracked_symbols", 0)), "símbolos"),
                    ui.kpi(
                        "Buy / Sell",
                        f"{buys} / {sells}",
                        f"{graded_a} grado A",
                        "up" if buys else "",
                    ),
                    ui.kpi(
                        "Paper equity",
                        ui.fmoney(paper.get("equity")),
                        f"día {ui.fnum(day_pnl, 2, suffix='%', sign=True)}",
                        ui.tone_class(day_pnl) if day_pnl else "",
                    ),
                    ui.kpi(
                        "Win rate",
                        ui.fnum(paper.get("win_rate"), 0, suffix="%")
                        if paper.get("win_rate") is not None
                        else "—",
                        f"{paper.get('closed_trades', 0)} trades cerrados",
                    ),
                    ui.kpi(
                        "Kill switch",
                        "ACTIVE" if kill else "OFF",
                        f"última ronda: {stats.get('symbols', 0)} sym",
                        "down" if kill else "up",
                    ),
                ]
            )
        )
        if status_now.get("vetoed_symbols"):
            st.warning(f"Vetados 24h: {', '.join(status_now['vetoed_symbols'])}")
        feed = status_now.get("feed") or {}
        if feed.get("warning"):
            st.warning(feed["warning"])

        html(ui.section("Actionable now", "BUY/SELL con plan · revisión manual, no recomendación"))
        act = _actionable(latest)
        if act:
            html(ui.cards(act[:12]))
        else:
            html(
                ui.empty(
                    "Sin señales accionables. Lanza una pasada desde Scanner o espera al loop."
                )
            )

        positions = paper.get("positions") or {}
        if positions:
            html(ui.section("Paper positions", "gestionadas por el plan: stop → break-even → T2"))
            pdf = pd.DataFrame([{"symbol": s, **v} for s, v in positions.items()]).rename(
                columns={"unrealized_pct": "pnl_%"}
            )
            st.dataframe(
                pdf,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "symbol": st.column_config.TextColumn("Symbol"),
                    "shares": st.column_config.NumberColumn("Shares", format="%d"),
                    "pnl_%": st.column_config.NumberColumn("P&L %", format="%+.2f%%"),
                    "entry": st.column_config.NumberColumn("Entry", format="$%.4f"),
                    "last": st.column_config.NumberColumn("Last", format="$%.4f"),
                    "stop": st.column_config.NumberColumn("Stop", format="$%.4f"),
                    "target": st.column_config.NumberColumn("Target", format="$%.4f"),
                },
            )

        html(ui.section("Tape", "última evaluación por símbolo"))
        df = _signals_df(latest)
        if df.empty:
            html(ui.empty("Aún no hay evaluaciones."))
        else:
            table(df, height=min(38 * (len(df) + 1), 520))

    with c1:
        st.caption("Señales del loop del monitor · tarjetas ordenadas por acción, grado y score")
    body()


def page_scanner() -> None:
    if not header(_status_safe()):
        return
    html(ui.section("Scanner", "una ronda completa del monitor sobre una lista"))
    try:
        lists = _run(watchlists(_client()))
        cfg = _run(monitor_config(_client()))
    except ApiOfflineError as exc:
        st.error(str(exc))
        return
    names = [str(item.get("name")) for item in lists] or ["default"]
    c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
    with c1:
        list_name = st.selectbox("Lista", names)
    with c2:
        min_score = st.slider("Score mín. (vista)", 0, 100, 0)
    with c3:
        actions = st.multiselect(
            "Acciones", ["buy", "sell", "hold"], default=["buy", "sell", "hold"]
        )
    with c4:
        st.write("")
        run = st.button("▶ Run pass", type="primary", use_container_width=True)
    st.caption(
        f"BUY score≥{cfg.get('buy_min_score')} · RVOL≥{cfg.get('buy_min_rvol')}x · "
        f"chase guard {'on' if cfg.get('buy_block_overextended', True) else 'off'} "
        f"(≤{cfg.get('extension_max_vwap_atr', 1.0)} ATR sobre VWAP, "
        f"RSI≤{cfg.get('extension_max_rsi', 88)}) · "
        f"plan stop {cfg.get('plan_min_stop_pct', 3)}–{cfg.get('plan_max_stop_pct', 12)}% · "
        f"R:R objetivo {cfg.get('plan_min_rr', 2)}"
    )
    if run:
        with st.spinner(f"Evaluando {list_name}…"):
            try:
                st.session_state["scan_result"] = _run(
                    run_monitor_pass(_client(timeout=240.0), list_name)
                )
            except ApiOfflineError as exc:
                st.error(str(exc))
                return
    result = st.session_state.get("scan_result")
    if not result:
        html(ui.empty("Pulsa Run pass para evaluar la lista."))
        return
    signals = [
        s
        for s in result.get("signals", [])
        if (s.get("score") or 0) >= min_score and s.get("action") in actions
    ]
    st.caption(f"{result.get('symbols', 0)} símbolos evaluados · lista {result.get('list')}")
    act = _actionable(signals)
    if act:
        html(ui.section("Signals", f"{len(act)} accionables"))
        html(ui.cards(act))
    html(ui.section("All results"))
    df = _signals_df(signals)
    if df.empty:
        html(ui.empty("Nada coincide con los filtros."))
    else:
        table(df)


def page_ticker() -> None:
    if not header(_status_safe()):
        return
    html(ui.section("Ticker desk", "snapshot en vivo · intradía · diario · anatomía del score"))
    c1, c2 = st.columns([3, 1])
    with c1:
        symbol = st.text_input("Ticker", placeholder="ABCD", key="ticker_sym")
    with c2:
        days = st.selectbox("Historia diaria", [60, 120, 250, 500], index=1)
    if not symbol.strip():
        html(ui.empty("Introduce un ticker para analizarlo."))
        return
    sym = symbol.strip().upper()
    with st.spinner(f"Cargando {sym}…"):
        try:
            snap = _run(stock(_client(timeout=120.0), sym))
            hist = _run(stock_history(_client(timeout=60.0), sym, days=days))
        except ApiOfflineError as exc:
            st.error(str(exc))
            return
        try:
            intra = _run(stock_intraday(_client(timeout=60.0), sym))
        except ApiOfflineError:
            intra = {"bars": []}

    score = float(snap.get("score") or 0)
    plan = snap.get("trade_plan")
    tech = snap.get("technical") or {}
    session = snap.get("session") or {}
    h1, h2 = st.columns([2.2, 1])
    with h1:
        sig = {
            **snap,
            "dollar_volume": snap.get("dollar_volume"),
            "risk_flags": snap.get("risk_flags"),
            "catalyst_summary": (snap.get("catalyst") or {}).get("summary"),
            "order_template": snap.get("order_template"),
        }
        html(ui.signal_card(sig))
        if snap.get("overextended"):
            st.warning(md_safe("Extendido: " + "; ".join(snap.get("extension_reasons") or [])))
        if snap.get("stale"):
            st.warning("Datos de mercado obsoletos — trata este snapshot con cautela.")
    with h2:
        st.plotly_chart(
            charts.score_gauge(score, snap.get("grade")),
            use_container_width=True,
            config={"displayModeBar": False},
        )
        html(
            ui.kpi_row(
                [
                    ui.kpi("Session", str(session.get("phase") or "—").upper(), "fase"),
                    ui.kpi("Prev close", ui.fprice(session.get("prev_close")), ""),
                    ui.kpi("PM high", ui.fprice(session.get("premarket_high")), ""),
                    ui.kpi(
                        "Float rot.",
                        ui.fnum(snap.get("float_rotation"), 2, suffix="x"),
                        "vol / float",
                    ),
                ]
            )
        )

    tab_i, tab_d, tab_s, tab_c, tab_r, tab_f = st.tabs(
        ["Intraday", "Daily", "Score", "Catalyst & flow", "Risk", "Fundamentals"]
    )
    with tab_i:
        fig = charts.intraday_chart(intra.get("bars", []), sym, plan, session)
        if fig is None:
            html(ui.empty(intra.get("note", "Sin datos intradía.")))
        else:
            st.plotly_chart(fig, use_container_width=True)
    with tab_d:
        fig = charts.daily_chart(list(hist.get("bars", [])), sym, plan)
        if fig is None:
            html(ui.empty(hist.get("note", "Sin historia para esta ventana.")))
        else:
            st.plotly_chart(fig, use_container_width=True)
        facts = tech.get("facts") or {}
        if facts:
            html(
                ui.kpi_row(
                    [
                        ui.kpi("RSI 14", ui.fnum(facts.get("rsi_14"), 1), "Wilder"),
                        ui.kpi(
                            "From 20d high",
                            ui.fnum(facts.get("pct_from_20d_high"), 1, suffix="%"),
                            "",
                        ),
                        ui.kpi(
                            "From 52w high",
                            ui.fnum(facts.get("pct_from_52w_high"), 1, suffix="%"),
                            "",
                        ),
                        ui.kpi(
                            "BB width pct.", ui.fnum(facts.get("bb_width_pctile"), 0), "<20 = coil"
                        ),
                        ui.kpi("ATR %", ui.fnum(tech.get("atr_pct"), 1, suffix="%"), "diario"),
                    ]
                )
            )
        for r in tech.get("technical_reasons") or []:
            st.caption(f"· {md_safe(r)}")
    with tab_s:
        bd = snap.get("score_breakdown") or {}
        comps = bd.get("components") or {}
        s1, s2 = st.columns([1.4, 1])
        with s1:
            st.plotly_chart(
                charts.score_bars(comps, SCORE_WEIGHTS, bd.get("penalties")),
                use_container_width=True,
                config={"displayModeBar": False},
            )
            st.caption(
                f"Base {bd.get('raw', '—')} − penalización {bd.get('penalty', '—')} = "
                f"{bd.get('final', '—')} · calidad de datos {bd.get('data_quality', '—')} · "
                f"catalizador {bd.get('catalyst_strength') or 'n/d (re-normalizado)'}"
            )
        with s2:
            subs = snap.get("subscores") or {}
            if subs:
                html(
                    ui.kpi_row(
                        [
                            ui.kpi(k.replace("_", " "), ui.fnum(v, 0), "sub-score 0-100")
                            for k, v in subs.items()
                        ]
                    )
                )
        html(ui.section("Reasons"))
        for r in snap.get("reasons", []):
            st.markdown(f"- {md_safe(r)}")
        if snap.get("order_template"):
            with st.expander("Plantilla de orden manual (revisar en DEGIRO)"):
                st.json(snap["order_template"])
    with tab_c:
        cat = snap.get("catalyst") or {}
        if cat:
            st.markdown(f"**{md_safe(cat.get('summary', 'Catalyst'))}**")
            st.caption(
                f"Impacto {cat.get('impact')} · confianza {cat.get('confidence')} · "
                f"hace {float(cat.get('age_hours', 0) or 0):.1f}h · "
                f"fuente primaria {cat.get('primary')}"
            )
        else:
            html(
                ui.empty(
                    "Sin catalizador detectado en 48h (o proveedor de noticias no configurado)."
                )
            )
        acc = snap.get("accumulation") or {}
        if acc:
            st.markdown(f"**Acumulación sigilosa** (score {acc.get('score')})")
            for r in acc.get("reasons", []):
                st.caption(f"· {md_safe(r)}")
        climax = tech.get("climax") or {}
        if climax:
            st.warning(
                f"Clímax de distribución: volumen {climax.get('volume_multiple')}x tras "
                f"+{climax.get('runup_pct')}% — no perseguir"
            )
        st.caption(
            f"Donchian gate: {'superado' if snap.get('donchian_gate') else 'no / n/a'} · "
            f"squeeze {'activo' if tech.get('squeeze_active') else 'inactivo'} · "
            f"markup {'listo' if tech.get('markup_ready') else 'no'}"
        )
        news = snap.get("news", []) or []
        for n in news:
            st.markdown(f"- **{md_safe(n.get('headline'))}** ({n.get('source', '')})")
    with tab_r:
        frozen = bool(snap.get("dilution_frozen"))
        halted = bool(snap.get("halted"))
        html(
            ui.kpi_row(
                [
                    ui.kpi(
                        "Dilution freeze",
                        "YES" if frozen else "NO",
                        "offering/ATM/shelf",
                        "down" if frozen else "up",
                    ),
                    ui.kpi(
                        "Halt", "YES" if halted else "NO", "trading", "down" if halted else "up"
                    ),
                    ui.kpi(
                        "Dollar rule", str(snap.get("dollar_rule", "—")).upper(), "cierres < $1"
                    ),
                    ui.kpi(
                        "Veto / kill",
                        f"{'YES' if snap.get('vetoed') else 'NO'} / "
                        f"{'ON' if snap.get('kill_switch') else 'OFF'}",
                        "circuitos",
                        "down" if snap.get("vetoed") or snap.get("kill_switch") else "",
                    ),
                ]
            )
        )
        fil = snap.get("filings", {}) or {}
        for r in fil.get("reasons") or []:
            st.caption(f"· {md_safe(r)}")
        if fil.get("note"):
            st.caption(f"Filings: {fil['note']}")
        flags = snap.get("risk_flags", []) or []
        if flags:
            html("".join(f"<span class='nt-chip risk'>{f}</span> " for f in flags))
        else:
            st.success("Sin flags de riesgo activos.")
    with tab_f:
        fund = snap.get("fundamentals") or {}
        if fund:
            labels = [
                ("market_cap", "Market cap", True),
                ("revenue_ttm", "Revenue TTM", True),
                ("net_income", "Net income", True),
                ("cash", "Cash", True),
                ("total_debt", "Total debt", True),
                ("shares_outstanding", "Shares out.", False),
                ("float_shares", "Float", False),
            ]
            html(
                ui.kpi_row(
                    [
                        ui.kpi(
                            label,
                            ui.fmoney(fund.get(key)) if money else ui.fnum(fund.get(key), 0),
                            "",
                        )
                        for key, label, money in labels
                    ]
                )
            )
        else:
            html(ui.empty(snap.get("fundamentals_note", "Sin fundamentales.")))


def page_radar() -> None:
    if not header(_status_safe()):
        return
    html(ui.section("Opportunity radar", "movers rankeados + sincronización a la lista radar"))
    c1, c2 = st.columns(2)
    with c1:
        if st.button("↻ Refresh", type="primary", use_container_width=True):
            st.rerun()
    with c2:
        if st.button("Sync top names → radar list", use_container_width=True):
            with st.spinner("Radar pass…"):
                try:
                    res = _run(run_radar(_client(timeout=60.0)))
                    st.success(
                        f"{res.get('status')}: +{res.get('added', 0)} → {res.get('list')} "
                        f"({res.get('ranked', 0)} rankeados)"
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
    html("".join(f"<span class='nt-chip'>{s}</span> " for s in enabled))
    rows = body.get("opportunities", []) or []
    if not rows:
        html(ui.empty("Sin oportunidades rankeadas aún. Ejecuta una pasada del monitor."))
        return
    df = pd.DataFrame(rows)
    for col in ("setups_hint", "reasons"):
        if col in df:
            df[col] = df[col].apply(lambda v: ", ".join(v) if isinstance(v, list) else v)
    table(df)


def page_rankings() -> None:
    if not header(_status_safe()):
        return
    html(ui.section("Universe", "elegibilidad por precio/liquidez con cotizaciones en vivo"))
    with st.form("universe_form"):
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            limit = st.selectbox("Símbolos", [25, 50, 100, 200], index=1)
        with c2:
            min_price = st.number_input("Precio mín.", value=0.10, step=0.10)
        with c3:
            max_price = st.number_input("Precio máx.", value=5.00, step=0.50)
        with c4:
            exchange = st.selectbox("Exchange", ["All", "NASDAQ", "NYSE", "AMEX"])
        go = st.form_submit_button("Scan universe", type="primary")
    if go:
        if min_price >= max_price:
            st.warning("El precio mínimo debe ser menor que el máximo.")
            return
        with st.spinner(f"Escaneando {limit} símbolos…"):
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
        html(
            ui.kpi_row(
                [
                    ui.kpi(
                        "Scanned", str(body.get("total", 0)), f"{body.get('duration_ms', 0)} ms"
                    ),
                    ui.kpi(
                        "Eligible", str(body.get("eligible_count", 0)), "precio + liquidez", "up"
                    ),
                    ui.kpi(
                        "Quotes", str(stats.get("quotes_ok", stats.get("ok", "—"))), "proveedor"
                    ),
                ]
            )
        )
        elig = body.get("eligible", []) or []
        if elig:
            table(pd.DataFrame(elig))
        else:
            html(ui.empty("Ningún elegible en este tramo. Amplía el rango de precios."))
    html(ui.section("Monitor rankings", "símbolos ya evaluados"))
    kind = st.segmented_control("Ranking", ["intraday", "premarket", "overall"], default="intraday")
    try:
        rank = _run(scanner_rankings(_client(), kind=kind or "intraday"))
    except ApiOfflineError as exc:
        st.error(str(exc))
        return
    rows = rank.get("rankings", rank.get("results", [])) or []
    if rank.get("market_status"):
        st.caption(f"Sesión: {rank['market_status']}")
    if not rows:
        html(ui.empty("Nada evaluado aún — lanza una pasada desde Scanner."))
        return
    table(_signals_df(rows))


def page_watchlists() -> None:
    if not header(_status_safe()):
        return
    html(ui.section("Watchlists", "listas persistentes que vigila el monitor"))
    try:
        lists = _run(watchlists(_client()))
    except ApiOfflineError as exc:
        st.error(str(exc))
        return
    names = [str(item.get("name")) for item in lists] or ["default"]
    c1, c2 = st.columns([1, 2])
    with c1:
        list_name = st.selectbox("Lista", names, key="wl_list")
    with c2, st.form("add_symbol_form", clear_on_submit=True):
        a1, a2 = st.columns([3, 1])
        with a1:
            raw = st.text_input("Añadir símbolos (separados por coma)", placeholder="ABCD, EFGH")
        with a2:
            st.write("")
            submitted = st.form_submit_button("Add", use_container_width=True)
        if submitted:
            symbols = [s.strip().upper() for s in raw.split(",") if s.strip()]
            if not symbols:
                st.warning("Introduce al menos un símbolo.")
            for s in symbols:
                try:
                    res = _run(add_symbol(_client(), list_name, s))
                    st.toast(f"{res.get('status')}: {res.get('symbol')}")
                except ApiOfflineError as exc:
                    st.error(str(exc))
    try:
        syms = _run(watchlist_symbols(_client(), list_name))
    except ApiOfflineError as exc:
        st.error(str(exc))
        return
    st.caption(f"{list_name} · {len(syms)} símbolos")
    if not syms:
        html(ui.empty("Lista vacía. Añade símbolos arriba."))
        return
    cols = st.columns(6)
    for i, s in enumerate(syms):
        with cols[i % 6]:
            if st.button(f"✕ {s}", key=f"rm_{s}", use_container_width=True, help=f"Quitar {s}"):
                try:
                    _run(remove_symbol(_client(), list_name, s))
                    st.rerun()
                except ApiOfflineError as exc:
                    st.error(str(exc))


def page_backtest() -> None:
    if not header(_status_safe()):
        return
    html(ui.section("Backtest", "regla RVOL-momentum · fills realistas · informativo"))
    with st.form("backtest_form"):
        symbols = st.text_input("Símbolos (coma)", placeholder="ABCD,EFGH")
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            days = st.slider("Días de historia", 30, 730, 250)
            entry = st.selectbox("Entrada", ["next_open", "close"], help="next_open = realista")
        with c2:
            min_rvol = st.slider("RVOL mín.", 1.0, 10.0, 2.0, step=0.5)
            min_change = st.slider("Cambio mín. %", 0.0, 50.0, 5.0, step=1.0)
        with c3:
            stop = st.slider("Stop %", -30.0, -1.0, -8.0, step=0.5)
            target = st.slider("Target % (0 = off)", 0.0, 100.0, 20.0, step=1.0)
        with c4:
            hold = st.slider("Días máx. en posición", 1, 30, 5)
            min_score = st.slider("Score mín.", 0, 100, 0)
        run = st.form_submit_button("Run backtest", type="primary")
    if run:
        if not symbols.strip():
            st.warning("Introduce al menos un símbolo.")
            return
        with st.spinner("Ejecutando…"):
            try:
                st.session_state["bt"] = _run(
                    run_backtest(
                        _client(timeout=300.0),
                        symbols,
                        days=days,
                        min_rvol=min_rvol,
                        min_change_pct=min_change,
                        holding_days=hold,
                        stop_pct=stop,
                        target_pct=target or None,
                        min_score=min_score,
                        entry=entry,
                    )
                )
            except ApiOfflineError as exc:
                st.error(str(exc))
                return
    result = st.session_state.get("bt")
    if not result:
        html(ui.empty("Configura la regla y ejecuta el backtest."))
        return
    m = result.get("metrics", {})
    pf = m.get("profit_factor", 0)
    html(
        ui.kpi_row(
            [
                ui.kpi("Trades", str(int(m.get("number_of_signals", 0))), "señales"),
                ui.kpi(
                    "Win rate",
                    ui.fnum(m.get("win_rate"), 1, suffix="%"),
                    "cerrados",
                    "up" if (m.get("win_rate") or 0) >= 50 else "",
                ),
                ui.kpi(
                    "Expectancy",
                    ui.fnum(m.get("expectancy"), 2, suffix="%", sign=True),
                    "por trade",
                    ui.tone_class(m.get("expectancy")),
                ),
                ui.kpi(
                    "Profit factor",
                    "∞" if pf == float("inf") else ui.fnum(pf, 2),
                    "",
                    "up" if pf and pf > 1 else "down",
                ),
                ui.kpi("Payoff", ui.fnum(m.get("payoff_ratio"), 2), "avg win / avg loss"),
                ui.kpi(
                    "Return (20%/trade)",
                    ui.fnum(m.get("total_return_compounded"), 1, suffix="%", sign=True),
                    "compuesto",
                    ui.tone_class(m.get("total_return_compounded")),
                ),
                ui.kpi(
                    "Max DD", ui.fnum(m.get("max_drawdown_equity"), 1, suffix="%"), "equity", "down"
                ),
                ui.kpi("Sharpe/trade", ui.fnum(m.get("sharpe_per_trade"), 2), ""),
            ]
        )
    )
    fig = charts.equity_curve_chart(result.get("equity_curve", []))
    if fig is not None:
        st.plotly_chart(fig, use_container_width=True)
    trades = result.get("trades", [])
    b1, b2 = st.columns(2)
    with b1:
        h = charts.returns_histogram(
            [t["return_pct"] for t in trades if t.get("return_pct") is not None]
        )
        if h is not None:
            st.plotly_chart(h, use_container_width=True)
    with b2:
        c = charts.calibration_chart(result.get("calibration", {}))
        if c is not None:
            st.plotly_chart(c, use_container_width=True)
    html(ui.section("Trades"))
    if trades:
        tdf = pd.DataFrame(trades)
        for col in ("entry", "exit"):
            if col in tdf:
                tdf[col] = pd.to_datetime(tdf[col], utc=True, errors="coerce").dt.tz_localize(None)
        st.dataframe(
            tdf,
            use_container_width=True,
            hide_index=True,
            column_config={
                "symbol": st.column_config.TextColumn("Symbol"),
                "entry": st.column_config.DatetimeColumn("Entry date", format="YYYY-MM-DD"),
                "exit": st.column_config.DatetimeColumn("Exit date", format="YYYY-MM-DD"),
                "exit_reason": st.column_config.TextColumn("Exit"),
                "return_pct": st.column_config.NumberColumn("Return", format="%+.2f%%"),
                "entry_price": st.column_config.NumberColumn("Entry", format="$%.4f"),
                "exit_price": st.column_config.NumberColumn("Exit", format="$%.4f"),
                "score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100),
            },
        )
    else:
        html(ui.empty("Ningún trade cumplió la regla en esta ventana."))
    wf = (result.get("walk_forward") or {}).get("mean")
    if wf:
        st.caption(
            f"Walk-forward (fuera de muestra) · win {wf.get('win_rate', 0):.1f}% · "
            f"avg {wf.get('average_return', 0):+.2f}%"
        )
    if result.get("skipped"):
        st.warning(f"Omitidos: {', '.join(result['skipped'])}")
    st.caption(result.get("disclaimer", ""))


def page_journal() -> None:
    if not header(_status_safe()):
        return
    html(ui.section("Journal", "alertas enviadas y trades paper cerrados"))
    t1, t2 = st.tabs(["Paper trades", "Alerts"])
    with t1:
        try:
            body = _run(monitor_paper_trades(_client()))
        except ApiOfflineError as exc:
            st.error(str(exc))
            body = {}
        trades = body.get("trades", []) or []
        if trades:
            df = pd.DataFrame(trades)
            wins = (df["pnl_dollars"] > 0).mean() * 100 if "pnl_dollars" in df else 0
            html(
                ui.kpi_row(
                    [
                        ui.kpi("Trades", str(len(df)), "persistidos"),
                        ui.kpi("Win rate", ui.fnum(wins, 0, suffix="%"), ""),
                        ui.kpi(
                            "P&L",
                            ui.fmoney(df["pnl_dollars"].sum()),
                            "neto de costes",
                            ui.tone_class(df["pnl_dollars"].sum()),
                        ),
                    ]
                )
            )
            st.dataframe(
                df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "pnl_pct": st.column_config.NumberColumn("P&L %", format="%+.2f%%"),
                    "pnl_dollars": st.column_config.NumberColumn("P&L $", format="$%+.2f"),
                },
            )
        else:
            html(ui.empty("Sin trades paper cerrados todavía."))
    with t2:
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
        st.caption(f"Historial ({body.get('total', len(rows))})")
        if not rows:
            html(ui.empty("Sin alertas persistidas. Las señales BUY/SELL aparecen aquí."))
            return
        df = pd.DataFrame(rows)
        if "score" in df.columns:
            df["score"] = pd.to_numeric(df["score"], errors="coerce")
        table(df)


def page_settings() -> None:
    if not header(_status_safe()):
        return
    html(ui.section("Settings", "umbrales del monitor (solo lectura)"))
    try:
        cfg = _run(monitor_config(_client()))
    except ApiOfflineError as exc:
        st.error(str(exc))
        return
    html(
        ui.kpi_row(
            [
                ui.kpi("Buy min score", str(cfg.get("buy_min_score", "—")), "umbral"),
                ui.kpi("Buy min RVOL", f"{cfg.get('buy_min_rvol', '—')}x", "volumen"),
                ui.kpi("Max spread", f"{cfg.get('buy_max_spread_pct', '—')}%", "liquidez"),
                ui.kpi("Interval", f"{cfg.get('interval_seconds', '—')}s", "loop"),
                ui.kpi(
                    "Chase guard",
                    "ON" if cfg.get("buy_block_overextended", True) else "OFF",
                    f"≤{cfg.get('extension_max_vwap_atr', '—')} ATR sobre VWAP",
                ),
                ui.kpi(
                    "Plan stop",
                    f"{cfg.get('plan_min_stop_pct', '—')}–{cfg.get('plan_max_stop_pct', '—')}%",
                    "estructural, acotado",
                ),
                ui.kpi(
                    "Plan exits",
                    "ON" if cfg.get("plan_exits_enabled", True) else "OFF",
                    "stop → BE → T2",
                ),
                ui.kpi("Max BUYs/round", str(cfg.get("max_buys_per_round") or "∞"), "breadth cap"),
            ]
        )
    )
    with st.expander("Raw config"):
        st.json(cfg)
    st.caption("Edita valores en config/settings.yaml — esta página es de solo lectura.")


def main() -> None:
    pages = {
        "Desk": [
            st.Page(page_command, title="Command", icon="🛰️", default=True),
            st.Page(page_scanner, title="Scanner", icon="⚡", url_path="scanner"),
            st.Page(page_ticker, title="Ticker desk", icon="🔎", url_path="ticker"),
            st.Page(page_radar, title="Radar", icon="📡", url_path="radar"),
        ],
        "Universe": [
            st.Page(page_rankings, title="Rankings", icon="🏁", url_path="rankings"),
            st.Page(page_watchlists, title="Watchlists", icon="🗂️", url_path="watchlists"),
        ],
        "Review": [
            st.Page(page_backtest, title="Backtest", icon="🧪", url_path="backtest"),
            st.Page(page_journal, title="Journal", icon="📒", url_path="journal"),
            st.Page(page_settings, title="Settings", icon="⚙️", url_path="settings"),
        ],
    }
    nav = st.navigation(pages, position="sidebar")
    nav.run()
    html(
        "<div class='nt-foot'>Herramienta de análisis · los scores son métricas de ranking, "
        "no probabilidades · trading en vivo desactivado · revisa manualmente antes de operar "
        "en DEGIRO</div>"
    )


if __name__ == "__main__":
    main()
