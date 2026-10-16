import streamlit as st

import lib

info = lib.build_info()
lib.headline("About the data", "Real daily wholesale prices reported by APMC mandis to Agmarknet, the Government of "
             "India's agricultural marketing network, downloaded through the CEDA Agri Market API (Ashoka University).")
lib.kpi_band([
    {"label": "Period", "value": f"{info.get('first_date', '')[:4]}–{info.get('last_date', '')[:4]}",
     "note": f"{info.get('first_date', '')} to {info.get('last_date', '')}"},
    {"label": "Source files", "value": f"{info.get('source_files', 0):,}"},
    {"label": "Reliable mandis", "value": f"{lib.weekly().groupby(['commodity', 'market']).ngroups:,}",
     "note": "crop-mandi series with ≥1 year and ≥60% of days"},
])
st.markdown("""
**Method in brief**

- **Cleaning** (SQL, `sql/00_staging.sql`): market names standardised, out-of-scope crops removed, ₹/kg slips and
  swapped min/max fixed, duplicates merged, one-day spikes flagged with a robust median/MAD test and excluded.
- **Seasons**: each month compared with the same year's average month, so shock years don't distort the shape.
- **Hold or sell**: every past week treated as a selling date and compared with storing for 1–24 weeks, net of
  weight loss and storage cost (both adjustable).
- **Where to sell**: week-by-week price difference to every other reliable mandi in the state, minus transport.
- **Export ban**: prices indexed to the two weeks before 8 Dec 2023, compared with the same weeks in normal years.
- **Forecast**: ridge regression on recent changes, distance from 12- and 52-week averages and the usual seasonal
  change; 80% range from recent errors (split conformal); backtested against two simple rules.

Code and full write-up: [github.com/Sujal-tyagi17/mandi-price-intelligence](https://github.com/Sujal-tyagi17/mandi-price-intelligence)
""")
report = lib.quality_report()
if report:
    with st.expander("Data quality report", icon=":material/fact_check:"):
        st.markdown(report)
