"""US Real Estate Market Dashboard — Streamlit entrypoint.

Run with:  streamlit run app.py

Type a city or ZIP code to get the local market picture: prices, rents, supply,
momentum, affordability, and the socioeconomic factors that drive people to move
between places. Every data source is free and open.
"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent / "src"))

from redash.cache import clear_cache  # noqa: E402
from redash.config import APP_ICON, APP_TITLE, GEO_LABEL  # noqa: E402
from redash.geo import build_region, search_regions  # noqa: E402
from redash.ui import pages  # noqa: E402
from redash.ui.format import ago  # noqa: E402

st.set_page_config(page_title=APP_TITLE, page_icon=APP_ICON, layout="wide",
                   initial_sidebar_state="expanded")

st.markdown("""
<style>
  .block-container { padding-top: 2.2rem; max-width: 1500px; }
  [data-testid="stMetricValue"] { font-size: 1.55rem; }
  [data-testid="stMetricLabel"] { opacity: 0.75; }
  h1 { letter-spacing: -0.02em; }
</style>
""", unsafe_allow_html=True)

DEFAULT_QUERY = "Austin, TX"
EXAMPLES = ["Austin, TX", "Detroit, MI", "Boise, ID", "Pittsburgh, PA",
            "02138", "90210"]


def _sidebar() -> str:
    """Search box plus one-click examples. Returns the query to render."""
    with st.sidebar:
        st.markdown(f"## {APP_ICON} Market lookup")

        # A form so the search applies on submit rather than on every keystroke,
        # and so Enter and the button do the same thing.
        with st.form("lookup", border=False, enter_to_submit=True):
            typed = st.text_input(
                "City or ZIP code",
                value=st.session_state.get("query", DEFAULT_QUERY),
                placeholder="e.g. Austin, TX or 78701")
            if st.form_submit_button("Search", type="primary", width="stretch"):
                st.session_state["query"] = typed.strip()

        st.caption("Or jump to an example:")
        cols = st.columns(2)
        for i, example in enumerate(EXAMPLES):
            if cols[i % 2].button(example, key=f"ex_{example}", width="stretch"):
                st.session_state["query"] = example
                st.rerun()

        st.divider()
        with st.expander("Optional: crime data key"):
            st.text_input(
                "FBI Crime Data Explorer key", type="password", key="fbi_api_key",
                help="Free from api.data.gov/signup. Only the crime panel uses it; "
                     "everything else works without any key.")
            st.caption("[Get a free key](https://api.data.gov/signup/)")

        with st.expander("Data cache"):
            st.caption("Source files are cached on disk so the app stays fast "
                       "and stops hammering public servers.")
            if st.button("Refresh all data", width="stretch"):
                removed = clear_cache()
                st.cache_data.clear()
                st.success(f"Cleared {removed} cached files.")
                st.rerun()

        st.divider()
        st.caption("Data: Zillow Research · US Census ACS · FRED · BLS")

    return st.session_state.get("query", DEFAULT_QUERY)


def _resolve(query: str):
    """Search, then let the user disambiguate when several places match."""
    if not query.strip():
        st.info("Enter a city or ZIP code in the sidebar to begin.")
        return None

    results = search_regions(query)
    if results.empty:
        st.warning(f"No published market found for **{query}**. Try a nearby "
                   f"larger city, a metro name, or a 5-digit ZIP code.")
        st.caption("Examples: " + ", ".join(EXAMPLES))
        return None

    if len(results) > 1:
        labels = [
            f"{row['label']}  ·  {GEO_LABEL.get(row['level'], row['level'])}"
            for _, row in results.iterrows()
        ]
        picked = st.selectbox(
            f"{len(results)} places match “{query}” — pick one:", range(len(labels)),
            format_func=lambda i: labels[i], key=f"disambig_{query}")
        row = results.iloc[picked]
    else:
        row = results.iloc[0]

    return build_region(row)


def main() -> None:
    query = _sidebar()

    st.title("US Real Estate Market Dashboard")
    st.caption("Home prices, rents, supply and the local conditions behind them "
               "— built entirely on free, open data.")

    region = _resolve(query)

    tabs = st.tabs(["📊 Market overview", "🔥 National scanner",
                    "🏘️ Livability", "⚖️ Compare", "🌐 Macro", "ℹ️ Sources"])

    with tabs[0]:
        if region is None:
            st.info("Search a place to see its market.")
        else:
            pages.render_overview(region)
    with tabs[1]:
        pages.render_scanner(region)
    with tabs[2]:
        if region is None:
            st.info("Search a place to see its demographics.")
        else:
            pages.render_livability(region)
    with tabs[3]:
        pages.render_compare(region)
    with tabs[4]:
        pages.render_macro()
    with tabs[5]:
        pages.render_about()


if __name__ == "__main__":
    main()
