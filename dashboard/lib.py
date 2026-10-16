"""Shared data access, styling and small UI components for the MandiPulse dashboard."""

from __future__ import annotations

import base64
import html
import json
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from config import ANCHOR_MARKETS, COMMODITIES, PROCESSED, REPORTS  # noqa: E402

# Validated colour-blind-safe steps (same system as DarkStore Pulse); light / dark
LIGHT = dict(blue="#2A78D6", orange="#EB6834", aqua="#1BAF7A", grey="#B9BFCA", faint="#DDE2EA",
             band="rgba(42,120,214,0.16)", ink="#18202F", ink2="#4A5468")
DARK = dict(blue="#3987E5", orange="#D95926", aqua="#199E70", grey="#4A5366", faint="#273042",
            band="rgba(57,135,229,0.24)", ink="#E7EBF2", ink2="#B4BCCB")
CROP_COLOR = {"Onion": "blue", "Tomato": "orange", "Potato": "aqua"}   # identity follows the crop
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def colors() -> dict:
    try:
        dark = st.context.theme.type == "dark"
    except Exception:  # noqa: BLE001
        dark = False
    return DARK if dark else LIGHT


def crop_color(crop: str) -> str:
    return colors()[CROP_COLOR.get(crop, "blue")]


# ---------------------------------------------------------------------------
# Data (everything comes from the CSVs written by run_all.py)
# ---------------------------------------------------------------------------
def available() -> bool:
    return (PROCESSED / "weekly_prices.csv").exists() and (PROCESSED / "forecast.csv").exists()


@st.cache_data(show_spinner=False)
def processed(name: str, dates: tuple[str, ...] = ()) -> pd.DataFrame:
    path = PROCESSED / f"{name}.csv"
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(path, parse_dates=list(dates))
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


@st.cache_data(show_spinner=False)
def build_info() -> dict:
    f = PROCESSED / "build_info.json"
    return json.loads(f.read_text()) if f.exists() else {}


@st.cache_data(show_spinner=False)
def quality_report() -> str:
    f = REPORTS / "data_quality.md"
    return f.read_text(encoding="utf-8") if f.exists() else ""


def weekly() -> pd.DataFrame:
    return processed("weekly_prices", ("week",))


def markets(crop: str) -> pd.DataFrame:
    """Reliable markets for a crop, biggest (most weeks reported) first, anchor markets on top."""
    w = weekly()
    m = (w[w.commodity == crop].groupby(["state", "market"]).agg(weeks=("week", "count"), last=("week", "max"))
         .reset_index())
    order = ANCHOR_MARKETS.get(crop, [])
    m["rank"] = [order.index(k) if k in order else len(order) for k in m.market]
    return m.sort_values(["rank", "weeks"], ascending=[True, False]).drop(columns="rank").reset_index(drop=True)


def market_label(state: str, market: str) -> str:
    return f"{market}, {state}"


# ---------------------------------------------------------------------------
# Shared controls
# ---------------------------------------------------------------------------
def crop() -> str:
    return st.session_state.get("f_crop") or COMMODITIES[0]


def market_picker(crop_name: str, key: str, label: str = "Mandi", states: list[str] | None = None):
    m = markets(crop_name)
    if states:
        m = m[m.state.isin(states)]
    if m.empty:
        return None, None
    opts = [market_label(s, k) for s, k in zip(m.state, m.market)]
    choice = st.selectbox(label, opts, key=f"{key}_{crop_name}", width=340)
    row = m.iloc[opts.index(choice)]
    return row.state, row.market


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------
def rs(v: float) -> str:
    return "–" if pd.isna(v) else f"₹{v:,.0f}"


def pct(v: float, signed: bool = True) -> str:
    return "–" if pd.isna(v) else (f"{v:+.0f}%" if signed else f"{v:.0f}%")


def crore(v: float) -> str:
    return f"₹{v:,.0f} crore" if abs(v) >= 10 else f"₹{v:,.1f} crore"


# ---------------------------------------------------------------------------
# Components (custom HTML inherits the text colour, so it works in light and dark)
# ---------------------------------------------------------------------------
def headline(text: str, deck: str | None = None):
    deck_html = f'<p class="mp-deck">{html.escape(deck)}</p>' if deck else ""
    st.html(f'<div class="mp-head"><h1 class="mp-headline">{html.escape(text)}</h1>{deck_html}</div>')


def section(title: str, caption: str | None = None):
    cap = f'<p class="mp-section-cap">{html.escape(caption)}</p>' if caption else ""
    st.html(f'<div class="mp-section"><h2>{html.escape(title)}</h2>{cap}</div>')


def _spark(values: list[float], color: str, w: int = 120, h: int = 28) -> str:
    vals = [v for v in values if v is not None and not pd.isna(v)]
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1
    pts = " ".join(f"{i * w / (len(vals) - 1):.1f},{h - 3 - (v - lo) / rng * (h - 6):.1f}" for i, v in enumerate(vals))
    last_x, last_y = pts.split(" ")[-1].split(",")
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="-3 -1 {w + 6} {h + 2}" width="{w + 6}" height="{h + 2}">'
           f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="1.8" stroke-linejoin="round"/>'
           f'<circle cx="{last_x}" cy="{last_y}" r="2.6" fill="{color}"/></svg>')
    uri = "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()
    return f'<img class="mp-spark" src="{uri}" alt="">'


