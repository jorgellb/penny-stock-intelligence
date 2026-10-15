"""Night Tape — dark trading-terminal design tokens for the Streamlit desk.

One palette shared by CSS and Plotly so tables, cards and charts read as a
single system. Semantic colors only: up/down for price, grade colors for
signal quality, accent for brand/navigation. No decoration without data.
"""

from __future__ import annotations

from typing import Any

BG = "#0A0E13"
SURFACE = "#11161E"
SURFACE_2 = "#171E28"
BORDER = "#222C3A"
GRID = "#1A222D"
TEXT = "#E6EDF3"
MUTED = "#8D9AAB"
DIM = "#5D6B7D"
ACCENT = "#F5B83D"  # amber: brand + focus
INFO = "#58A6FF"
UP = "#2FD27F"
DOWN = "#FF5D6C"
WARN = "#F5B83D"
VIOLET = "#A48BFA"

GRADE_COLORS = {"A": UP, "B": INFO, "C": WARN}
ACTION_COLORS = {"buy": UP, "sell": DOWN, "hold": MUTED}

MONO = "'JetBrains Mono', 'IBM Plex Mono', ui-monospace, monospace"
SANS = "'IBM Plex Sans', 'Inter', system-ui, sans-serif"

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap');

:root {{
  --bg: {BG}; --surface: {SURFACE}; --surface-2: {SURFACE_2}; --border: {BORDER};
  --text: {TEXT}; --muted: {MUTED}; --dim: {DIM}; --accent: {ACCENT};
  --info: {INFO}; --up: {UP}; --down: {DOWN}; --warn: {WARN}; --violet: {VIOLET};
}}

html, body, [class*="css"], .stApp {{ font-family: {SANS}; color: var(--text); }}
.stApp, [data-testid="stAppViewContainer"] {{
  background: radial-gradient(1200px 500px at 15% -10%, #142033 0%, var(--bg) 55%) !important; }}
[data-testid="stHeader"] {{ background: transparent !important; }}
.block-container {{ padding-top: .8rem; padding-bottom: 3rem; max-width: 1400px; }}
header[data-testid="stHeader"] {{ background: transparent; }}

/* —— top bar —— */
.nt-bar {{
  display: flex; flex-wrap: wrap; align-items: center; gap: .5rem 1rem;
  padding: .55rem .2rem .8rem; border-bottom: 1px solid var(--border); margin-bottom: 1rem;
}}
.nt-logo {{ font-family: {MONO}; font-weight: 700; font-size: 1.05rem; letter-spacing: .02em; }}
.nt-logo b {{ color: var(--accent); }}
.nt-logo span {{ color: var(--muted); font-weight: 500; font-size: .78rem; margin-left: .5rem;
  letter-spacing: .12em; text-transform: uppercase; }}
.nt-pills {{ display: flex; flex-wrap: wrap; gap: .4rem; margin-left: auto; }}
.nt-pill {{
  font-family: {MONO}; font-size: .68rem; letter-spacing: .08em; text-transform: uppercase;
  padding: .22rem .55rem; border: 1px solid var(--border); border-radius: 999px;
  color: var(--muted); background: var(--surface); white-space: nowrap;
}}
.nt-pill i {{ display: inline-block; width: .45rem; height: .45rem; border-radius: 50%;
  margin-right: .35rem; background: var(--dim); vertical-align: middle; }}
.nt-pill.ok i {{ background: var(--up); box-shadow: 0 0 8px var(--up); }}
.nt-pill.bad i {{ background: var(--down); box-shadow: 0 0 8px var(--down); }}
.nt-pill.warn i {{ background: var(--warn); }}
.nt-pill.info i {{ background: var(--info); }}

/* —— section heads —— */
.nt-h {{ display: flex; align-items: baseline; gap: .7rem; margin: 1.3rem 0 .6rem; }}
.nt-h h2 {{ font-size: .8rem; font-family: {MONO}; letter-spacing: .16em; text-transform: uppercase;
  color: var(--text); margin: 0; font-weight: 600; }}
.nt-h .rule {{ flex: 1; height: 1px; background: var(--border); }}
.nt-h .lede {{ font-size: .78rem; color: var(--dim); }}

/* —— KPI tiles —— */
.nt-kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: .6rem; }}
.nt-kpi {{ background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
  padding: .7rem .85rem; position: relative; overflow: hidden; }}
.nt-kpi::before {{ content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 3px;
  background: var(--tone, var(--dim)); }}
.nt-kpi .l {{ font-family: {MONO}; font-size: .62rem; letter-spacing: .14em; text-transform: uppercase;
  color: var(--dim); }}
.nt-kpi .v {{ font-family: {MONO}; font-size: 1.35rem; font-weight: 600; margin: .2rem 0 .05rem;
  font-variant-numeric: tabular-nums; color: var(--tone-text, var(--text)); }}
.nt-kpi .h {{ font-size: .74rem; color: var(--muted); }}

/* —— signal cards —— */
.nt-cards {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(330px, 1fr)); gap: .75rem; }}
.nt-card {{ background: linear-gradient(180deg, var(--surface-2), var(--surface)); border: 1px solid var(--border);
  border-radius: 12px; padding: .85rem .95rem .8rem; }}
