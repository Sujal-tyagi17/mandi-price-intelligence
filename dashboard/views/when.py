import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import decisions
import lib

c = lib.colors()
crop = lib.crop()
season = lib.processed("seasonality")
weekly = lib.weekly()
color = lib.crop_color(crop)

with st.container(horizontal=True, vertical_alignment="bottom"):
    state, market = lib.market_picker(crop, "when_market")
if market is None:
    st.info("No reliable mandi for this crop yet.")
    st.stop()

s = season[(season.commodity == crop) & (season.market == market) & (season.state == state)].sort_values("month")
alls = season[(season.commodity == crop) & (season.market == "All markets")].sort_values("month")
if s.empty:
    s = alls
lo, hi = s.loc[s.season_index.idxmin()], s.loc[s.season_index.idxmax()]
lib.headline(f"In {market}, {crop.lower()} fetches {hi.season_index / lo.season_index - 1:.0%} more in "
             f"{lib.MONTHS[int(hi.month) - 1]} than in {lib.MONTHS[int(lo.month) - 1]}",
             "Seasonal index: each month's price compared with that year's average month (100). Every year is "
             "compared with itself, so one shock year or inflation doesn't distort the pattern.")

lib.section("The price calendar", f"Median over {int(s.market_years.max())} years in {market}; whiskers show the "
            "middle half of years. Grey line: all reliable mandis.")
fig = go.Figure()
fig.add_bar(x=lib.MONTHS, y=s.season_index - 100, base=100, marker=dict(color=color, cornerradius=4),
            error_y=dict(type="data", symmetric=False, array=s.index_p75 - s.season_index,
                         arrayminus=s.season_index - s.index_p25, color=c["ink2"], thickness=1.2, width=3),
            customdata=s.season_index, name=market,
            hovertemplate=market + ": %{customdata:.0f}<extra></extra>")
if s is not alls:
    fig.add_scatter(x=lib.MONTHS, y=alls.season_index, mode="lines+markers", name="All mandis",
                    line=dict(color=c["grey"], width=2), marker=dict(size=8),
                    hovertemplate="All mandis: %{y:.0f}<extra></extra>")
fig.add_hline(y=100, line=dict(color=c["ink2"], width=1, dash="dot"))
fig.update_yaxes(title="Seasonal index (100 = average month)")
fig.update_layout(bargap=0.35)
lib.plot(fig, 360)

# ---- hold or sell ----------------------------------------------------------------------
st_default = decisions.STORAGE[crop]
lib.section("Hold or sell?", "Every past week is treated as a possible selling date: what if the crop had been "
            "stored instead and sold later? Storage loses weight and costs money, so a higher later price is not "
            "automatically a gain. " + st_default.note + ".")
with st.container(horizontal=True, vertical_alignment="bottom", gap="medium"):
    start_month = st.selectbox("Harvest / selling month", lib.MONTHS, index=int(lo.month) - 1, key=f"hm_{crop}", width=220)
    loss = st.number_input("Weight lost per month (%)", 0.0, 60.0, st_default.loss_pct_per_month, 0.5, key=f"loss_{crop}", width=220)
    cost = st.number_input("Storage cost (₹/quintal/month)", 0, 500, int(st_default.cost_per_quintal_month), 10,
                           key=f"cost_{crop}", width=240)

m = weekly[(weekly.commodity == crop) & (weekly.market == market) & (weekly.state == state)]
t = decisions.hold_or_sell(m, loss, cost, st_default.hold_weeks)
t = t[t.start_month == lib.MONTHS.index(start_month) + 1]
if t.empty:
    st.info("Not enough history for this month.")
    st.stop()
best = t.loc[t.median_gain_pct.idxmax()]
if best.median_gain_pct > 0 and best.pct_cases_hold_paid >= 60:
    lib.callouts([{"tone": "ok", "title": f"Holding about {int(best.hold_weeks)} weeks usually paid",
                   "body": f"Selling in {start_month}, storing {int(best.hold_weeks)} weeks paid off in "
                           f"{best.pct_cases_hold_paid:.0f}% of past cases, with a typical gain of "
                           f"{best.median_gain_pct:+.0f}% ({lib.rs(best.median_gain_rs_per_quintal)} per quintal) "
                           "after losses and storage cost."}])
else:
    lib.callouts([{"tone": "alert", "title": "Selling straight away usually did as well or better",
                   "body": f"No holding period beat selling in {start_month} in most years once weight loss and "
                           f"storage cost are counted (best case: {int(best.hold_weeks)} weeks paid in "
                           f"{best.pct_cases_hold_paid:.0f}% of cases)."}])

fig = go.Figure()
x = [f"{int(h)} wk" for h in t.hold_weeks]
fig.add_bar(x=x, y=t.median_gain_pct, marker=dict(color=[color if v > 0 else c["grey"] for v in t.median_gain_pct],
                                                    cornerradius=4),
            error_y=dict(type="data", symmetric=False, array=t.p90_gain_pct - t.median_gain_pct,
                         arrayminus=t.median_gain_pct - t.p10_gain_pct, color=c["ink2"], thickness=1.2, width=3),
            customdata=t[["pct_cases_hold_paid", "p10_gain_pct", "p90_gain_pct"]].to_numpy(),
            hovertemplate="Hold %{x}: median %{y:+.0f}%<br>paid in %{customdata[0]:.0f}% of cases"
                          "<br>bad year %{customdata[1]:+.0f}%, good year %{customdata[2]:+.0f}%<extra></extra>",
            name="Median gain")
fig.add_hline(y=0, line=dict(color=c["ink2"], width=1))
fig.update_yaxes(title="Gain vs selling now (%)", ticksuffix="%")
fig.update_layout(showlegend=False, bargap=0.45, hovermode="closest")
lib.plot(fig, 320)
st.caption("Bars: typical outcome. Whiskers: a bad year (10th percentile) to a good year (90th percentile).")
st.dataframe(t[["hold_weeks", "cases", "pct_cases_hold_paid", "median_gain_pct", "p10_gain_pct", "p90_gain_pct",
                "median_gain_rs_per_quintal"]], hide_index=True, width="stretch", column_config={
    "hold_weeks": "Hold (weeks)", "cases": "Past cases",
    "pct_cases_hold_paid": st.column_config.ProgressColumn("Holding paid", format="%.0f%%", min_value=0, max_value=100),
    "median_gain_pct": st.column_config.NumberColumn("Typical gain", format="%+.0f%%"),
    "p10_gain_pct": st.column_config.NumberColumn("Bad year", format="%+.0f%%"),
    "p90_gain_pct": st.column_config.NumberColumn("Good year", format="%+.0f%%"),
    "median_gain_rs_per_quintal": st.column_config.NumberColumn("Typical gain, ₹/quintal", format="%+d"),
})