def kpi_band(items: list[dict]):
    """items: label, value, delta (str|None), good (bool|None), note (str|None), spark (list|None), color"""
    cells = []
    for it in items:
        delta = ""
        if it.get("delta"):
            g = it.get("good")
            tone = "mp-flat" if g is None else ("mp-good" if bool(g) else "mp-bad")
            delta = f'<span class="mp-delta {tone}">{html.escape(it["delta"])}</span>'
        note = f'<span class="mp-note">{html.escape(it["note"])}</span>' if it.get("note") else ""
        spark = _spark(it["spark"], it.get("color") or colors()["blue"]) if it.get("spark") else ""
        cells.append(
            f'<div class="mp-kpi"><div class="mp-kpi-label">{html.escape(it["label"])}</div>'
            f'<div class="mp-kpi-value">{html.escape(it["value"])}</div>'
            f'<div class="mp-kpi-meta">{delta}{note}</div>{spark}</div>')
    st.html(f'<div class="mp-band">{"".join(cells)}</div>')


def callouts(rows: list[dict]):
    """rows: tone (alert | info | ok), title, body"""
    out = [f'<div class="mp-callout mp-{r["tone"]}"><div class="mp-callout-title">{html.escape(r["title"])}</div>'
           f'<div class="mp-callout-body">{html.escape(r["body"])}</div></div>' for r in rows]
    st.html(f'<div class="mp-callouts">{"".join(out)}</div>')


def table_height(n: int, max_rows: int = 16) -> int:
    return int(35 * min(n, max_rows)) + 3


def plot(fig: go.Figure, height: int = 360, key: str | None = None):
    fig.update_layout(
        height=height, margin=dict(l=4, r=4, t=8, b=4),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, title=None),
        hoverlabel=dict(font_size=13), hovermode="x unified",
        font=dict(family="Archivo, sans-serif"),
    )
    fig.update_xaxes(showgrid=False, title_font=dict(size=12))
    fig.update_yaxes(title_font=dict(size=12), zeroline=False)
    st.plotly_chart(fig, width="stretch", theme="streamlit", key=key,
                    config={"displaylogo": False, "modeBarButtonsToRemove": ["lasso2d", "select2d"]})


def sample_banner():
    if build_info().get("sample_data"):
        st.warning("**Demo mode: these numbers come from synthetic sample data, not real mandi prices.** "
                   "They exist only to show how the dashboard works. Run the CEDA download and "
                   "`python run_all.py` to see real results.", icon=":material/science:")


CSS = """
<style>
.block-container {max-width: 1280px;}
.mp-head {margin: 0.4rem 0 1.1rem;}
.mp-headline {font-family: Archivo, sans-serif; font-variation-settings: "wdth" 116; font-weight: 760;
  font-size: clamp(1.7rem, 3.1vw, 2.6rem); line-height: 1.08; letter-spacing: -0.012em; margin: 0;
  max-width: 32ch; padding: 0; font-variant-numeric: tabular-nums;}
.mp-deck {margin: 0.55rem 0 0; max-width: 74ch; font-size: 1.02rem; line-height: 1.5; opacity: 0.78;}
.mp-band {display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  border-top: 2px solid currentColor; border-bottom: 1px solid color-mix(in srgb, currentColor 18%, transparent);
  margin: 0.2rem 0 1.4rem;}
.mp-kpi {padding: 0.75rem 1rem 0.7rem; border-right: 1px solid color-mix(in srgb, currentColor 14%, transparent);
  display: flex; flex-direction: column; gap: 0.15rem; min-width: 0;}
.mp-kpi:last-child {border-right: none;}
.mp-kpi:first-child {padding-left: 0;}
.mp-kpi-label {font-size: 0.84rem; opacity: 0.72;}
.mp-kpi-value {font-variation-settings: "wdth" 108; font-weight: 680; font-size: 1.7rem; line-height: 1.15;
  font-variant-numeric: tabular-nums; white-space: nowrap;}
.mp-kpi-meta {font-size: 0.8rem; display: flex; gap: 0.45rem; flex-wrap: wrap; min-height: 1.1rem;}
.mp-note {opacity: 0.62;}
.mp-delta {font-weight: 600; font-variant-numeric: tabular-nums;}
.mp-good {color: #1F8A5B;} .mp-bad {color: #D2551E;} .mp-flat {opacity: 0.7;}
@media (prefers-color-scheme: dark) {.mp-good {color: #3FBF85;} .mp-bad {color: #F08A5D;}}
.mp-spark {width: 100%; height: 28px; margin-top: 0.4rem; display: block;}
.mp-section {margin: 1.6rem 0 0.35rem;}
.mp-section h2 {font-variation-settings: "wdth" 110; font-weight: 700; font-size: 1.28rem; margin: 0; padding: 0;}
.mp-section-cap {margin: 0.25rem 0 0; opacity: 0.7; font-size: 0.92rem; max-width: 80ch;}
.mp-callouts {display: grid; gap: 0.6rem; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); margin: 0.4rem 0 0.6rem;}
.mp-callout {padding: 0.7rem 0.9rem 0.75rem; border-left: 4px solid; border-radius: 2px;
  background: color-mix(in srgb, currentColor 4%, transparent);}
.mp-callout-title {font-weight: 650; margin-bottom: 0.2rem; line-height: 1.3;}
.mp-callout-body {font-size: 0.9rem; line-height: 1.45; opacity: 0.82;}
.mp-alert {border-color: #EB6834;} .mp-info {border-color: #2A78D6;} .mp-ok {border-color: #1BAF7A;}
@media (max-width: 640px) {
  .mp-kpi {border-right: none; padding-left: 0; border-bottom: 1px solid color-mix(in srgb, currentColor 10%, transparent);}
}
</style>
"""
