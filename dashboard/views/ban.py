import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import decisions
import lib

c = lib.colors()
path = lib.processed("ban_event_daily", ("date",))
summ = lib.processed("ban_event_summary")
if path.empty or summ.empty:
    lib.headline("The onion export ban")
    st.info("Not enough onion price history around December 2023 to study the ban.")
    st.stop()

anchor = "Lasalgaon" if "Lasalgaon" in set(summ.market) else summ.sort_values("arrivals_during_ban_tonnes"
                                                                                if "arrivals_during_ban_tonnes" in summ
                                                                                else "pre_ban_price").market.iloc[-1]
a = summ.set_index("market").loc[anchor]
lib.headline(f"During the export ban, {anchor} onion sold {abs(a.effect_pct):.0f}% "
             f"{'below' if a.effect_pct < 0 else 'above'} what the season normally brings",
             f"India banned onion exports from {decisions.BAN_START.day} {decisions.BAN_START:%B %Y} to "
             f"{decisions.BAN_END.day} {decisions.BAN_END:%B %Y} to cool "
             "retail prices. Prices always fall from December as the late-kharif crop arrives, so the question "
             "is how much further they fell than in a normal year.")

items = [{"label": "Price before the ban", "value": lib.rs(a.pre_ban_price), "note": "₹/quintal, 2 weeks before"},
         {"label": "Ban period vs a normal year", "value": lib.pct(a.effect_pct), "good": a.effect_pct >= 0,
          "delta": f"{lib.rs(abs(a.effect_rs_per_quintal))}/quintal {'less' if a.effect_rs_per_quintal < 0 else 'more'}"}]
if "revenue_gap_crore" in summ and pd.notna(a.get("revenue_gap_crore")):
    items.append({"label": f"Farmers' revenue gap at {anchor}", "value": lib.crore(a.revenue_gap_crore),
                  "note": f"on {a.arrivals_during_ban_tonnes:,.0f} tonnes sold during the ban"})
    total = summ.revenue_gap_crore.sum()
    items.append({"label": f"Across {len(summ)} reliable onion mandis", "value": lib.crore(total),
                  "note": "estimated, same method"})
lib.kpi_band(items)

market = st.selectbox("Mandi", sorted(summ.market), index=sorted(summ.market).index(anchor), width=340)
p = path[path.market == market]
lib.section(f"{market}: price after the ban vs the usual path",
            "Price indexed to its average over the two weeks before the ban (100). Band: the range of the same "
            f"weeks in {', '.join(str(y) + '–' + str(y + 1)[2:] for y in decisions.BAN_COMPARISON_YEARS)}; "
            "line inside it: their median. 2019–20 is left out because it had an export ban of its own.")
fig = go.Figure()
fig.add_vrect(x0=decisions.BAN_START, x1=decisions.BAN_END, fillcolor=c["orange"], opacity=0.08, line_width=0,
              layer="below", annotation_text="Export ban", annotation_position="top left")
fig.add_scatter(x=p.date, y=p.expected_high, mode="lines", line=dict(width=0), showlegend=False, hoverinfo="skip")
fig.add_scatter(x=p.date, y=p.expected_low, mode="lines", line=dict(width=0), fill="tonexty",
                fillcolor=c["band"], name="Normal years (range)", hoverinfo="skip")
fig.add_scatter(x=p.date, y=p.expected_index, mode="lines", line=dict(color=c["grey"], width=2, dash="dot"),
                name="Normal year", hovertemplate="Normal: %{y:.0f}")
fig.add_scatter(x=p.date, y=p.actual_index, mode="lines", line=dict(color=c["blue"], width=2.4),
                name="2023–24 (actual)", hovertemplate="Actual: %{y:.0f}")
fig.add_hline(y=100, line=dict(color=c["ink2"], width=1, dash="dot"))
fig.update_yaxes(title="Price index (100 = two weeks before the ban)")
lib.plot(fig, 400)

lib.section("Every reliable onion mandi", "Average index during the ban, actual vs normal year.")
cols = {"market": "Mandi", "pre_ban_price": st.column_config.NumberColumn("Price before (₹/q)", format="₹%d"),
        "avg_actual_index": st.column_config.NumberColumn("Actual index", format="%.0f"),
        "avg_expected_index": st.column_config.NumberColumn("Normal-year index", format="%.0f"),
        "effect_pct": st.column_config.NumberColumn("Ban effect", format="%+.0f%%"),
        "effect_rs_per_quintal": st.column_config.NumberColumn("Effect, ₹/quintal", format="%+d"),
        "comparison_years": "Years compared",
        "arrivals_during_ban_tonnes": st.column_config.NumberColumn("Tonnes sold", format="%d"),
        "revenue_gap_crore": st.column_config.NumberColumn("Revenue gap", format="₹%.1f cr")}
st.dataframe(summ.sort_values("effect_pct"), hide_index=True, width="stretch",
             height=lib.table_height(len(summ)), column_config=cols)
st.caption("This compares the ban period with normal years; it can't separate the ban from anything else "
           "unusual that season (for example, a smaller kharif crop pushed prices up in the months before).")
