import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import lib

c = lib.colors()
crop = lib.crop()
idx = lib.processed("price_index_weekly", ("week",))
weekly = lib.weekly()
shocks = lib.processed("price_shocks", ("start_week", "extreme_week", "end_week"))

g = idx[idx.commodity == crop].sort_values("week")
last = g.iloc[-1]
yoy = last.yoy_pct
if pd.isna(yoy):
    head = f"{crop} is selling at {lib.rs(last.median_price)} a quintal in a typical mandi"
else:
    head = (f"{crop} prices are {abs(yoy):.0f}% {'higher' if yoy > 0 else 'lower'} than a year ago"
            if abs(yoy) >= 3 else f"{crop} prices are about where they were a year ago")
lib.headline(head, f"Typical (median) modal price across {int(last.markets)} reliable mandis in the week of "
                   f"{last.week:%d %b %Y}: {lib.rs(last.median_price)} per quintal, about ₹{last.median_price / 100:,.0f} a kg "
                   "at the wholesale gate.")

items = []
for crop_name in lib.COMMODITIES:
    s = idx[idx.commodity == crop_name].sort_values("week")
    if s.empty:
        continue
    r = s.iloc[-1]
    four = s.iloc[-5].median_price if len(s) > 4 else None
    items.append({"label": f"{crop_name}, ₹/quintal", "value": lib.rs(r.median_price),
                  "delta": None if pd.isna(r.yoy_pct) else f"{r.yoy_pct:+.0f}% vs a year ago", "good": None,
                  "note": None if four is None else f"{100 * (r.median_price / four - 1):+.0f}% in 4 weeks",
                  "spark": s.median_price.tail(26).tolist(), "color": lib.crop_color(crop_name)})
lib.kpi_band(items)

# ---- long-run chart ------------------------------------------------------------------
lib.section(f"{crop}: typical mandi price, week by week",
            "Median across reliable mandis. Shaded: price shocks, when the national index rose 40% or more "
            "(or fell by a similar amount) within four weeks.")
fig = go.Figure()
for r in shocks[shocks.commodity == crop].itertuples():
    fig.add_vrect(x0=r.start_week, x1=r.end_week, fillcolor=c["orange"] if r.direction == "Spike" else c["grey"],
                  opacity=0.13, line_width=0, layer="below")
fig.add_scatter(x=g.week, y=g.median_price, mode="lines", line=dict(color=lib.crop_color(crop), width=2),
                name=crop, hovertemplate="₹%{y:,.0f}/quintal<extra></extra>")
fig.update_yaxes(title="₹ per quintal", rangemode="tozero", tickformat=",")
fig.update_layout(showlegend=False)
lib.plot(fig, 380)

# ---- markets table -------------------------------------------------------------------
lib.section("Mandi by mandi", "Latest weekly modal price in each reliable mandi, with the last six months.")
w = weekly[weekly.commodity == crop].sort_values("week")
rows = []
for (state, market), m in w.groupby(["state", "market"]):
    m = m.set_index("week").modal_price
    latest_week = m.index.max()
    if latest_week < w.week.max() - pd.Timedelta(weeks=8):
        continue                                    # stopped reporting
    prev4 = m.loc[:latest_week - pd.Timedelta(weeks=4)]
    ago = m.loc[:latest_week - pd.Timedelta(weeks=52)]
    rows.append({"market": market, "state": state, "week": latest_week.date(), "price": m.iloc[-1],
                 "chg4": 100 * (m.iloc[-1] / prev4.iloc[-1] - 1) if len(prev4) else None,
                 "yoy": 100 * (m.iloc[-1] / ago.iloc[-1] - 1) if len(ago) and ago.index[-1] > latest_week - pd.Timedelta(weeks=56) else None,
                 "trend": m.tail(26).tolist()})
tab = pd.DataFrame(rows).sort_values("price", ascending=False)
st.dataframe(tab, hide_index=True, width="stretch", height=lib.table_height(len(tab)), column_config={
    "market": "Mandi", "state": "State", "week": st.column_config.DateColumn("Week of", format="D MMM YYYY"),
    "price": st.column_config.NumberColumn("₹/quintal", format="₹%d"),
    "chg4": st.column_config.NumberColumn("4-week change", format="%+.0f%%"),
    "yoy": st.column_config.NumberColumn("vs a year ago", format="%+.0f%%"),
    "trend": st.column_config.LineChartColumn("Last 26 weeks", width="medium"),
})