.nt-card.buy {{ border-color: rgba(47,210,127,.35); }}
.nt-card.sell {{ border-color: rgba(255,93,108,.35); }}
.nt-card .top {{ display: flex; align-items: center; gap: .55rem; }}
.nt-card .sym {{ font-family: {MONO}; font-size: 1.3rem; font-weight: 700; letter-spacing: .03em; }}
.nt-card .px {{ font-family: {MONO}; color: var(--muted); font-size: .9rem; margin-left: auto;
  font-variant-numeric: tabular-nums; text-align: right; }}
.nt-card .px b {{ color: var(--text); font-weight: 600; }}
.nt-act {{ font-family: {MONO}; font-size: .64rem; font-weight: 700; letter-spacing: .12em;
  padding: .16rem .45rem; border-radius: 4px; color: var(--bg); background: var(--muted); }}
.nt-act.buy {{ background: var(--up); }} .nt-act.sell {{ background: var(--down); }}
.nt-act.hold {{ background: var(--surface-2); color: var(--muted); border: 1px solid var(--border); }}
.nt-grade {{ font-family: {MONO}; font-weight: 700; font-size: .72rem; width: 1.45rem; height: 1.45rem;
  display: inline-grid; place-items: center; border-radius: 6px; border: 1.5px solid currentColor; }}
.nt-ring {{ --p: 0; --c: var(--info); width: 2.6rem; height: 2.6rem; border-radius: 50%;
  background: conic-gradient(var(--c) calc(var(--p) * 1%), var(--border) 0);
  display: grid; place-items: center; flex: none; }}
.nt-ring span {{ width: 2.05rem; height: 2.05rem; border-radius: 50%; background: var(--surface-2);
  display: grid; place-items: center; font-family: {MONO}; font-size: .78rem; font-weight: 700; }}
.nt-stats {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: .3rem; margin: .65rem 0 .5rem; }}
.nt-stat .l {{ font-family: {MONO}; font-size: .58rem; letter-spacing: .12em; color: var(--dim);
  text-transform: uppercase; }}
.nt-stat .v {{ font-family: {MONO}; font-size: .86rem; font-weight: 600; font-variant-numeric: tabular-nums; }}
.up {{ color: var(--up); }} .down {{ color: var(--down); }} .muted {{ color: var(--muted); }}
.nt-chips {{ display: flex; flex-wrap: wrap; gap: .3rem; margin: .2rem 0 .55rem; }}
.nt-chip {{ font-family: {MONO}; font-size: .62rem; letter-spacing: .06em; padding: .14rem .45rem;
  border-radius: 4px; background: rgba(164,139,250,.12); color: var(--violet);
  border: 1px solid rgba(164,139,250,.3); }}
.nt-chip.risk {{ background: rgba(255,93,108,.1); color: var(--down); border-color: rgba(255,93,108,.3); }}
.nt-chip.main {{ background: rgba(245,184,61,.12); color: var(--accent); border-color: rgba(245,184,61,.35); }}

