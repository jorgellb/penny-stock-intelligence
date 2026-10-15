"""Plotly figures for the desk. Pure functions: data in, figure out.

Indicators are recomputed locally with pandas so the dashboard container
stays decoupled from the backend package.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from dashboard import theme as t


def _frame(bars: list[dict], time_key: str) -> pd.DataFrame:
    df = pd.DataFrame(bars)
    if df.empty:
        return df
    df["x"] = pd.to_datetime(df[time_key], utc=True, errors="coerce")
    if time_key == "date":
        df["x"] = df["x"].dt.tz_convert(None).dt.normalize()
    else:
        df["x"] = df["x"].dt.tz_convert("America/New_York")
    return df.dropna(subset=["x"]).reset_index(drop=True)


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """EMA 9/20/50, Bollinger(20,2), Wilder RSI 14, MACD(12,26,9)."""
    c = df["close"].astype(float)
    for n in (9, 20, 50):
        df[f"ema{n}"] = c.ewm(span=n, adjust=False).mean() if len(c) >= n else None
    mid = c.rolling(20).mean()
    sd = c.rolling(20).std()
    df["bb_up"], df["bb_lo"] = mid + 2 * sd, mid - 2 * sd
    delta = c.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    rs = gain / loss.replace(0, float("nan"))
    df["rsi"] = (100 - 100 / (1 + rs)).fillna(100.0).where(loss.notna())
    macd = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    df["macd_hist"] = macd - macd.ewm(span=9, adjust=False).mean()
    return df


def _plan_lines(fig: Any, plan: dict | None, row: int = 1) -> None:
    if not plan:
        return
    levels = [
        ("ENTRY", plan.get("entry"), t.TEXT, "solid"),
        ("STOP", plan.get("stop"), t.DOWN, "dash"),
    ]
    for i, tgt in enumerate(plan.get("targets") or [], start=1):
        levels.append((f"T{i}", tgt, t.UP, "dot"))
    for label, y, color, dash in levels:
        if y is None:
            continue
        fig.add_hline(
            y=float(y),
            line_color=color,
            line_dash=dash,
            line_width=1,
            row=row,
            col=1,
            annotation_text=f"{label} {float(y):.4g}",
            annotation_position="top left",
            annotation_font={"color": color, "size": 10},
        )


def daily_chart(bars: list[dict], symbol: str, plan: dict | None = None) -> Any | None:
    """Candles + EMAs + Bollinger + volume + RSI + MACD histogram."""
    if not bars:
        return None
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    df = add_indicators(_frame(bars, "date"))
    if df.empty:
        return None
    up = df["close"] >= df["open"]
    fig = make_subplots(
        rows=4,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.025,
        row_heights=[0.56, 0.14, 0.15, 0.15],
    )
    fig.add_trace(go.Scatter(x=df["x"], y=df["bb_up"], line={"width": 0}, hoverinfo="skip"), 1, 1)
    fig.add_trace(
        go.Scatter(
            x=df["x"],
            y=df["bb_lo"],
            line={"width": 0},
            fill="tonexty",
            fillcolor="rgba(88,166,255,0.06)",
            hoverinfo="skip",
        ),
        1,
        1,
    )
    fig.add_trace(
        go.Candlestick(
            x=df["x"],
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            name=symbol,
            increasing={"line": {"color": t.UP}, "fillcolor": t.UP},
            decreasing={"line": {"color": t.DOWN}, "fillcolor": t.DOWN},
        ),
        1,
        1,
    )
    for col, color, name in (
        ("ema9", t.ACCENT, "EMA9"),
        ("ema20", t.INFO, "EMA20"),
        ("ema50", t.VIOLET, "EMA50"),
    ):
        if df[col].notna().any():
            fig.add_trace(
                go.Scatter(x=df["x"], y=df[col], name=name, line={"color": color, "width": 1.2}),
                1,
                1,
            )
    fig.add_trace(
        go.Bar(
            x=df["x"],
            y=df["volume"],
            name="Vol",
            marker_color=[t.UP if u else t.DOWN for u in up],
            opacity=0.55,
        ),
        2,
        1,
    )
    fig.add_trace(
        go.Scatter(x=df["x"], y=df["rsi"], name="RSI", line={"color": t.ACCENT, "width": 1.3}), 3, 1
    )
    for lvl in (30, 70):
        fig.add_hline(y=lvl, line_color=t.DIM, line_dash="dot", line_width=1, row=3, col=1)
    fig.add_trace(
        go.Bar(
            x=df["x"],
            y=df["macd_hist"],
            name="MACD hist",
            marker_color=[t.UP if v >= 0 else t.DOWN for v in df["macd_hist"].fillna(0)],
        ),
        4,
        1,
    )
    _plan_lines(fig, plan)
    fig.update_layout(
        **t.plotly_layout(
            640,
            title={
                "text": f"{symbol} · DAILY · EMA 9/20/50 · BB 20/2 · RSI 14 · MACD",
                "font": {"size": 11, "color": t.MUTED},
            },
            xaxis_rangebreaks=[{"bounds": ["sat", "mon"]}],
            bargap=0.15,
        )
    )
    fig.update_yaxes(range=[0, 100], row=3, col=1)
    return t.style_axes(fig)


def intraday_chart(
    bars: list[dict], symbol: str, plan: dict | None = None, session: dict | None = None
) -> Any | None:
    """Latest session 5m candles with VWAP, premarket shading and plan levels."""
    if not bars:
        return None
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    df = _frame(bars, "ts")
    if df.empty:
        return None
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.78, 0.22]
    )
    pre = df[~df["regular"].astype(bool)] if "regular" in df else df.iloc[0:0]
    if not pre.empty:
        reg_start = df[df["regular"].astype(bool)]["x"].min() if df["regular"].any() else None
        pre_before = pre[pre["x"] < reg_start] if reg_start is not None else pre
        if not pre_before.empty:
            fig.add_vrect(
                x0=pre_before["x"].min(),
                x1=pre_before["x"].max(),
                fillcolor="rgba(245,184,61,0.05)",
                line_width=0,
                row=1,
                col=1,
                annotation_text="PRE",
                annotation_position="top left",
                annotation_font={"size": 9, "color": t.DIM},
            )
    fig.add_trace(
        go.Candlestick(
            x=df["x"],
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            name=symbol,
            increasing={"line": {"color": t.UP}, "fillcolor": t.UP},
            decreasing={"line": {"color": t.DOWN}, "fillcolor": t.DOWN},
        ),
        1,
        1,
    )
    if "vwap" in df and df["vwap"].notna().any():
        fig.add_trace(
            go.Scatter(x=df["x"], y=df["vwap"], name="VWAP", line={"color": t.INFO, "width": 1.6}),
            1,
            1,
        )
    up = df["close"] >= df["open"]
    fig.add_trace(
        go.Bar(
            x=df["x"],
            y=df["volume"],
            name="Vol",
            marker_color=[t.UP if u else t.DOWN for u in up],
            opacity=0.55,
        ),
        2,
        1,
    )
    session = session or {}
    for key, label, color in (
        ("premarket_high", "PM HIGH", t.ACCENT),
        ("opening_range_high", "OR HIGH", t.VIOLET),
        ("prev_close", "PREV CLOSE", t.DIM),
    ):
        val = session.get(key)
        if val:
            fig.add_hline(
                y=float(val),
                line_color=color,
                line_dash="dot",
                line_width=1,
                row=1,
                col=1,
                annotation_text=f"{label} {float(val):.4g}",
                annotation_position="bottom right",
                annotation_font={"color": color, "size": 9},
            )
    _plan_lines(fig, plan)
    fig.update_layout(
        **t.plotly_layout(
            520,
            title={
                "text": f"{symbol} · INTRADAY 5m · VWAP · extended hours",
                "font": {"size": 11, "color": t.MUTED},
            },
            bargap=0.1,
        )
    )
    return t.style_axes(fig)


def score_gauge(score: float, grade: str | None = None) -> Any:
    import plotly.graph_objects as go

    color = (
        t.UP if score >= 80 else (t.INFO if score >= 70 else (t.WARN if score >= 50 else t.DOWN))
    )
    fig = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=score,
            number={
                "font": {"family": "JetBrains Mono", "size": 34, "color": t.TEXT},
                "suffix": f" {grade}" if grade else "",
            },
            gauge={
                "axis": {"range": [0, 100], "tickcolor": t.DIM, "showticklabels": False},
                "bar": {"color": color, "thickness": 0.28},
                "bgcolor": t.SURFACE_2,
                "borderwidth": 0,
                "steps": [
                    {"range": [0, 50], "color": "#1a1416"},
                    {"range": [50, 70], "color": "#1b1a14"},
                    {"range": [70, 100], "color": "#121c18"},
                ],
                "threshold": {"line": {"color": t.ACCENT, "width": 2}, "value": 70},
            },
        )
    )
    fig.update_layout(**t.plotly_layout(190, margin={"l": 18, "r": 18, "t": 10, "b": 0}))
    return fig


def score_bars(
    components: dict[str, Any], weights: dict[str, int], penalties: dict[str, Any] | None = None
) -> Any:
    """Horizontal bars: earned points vs available weight, penalties in red."""
    import plotly.graph_objects as go

    names = list(weights)
    earned = [float(components.get(n, 0) or 0) for n in names]
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            y=names,
            x=[weights[n] for n in names],
            orientation="h",
            marker_color=t.SURFACE_2,
            hoverinfo="skip",
        )
    )
    fig.add_trace(
        go.Bar(
            y=names,
            x=earned,
            orientation="h",
            marker_color=t.INFO,
            text=[f"{e:.0f}/{weights[n]}" for e, n in zip(earned, names, strict=False)],
            textposition="outside",
            textfont={"color": t.TEXT, "size": 10},
        )
    )
    for name, pen in (penalties or {}).items():
        fig.add_trace(
            go.Bar(
                y=[name],
                x=[-float(pen)],
                orientation="h",
                marker_color=t.DOWN,
                text=[f"-{float(pen):.0f}"],
                textposition="outside",
                textfont={"color": t.DOWN, "size": 10},
            )
        )
    fig.update_layout(
        **t.plotly_layout(
            60 + 30 * (len(names) + len(penalties or {})),
            barmode="overlay",
            hovermode=False,
            margin={"l": 8, "r": 40, "t": 8, "b": 8},
        )
    )
    fig.update_yaxes(autorange="reversed", side="left", gridcolor="rgba(0,0,0,0)")
    fig.update_xaxes(gridcolor=t.GRID, zeroline=True, zerolinecolor=t.BORDER)
    return fig


def equity_curve_chart(curve: list[dict]) -> Any | None:
    if not curve:
        return None
    import plotly.graph_objects as go

    df = pd.DataFrame(curve)
    df["x"] = pd.to_datetime(df["date"], utc=True, errors="coerce")
    eq = df["equity"].astype(float)
    peak = eq.cummax()
    dd = (eq / peak - 1) * 100
    color = t.UP if eq.iloc[-1] >= 100 else t.DOWN
    from plotly.subplots import make_subplots

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, row_heights=[0.72, 0.28], vertical_spacing=0.04
    )
    fig.add_trace(
        go.Scatter(
            x=df["x"],
            y=eq,
            mode="lines",
            line={"color": color, "width": 2},
            fill="tozeroy",
            fillcolor="rgba(47,210,127,0.07)" if color == t.UP else "rgba(255,93,108,0.07)",
            name="Equity",
            customdata=df[["symbol", "return_pct"]],
            hovertemplate="%{y:.2f} · %{customdata[0]} %{customdata[1]:+.2f}%",
        ),
        1,
        1,
    )
    fig.add_hline(y=100, line_color=t.DIM, line_dash="dot", row=1, col=1)
    fig.add_trace(
        go.Scatter(
            x=df["x"],
            y=dd,
            mode="lines",
            line={"color": t.DOWN, "width": 1},
            fill="tozeroy",
            fillcolor="rgba(255,93,108,0.12)",
            name="Drawdown %",
        ),
        2,
        1,
    )
    fig.update_layout(
        **t.plotly_layout(
            400,
            title={
                "text": "EQUITY (base 100) · DRAWDOWN %",
                "font": {"size": 11, "color": t.MUTED},
            },
        )
    )
    fig.update_yaxes(range=[min(eq.min(), 100) * 0.98, max(eq.max(), 100) * 1.02], row=1, col=1)
    return t.style_axes(fig)


def returns_histogram(returns: list[float]) -> Any | None:
    if not returns:
        return None
    import plotly.graph_objects as go

    fig = go.Figure()
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r <= 0]
    fig.add_trace(go.Histogram(x=losses, marker_color=t.DOWN, opacity=0.8, nbinsx=20, name="loss"))
    fig.add_trace(go.Histogram(x=wins, marker_color=t.UP, opacity=0.8, nbinsx=20, name="win"))
    fig.update_layout(
        **t.plotly_layout(
            300,
            barmode="overlay",
            hovermode="closest",
            title={"text": "TRADE RETURN DISTRIBUTION %", "font": {"size": 11, "color": t.MUTED}},
        )
    )
    return t.style_axes(fig)


def calibration_chart(calibration: dict[str, dict[str, float]]) -> Any | None:
    rows = [(band, v) for band, v in calibration.items() if v.get("n", 0) > 0]
    if not rows:
        return None
    import plotly.graph_objects as go

    bands = [b for b, _ in rows]
    avg = [v["average_return"] for _, v in rows]
    fig = go.Figure(
        go.Bar(
            x=bands,
            y=avg,
            marker_color=[t.UP if a > 0 else t.DOWN for a in avg],
            text=[f"n={int(v['n'])} · win {v['win_rate']:.0f}%" for _, v in rows],
            textposition="outside",
            textfont={"size": 10, "color": t.MUTED},
        )
    )
    fig.update_layout(
        **t.plotly_layout(
            300,
            hovermode="closest",
            title={
                "text": "AVG RETURN BY SCORE BAND (point-in-time)",
                "font": {"size": 11, "color": t.MUTED},
            },
        )
    )
    return t.style_axes(fig)
