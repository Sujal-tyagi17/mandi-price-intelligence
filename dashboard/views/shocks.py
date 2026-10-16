import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import lib

c = lib.colors()
crop = lib.crop()
color = lib.crop_color(crop)
vol = lib.processed("volatility", ("month",))
shocks = lib.processed("price_shocks", ("start_week", "extreme_week", "end_week"))
supply = lib.processed("supply_price")

v = vol[vol.commodity == crop].sort_values("month")
by_crop = vol.groupby("commodity").median_cv_pct.median().sort_values(ascending=False)
s = shocks[shocks.commodity == crop]
lib.headline(f"{crop} had {len(s)} price shock{'s' if len(s) != 1 else ''} since {v.month.min():%Y}",
             f"A typical {crop.lower()} mandi's price moves {v.median_cv_pct.median():.0f}% within a month "
             f"(coefficient of variation). Most volatile crop: {by_crop.index[0].lower()}.")

sp = supply[supply.commodity == crop] if not supply.empty else supply
items = [{"label": "Typical month-to-month swing", "value": f"{v.median_cv_pct.median():.0f}%",
          "note": "median coefficient of variation"},
         {"label": "Worst month", "value": f"{v.median_cv_pct.max():.0f}%",
          "note": f"{v.loc[v.median_cv_pct.idxmax(), 'month']:%b %Y}"},
         {"label": "Shocks", "value": f"{(s.direction == 'Spike').sum()} up · {(s.direction == 'Crash').sum()} down"}]
if not sp.empty:
    r = sp.iloc[0]
    items.append({"label": "10% more arrivals at a mandi", "value": f"{r.price_change_for_10pct_more_arrivals:+.1f}%",
                  "note": f"price, same mandi and year (95% CI {100 * (1.1 ** r.ci_low - 1):+.1f}% to "
                          f"{100 * (1.1 ** r.ci_high - 1):+.1f}%)"})
lib.kpi_band(items)

lib.section("Volatility month by month", "Median across reliable mandis of the within-month variation in daily prices.")
fig = go.Figure()
for o in lib.COMMODITIES:
    g = vol[vol.commodity == o].sort_values("month")
    fig.add_scatter(x=g.month, y=g.median_cv_pct, mode="lines", name=o,
                    line=dict(color=lib.crop_color(o), width=2.2 if o == crop else 1.1),
                    opacity=1 if o == crop else 0.45, hovertemplate=f"{o}: %{{y:.0f}}%<extra></extra>")
fig.update_yaxes(title="Within-month variation (%)", ticksuffix="%", rangemode="tozero")
lib.plot(fig, 340)

lib.section("Shock episodes", "The national price index rose 40% or more, or fell by a similar amount, within four weeks.")
st.dataframe(s.drop(columns="commodity").sort_values("start_week", ascending=False), hide_index=True, width="stretch",
             column_config={"direction": "Type",
                            "start_week": st.column_config.DateColumn("From", format="MMM YYYY"),
                            "extreme_week": st.column_config.DateColumn("Peak / trough", format="D MMM YYYY"),
                            "end_week": st.column_config.DateColumn("Until", format="MMM YYYY"),
                            "index_before": st.column_config.NumberColumn("Index before", format="%.0f"),
                            "index_extreme": st.column_config.NumberColumn("Index at extreme", format="%.0f"),
                            "change_pct": st.column_config.NumberColumn("Change", format="%+.0f%%")})

lib.section("Do bigger arrivals mean lower prices?",
            "Each mandi is compared only with itself in the same year, after removing the normal seasonal pattern. "
            "It's an association, not a demand curve: high prices also pull in more produce.")
if supply.empty:
    st.info("The data has no arrival quantities, so this can't be measured.")
else:
    st.dataframe(supply, hide_index=True, width="stretch", column_config={
        "commodity": "Crop", "elasticity": st.column_config.NumberColumn("Elasticity", format="%.2f"),
        "ci_low": st.column_config.NumberColumn("95% CI low", format="%.2f"),
        "ci_high": st.column_config.NumberColumn("95% CI high", format="%.2f"),
        "price_change_for_10pct_more_arrivals": st.column_config.NumberColumn("Price if arrivals +10%", format="%+.1f%%"),
        "weeks": "Mandi-weeks", "markets": "Mandis", "r2_within": st.column_config.NumberColumn("R² (within)", format="%.2f")})
