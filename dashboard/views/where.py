import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import decisions
import lib

c = lib.colors()
crop = lib.crop()
weekly = lib.weekly()
gaps = lib.processed("price_gaps")

with st.container(horizontal=True, vertical_alignment="bottom", gap="medium"):
    state, home = lib.market_picker(crop, "where_home", "My mandi")
    transport = st.number_input("Cost to take a quintal to another mandi (₹)", 0, 1000, 100, 10,
                                key=f"transport_{crop}", width=340,
                                help="Freight, loading and the extra day. Roughly ₹60–150 a quintal for a "
                                     "truckload going 100–200 km.")
if home is None:
    st.stop()

b = decisions.best_markets(weekly, crop, state, home, transport, last_years=3)
if b.empty:
    lib.headline(f"{home} is the only reliable {crop.lower()} mandi in {state}")
    st.stop()
top = b.iloc[0]
if top.pct_weeks_move_pays >= 50:
    lib.headline(f"{top.market} beat {home} by more than the transport cost in {top.pct_weeks_move_pays:.0f}% "
                 "of weeks",
                 f"Over the last three years, taking {crop.lower()} from {home} to {top.market} would have earned "
                 f"about {lib.rs(top.avg_gain_when_it_pays_rs)} a quintal more in those weeks, after a "
                 f"{lib.rs(transport)} transport cost.")
else:
    lib.headline(f"{home} is hard to beat: no other {state} mandi pays enough extra to cover {lib.rs(transport)} "
                 "transport most weeks",
                 f"Best alternative: {top.market}, which paid more than the transport cost in "
                 f"{top.pct_weeks_move_pays:.0f}% of weeks.")

lib.section(f"Other reliable {crop.lower()} mandis in {state}", "Compared week by week over the last three years.")
st.dataframe(b, hide_index=True, width="stretch", height=lib.table_height(len(b)), column_config={
    "market": "Mandi", "weeks_compared": "Weeks compared",
    "median_premium_rs": st.column_config.NumberColumn(f"Typical ₹/quintal vs {home}", format="%+d"),
    "median_premium_pct": st.column_config.NumberColumn("In %", format="%+.0f%%"),
    "pct_weeks_move_pays": st.column_config.ProgressColumn("Weeks the trip pays", format="%.0f%%",
                                                          min_value=0, max_value=100),
    "avg_gain_when_it_pays_rs": st.column_config.NumberColumn("Gain in those weeks", format="₹%d"),
})

lib.section(f"{home} against the top alternatives", "Weekly modal price, last three years.")
w = weekly[(weekly.commodity == crop) & (weekly.state == state)]
w = w[w.week > w.week.max() - pd.DateOffset(years=3)]
fig = go.Figure()
palette = [c["orange"], c["aqua"], c["grey"]]
for colr, other in zip(palette, b.market.head(3)):
    o = w[w.market == other]
    fig.add_scatter(x=o.week, y=o.modal_price, mode="lines", name=other, line=dict(color=colr, width=1.6))
h = w[w.market == home]
fig.add_scatter(x=h.week, y=h.modal_price, mode="lines", name=f"{home} (my mandi)",
                line=dict(color=c["blue"], width=2.4))
fig.update_traces(hovertemplate="₹%{y:,.0f}")
fig.update_yaxes(title="₹ per quintal", tickformat=",")
lib.plot(fig, 380)

lib.section(f"How far apart are {state} mandis on the same day?",
            "Every pair of reliable mandis, on the days both reported. A big gap = one mandi at least 15% above "
            "the other; a run is how many reporting days in a row it lasted.")
g = gaps[(gaps.commodity == crop) & (gaps.state == state)]
st.dataframe(g.drop(columns=["commodity", "state"]), hide_index=True, width="stretch",
             height=lib.table_height(len(g), 10), column_config={
    "market_a": "Mandi A", "market_b": "Mandi B", "shared_days": "Days compared",
    "median_gap_b_vs_a_pct": st.column_config.NumberColumn("B vs A, typical", format="%+.0f%%"),
    "median_abs_gap_pct": st.column_config.NumberColumn("Typical gap", format="%.0f%%"),
    "pct_days_big_gap": st.column_config.ProgressColumn("Days with a big gap", format="%.0f%%", min_value=0, max_value=100),
    "pct_days_b_higher": st.column_config.NumberColumn("Days B higher", format="%.0f%%"),
    "avg_big_gap_run_days": st.column_config.NumberColumn("Avg run (days)", format="%.1f"),
    "longest_big_gap_run_days": "Longest run",
})
