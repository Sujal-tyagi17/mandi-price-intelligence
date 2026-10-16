"""MandiPulse dashboard.   streamlit run dashboard/app.py"""


import streamlit as st

import lib

HERE = lib.ROOT / "dashboard"   # (not __file__: Streamlit's AppTest runs a copy of this script)
st.set_page_config(page_title="MandiPulse", page_icon=":material/agriculture:", layout="wide")
st.html(lib.CSS)

if not lib.available():
    st.title("MandiPulse")
    st.info("No results yet. Download the data (see DATA.md) and run `python run_all.py`, then reload this page.")
    st.stop()

pages = [
    st.Page(HERE / "views/prices.py", title="Prices now", icon=":material/monitoring:", default=True),
    st.Page(HERE / "views/when.py", url_path="when-to-sell", title="When to sell", icon=":material/calendar_month:"),
    st.Page(HERE / "views/where.py", url_path="where-to-sell", title="Where to sell", icon=":material/storefront:"),
    st.Page(HERE / "views/ban.py", url_path="export-ban", title="Export ban", icon=":material/block:"),
    st.Page(HERE / "views/forecast.py", url_path="forecast", title="Next 4 weeks", icon=":material/trending_up:"),
    st.Page(HERE / "views/shocks.py", url_path="shocks", title="Shocks & supply", icon=":material/bolt:"),
    st.Page(HERE / "views/about.py", url_path="about", title="About the data", icon=":material/info:"),
]
page = st.navigation(pages, position="top")

lib.sample_banner()
if page.url_path not in ("export-ban", "about"):
    st.segmented_control("Crop", options=lib.COMMODITIES, key="f_crop", default=lib.COMMODITIES[0],
                         label_visibility="collapsed")
page.run()

info = lib.build_info()
st.html('<p style="margin-top:3rem;opacity:.55;font-size:.8rem">Built by Sujal Tyagi. Daily wholesale prices '
        f'reported by APMC mandis to Agmarknet, via the CEDA Agri Market API · data {info.get("first_date", "")} '
        f'to {info.get("last_date", "")}.</p>')