/* —— trade plan ladder —— */
.nt-plan {{ background: var(--bg); border: 1px solid var(--border); border-radius: 8px; padding: .55rem .65rem; }}
.nt-plan .row {{ display: flex; justify-content: space-between; font-family: {MONO}; font-size: .72rem;
  font-variant-numeric: tabular-nums; }}
.nt-plan .row span:first-child {{ color: var(--dim); letter-spacing: .08em; }}
.nt-ladder {{ position: relative; height: 8px; border-radius: 4px; margin: .5rem 0 .45rem;
  background: linear-gradient(90deg, rgba(255,93,108,.55) 0 var(--e), rgba(47,210,127,.5) var(--e) 100%); }}
.nt-ladder i {{ position: absolute; top: -3px; width: 2px; height: 14px; background: var(--text); }}
.nt-ladder i.t {{ background: var(--up); }}
.nt-plan .foot {{ font-size: .7rem; color: var(--muted); margin-top: .35rem; }}
.nt-order {{ font-family: {MONO}; font-size: .68rem; color: var(--accent); margin-top: .45rem;
  word-break: break-word; }}
details.nt-why {{ margin-top: .45rem; }}
details.nt-why summary {{ cursor: pointer; font-family: {MONO}; font-size: .66rem; color: var(--dim);
  letter-spacing: .1em; text-transform: uppercase; }}
details.nt-why ul {{ margin: .35rem 0 0 1rem; padding: 0; font-size: .76rem; color: var(--muted); }}

/* —— empty / notes —— */
.nt-empty {{ border: 1px dashed var(--border); border-radius: 10px; padding: 1.1rem; color: var(--muted);
  font-size: .86rem; text-align: center; }}
.nt-foot {{ margin-top: 2.5rem; padding-top: .8rem; border-top: 1px solid var(--border);
  font-family: {MONO}; font-size: .64rem; color: var(--dim); letter-spacing: .03em; }}

/* —— streamlit chrome —— */
section[data-testid="stSidebar"], [data-testid="stSidebar"] > div:first-child {{
  background: #0D1219 !important; border-right: 1px solid var(--border); }}
div[data-testid="stMetric"] {{ background: var(--surface); border: 1px solid var(--border);
  border-radius: 10px; padding: .6rem .8rem; }}
.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button {{
  border-radius: 8px !important; font-weight: 600 !important; }}
div[data-baseweb="tab-list"] {{ gap: .2rem; border-bottom: 1px solid var(--border); }}
button[data-baseweb="tab"] {{ font-family: {MONO} !important; font-size: .7rem !important;
  letter-spacing: .1em !important; text-transform: uppercase !important; }}
div[data-testid="stDataFrame"] {{ border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }}

@media (max-width: 760px) {{
  .nt-pills {{ margin-left: 0; }}
  .nt-stats {{ grid-template-columns: repeat(2, 1fr); }}
  .nt-cards {{ grid-template-columns: 1fr; }}
}}
@media (prefers-reduced-motion: reduce) {{ * {{ animation: none !important; transition: none !important; }} }}
</style>
"""


def plotly_layout(height: int = 420, **extra: Any) -> dict[str, Any]:
    """Base Plotly layout matching the CSS tokens."""
    layout: dict[str, Any] = {
        "template": "plotly_dark",
        "height": height,
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": SURFACE,
        "font": {"family": "JetBrains Mono, monospace", "color": MUTED, "size": 11},
        "margin": {"l": 8, "r": 8, "t": 34, "b": 8},
        "showlegend": False,
        "hovermode": "x unified",
        "hoverlabel": {"bgcolor": SURFACE_2, "bordercolor": BORDER, "font": {"color": TEXT}},
        "xaxis_rangeslider_visible": False,
    }
    layout.update(extra)
    return layout


def style_axes(fig: Any) -> Any:
    fig.update_xaxes(
        gridcolor=GRID,
        zeroline=False,
        linecolor=BORDER,
        showspikes=True,
        spikecolor=DIM,
        spikethickness=1,
        spikedash="dot",
    )
    fig.update_yaxes(gridcolor=GRID, zeroline=False, linecolor=BORDER, side="right")
    return fig
