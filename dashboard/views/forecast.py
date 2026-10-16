import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import lib

c = lib.colors()
crop = lib.crop()
color = lib.crop_color(crop)
fc = lib.processed("forecast", ("origin_week", "target_week"))
bt = lib.processed("forecast_backtest")
detail = lib.processed("forecast_backtest_detail", ("origin_week", "target_week"))
weekly = lib.weekly()

with st.container(horizontal=True, vertical_alignment="bottom"):
    state, market = lib.market_picker(crop, "fc_market")
f = fc[(fc.commodity == crop) & (fc.market == market) & (fc.state == state)].sort_values("horizon")
if f.empty:
    lib.headline(f"No current forecast for {market}")
    st.info("This mandi hasn't reported in the last four weeks of the data.")
    st.stop()
f4 = f.iloc[-1]
lib.headline(f"{market} {crop.lower()}: likely {lib.rs(f4.p10)} to {lib.rs(f4.p90)} a quintal by "
             f"{f4.target_week:%d %b %Y}",
             f"Four weeks on from the last price ({lib.rs(f4.last_price)} in the week of {f4.origin_week:%d %b %Y}). "
             "The range is built to contain the real price 8 times out of 10, and the backtest below checks that "
             "it actually does.")

hist = weekly[(weekly.commodity == crop) & (weekly.market == market) & (weekly.state == state)].sort_values("week").tail(30)
fig = go.Figure()
x = [f4.origin_week] + list(f.target_week)
fig.add_scatter(x=x, y=[f4.last_price] + list(f.p90), mode="lines", line=dict(width=0), showlegend=False,
                hoverinfo="skip")
fig.add_scatter(x=x, y=[f4.last_price] + list(f.p10), mode="lines", line=dict(width=0), fill="tonexty",
                fillcolor=c["band"], name="80% range", hoverinfo="skip")
fig.add_scatter(x=hist.week, y=hist.modal_price, mode="lines+markers", line=dict(color=color, width=2),
                marker=dict(size=6), name="Actual", hovertemplate="Actual ₹%{y:,.0f}")
fig.add_scatter(x=x, y=[f4.last_price] + list(f.p50), mode="lines+markers", name="Forecast (middle)",
                line=dict(color=color, width=2, dash="dot"), marker=dict(size=8, symbol="circle-open"),
                customdata=[[f4.last_price, f4.last_price]] + f[["p10", "p90"]].values.tolist(),
                hovertemplate="Forecast ₹%{y:,.0f} (₹%{customdata[0]:,.0f}–₹%{customdata[1]:,.0f})")
fig.update_yaxes(title="₹ per quintal", tickformat=",")
lib.plot(fig, 380)

# ---- backtest ---------------------------------------------------------------------------
lib.section("Does it beat simple rules?",
            "Backtest over the last two years: each week, forecast using only data available at the time, then "
            "compare with what happened. Error = average % miss on the price (lower is better).")
b = bt[bt.commodity == crop]
names = {"naive": "Price stays the same", "seasonal_naive": "Usual seasonal change", "model": "MandiPulse model"}
wide = b.pivot_table(index="horizon", columns="method", values="mape_pct").rename(columns=names)
m = b[b.method == "model"].set_index("horizon")
wide["Beats 'stays the same' by"] = m.improvement_vs_naive_pct
wide["Range held the price"] = m.coverage_80_pct
wide.index = [f"{h} week{'s' if h > 1 else ''} ahead" for h in wide.index]
fmt = {k: st.column_config.NumberColumn(k, format="%.1f%%") for k in names.values()}
fmt["Beats 'stays the same' by"] = st.column_config.NumberColumn(format="%+.0f%%")
fmt["Range held the price"] = st.column_config.ProgressColumn(format="%.0f%%", min_value=0, max_value=100,
                                                              help="Share of backtest weeks where the actual price "
                                                                   "fell inside the 80% range. Should be near 80%.")
st.dataframe(wide, width="stretch", column_config=fmt)
h4 = m.loc[4] if 4 in m.index else None
if h4 is not None:
    better = h4.improvement_vs_naive_pct
    lib.callouts([{"tone": "ok" if better > 5 else "info",
                   "title": (f"Four weeks out, the model misses by {h4.mape_pct:.0f}% on average, "
                             f"{abs(better):.0f}% {'less' if better > 0 else 'more'} than assuming no change"),
                   "body": f"Its 80% range contained the real price {h4.coverage_80_pct:.0f}% of the time, with an "
                           f"average width of ±{h4.avg_range_width_pct / 2:.0f}%. Mandi prices are hard to forecast: "
                           "the range is the useful part, not the middle line."}])

d = detail[(detail.commodity == crop) & (detail.market == market) & (detail.state == state) & (detail.horizon == 4)]
if not d.empty:
    lib.section(f"Backtest in {market}: forecasts made four weeks earlier", None)
    fig = go.Figure()
    fig.add_scatter(x=d.target_week, y=d.high, mode="lines", line=dict(width=0), showlegend=False, hoverinfo="skip")
    fig.add_scatter(x=d.target_week, y=d.low, mode="lines", line=dict(width=0), fill="tonexty",
                    fillcolor=c["band"], name="80% range", hoverinfo="skip")
    fig.add_scatter(x=d.target_week, y=d.model, mode="lines", line=dict(color=color, width=1.6, dash="dot"),
                    name="Forecast", hovertemplate="Forecast ₹%{y:,.0f}")
    fig.add_scatter(x=d.target_week, y=d.actual, mode="lines", line=dict(color=c["ink"], width=1.8),
                    name="Actual", hovertemplate="Actual ₹%{y:,.0f}")
    fig.update_yaxes(title="₹ per quintal", tickformat=",")
    lib.plot(fig, 340)
