"""US Real Estate Market Dashboard — Streamlit entrypoint.

Run with:  streamlit run app.py

Type a city or ZIP code to get the local market picture: prices, rents, supply,
momentum, affordability, and the socioeconomic factors that drive people to move
between places. Every data source is free and open.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

sys.path.insert(0, str(Path(__file__).parent / "src"))

from redash import refresh  # noqa: E402
from redash.cache import cache_stats, clear_cache  # noqa: E402
from redash.config import APP_ICON, APP_TITLE, GEO_LABEL  # noqa: E402
from redash.geo import build_region, search_regions  # noqa: E402
from redash.ui import charts, pages  # noqa: E402
from redash.ui.format import ago  # noqa: E402

st.set_page_config(page_title=APP_TITLE, page_icon=APP_ICON, layout="wide",
                   initial_sidebar_state="expanded")

# Layout only. Colours are left to the theme so both palettes stay intact -
# in particular nothing is dimmed with opacity, which is what makes text look
# washed out against a dark background.
st.markdown("""
<style>
  .block-container { padding-top: 2.2rem; max-width: 1500px; }
  [data-testid="stMetricValue"] { font-size: 1.55rem; }
  h1 { letter-spacing: -0.02em; }
</style>
""", unsafe_allow_html=True)

DEFAULT_QUERY = "Austin, TX"
THEME_CHOICES = ["System", "Light", "Dark"]
EXAMPLES = ["Austin, TX", "Detroit, MI", "Boise, ID", "Pittsburgh, PA",
            "02138", "90210"]


def _theme_picker() -> None:
    """Light / Dark / System control.

    Streamlit has no API for setting the theme from Python, but it stores the
    active choice in the browser under a `stActiveTheme-*` key. Writing that key
    and reloading is the same thing its own Settings menu does. The selection is
    mirrored into the URL so it survives the reload - session state does not.
    """
    current = st.query_params.get("theme", "System")
    if current not in THEME_CHOICES:
        current = "System"

    choice = st.segmented_control(
        "Appearance", THEME_CHOICES, default=current, key="theme_choice",
        help="Dark mode also re-colours every chart, not just the page.")
    choice = choice or current
    if choice != current:
        st.query_params["theme"] = choice

    # Idempotent: only touches storage and reloads when the value differs,
    # so this cannot loop. A failure here simply leaves the theme unchanged.
    components.html(
        f"""
        <script>
        (function () {{
          try {{
            var store = window.parent.localStorage;
            var key = null;
            for (var i = 0; i < store.length; i++) {{
              var k = store.key(i);
              if (k && k.indexOf('stActiveTheme') === 0) {{ key = k; break; }}
            }}
            if (!key) {{
              var path = window.parent.location.pathname || '/';
              key = 'stActiveTheme-' + path + '-v2';
            }}
            var wanted = JSON.stringify({choice!r});
            if (store.getItem(key) !== wanted) {{
              store.setItem(key, wanted);
              window.parent.location.reload();
            }}
          }} catch (err) {{ /* storage blocked - keep the current theme */ }}
        }})();
        </script>
        """,
        height=0,
    )


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
        _theme_picker()

        st.divider()
        with st.expander("Optional: crime data key"):
            st.text_input(
                "FBI Crime Data Explorer key", type="password", key="fbi_api_key",
                help="Free from api.data.gov/signup. Only the crime panel uses it; "
                     "everything else works without any key.")
            st.caption("[Get a free key](https://api.data.gov/signup/)")

        with st.expander("Data cache"):
            stats = cache_stats()
            st.caption(f"{stats['files']} files · {stats['mb']:.0f} MB on disk · "
                       f"last updated {ago(stats['newest'])}")
            st.selectbox("What to download", list(refresh.SCOPES),
                         key="refresh_scope",
                         help="ZIP and county files are the large ones. Core "
                              "markets cover most searches.")
            if st.button("Refresh data now", width="stretch"):
                st.session_state["refresh_request"] = st.session_state["refresh_scope"]
                st.session_state.pop("refresh_result", None)
                st.rerun()
            st.caption("Zillow publishes monthly, so a refresh is only worth "
                       "running when new data lands.")

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


def _run_refresh(scope: str) -> dict:
    """Download every dataset in scope, narrating progress. Returns a summary.

    This runs exactly once per request. The caller stores the returned summary
    in session state so that later reruns - clicking a button, resizing - redraw
    the result instead of downloading everything again.
    """
    tasks = refresh.build_tasks(refresh.SCOPES[scope])
    st.caption(f"{scope} — {len(tasks)} datasets. Cached copies are discarded "
               f"and pulled fresh from Zillow, FRED and the Census Bureau. "
               f"Keep this tab open until it finishes.")

    clear_cache()
    st.cache_data.clear()

    bar = st.progress(0.0, text="Preparing…")
    log = st.status(f"Downloading {len(tasks)} datasets…", expanded=True)
    started = time.time()
    downloaded = 0.0
    lines: list[str] = []
    failures: list[list[str]] = []

    for event in refresh.run(tasks):
        counter = f"({event.index}/{event.total})"
        if not event.done:
            bar.progress(event.fraction,
                         text=f"{counter} {event.group} · {event.label}")
            continue

        bar.progress(event.fraction, text=f"{counter} {event.label}")
        if event.error:
            failures.append([event.label, event.error])
            line = f":red[✗] **{event.label}** — {event.error}"
        else:
            downloaded += event.mb
            line = f":green[✓] {event.label} · {event.mb:.1f} MB"
        lines.append(line)
        log.write(line)

    summary = {
        "scope": scope,
        "total": len(tasks),
        "ok": len(tasks) - len(failures),
        "mb": downloaded,
        "seconds": time.time() - started,
        "lines": lines,
        "failures": failures,
    }
    _finish_log(log, bar, summary)
    return summary


def _finish_log(log, bar, summary: dict) -> None:
    bar.progress(1.0, text=f"Done — {summary['mb']:.0f} MB "
                           f"in {summary['seconds']:.0f}s")
    if summary["failures"]:
        log.update(label=f"Finished with {len(summary['failures'])} problem(s)",
                   state="error", expanded=True)
    else:
        log.update(label=f"All {summary['total']} datasets downloaded",
                   state="complete", expanded=False)


def _replay_refresh(summary: dict) -> None:
    """Redraw a completed refresh without downloading anything again."""
    st.caption(f"{summary['scope']} — {summary['total']} datasets.")
    bar = st.progress(1.0)
    log = st.status("Downloaded datasets", expanded=False)
    for line in summary["lines"]:
        log.write(line)
    _finish_log(log, bar, summary)


def _refresh_screen() -> bool:
    """Render the refresh page if one is pending or just finished.

    Returns True when the refresh screen owns the page for this run, so the
    caller can skip the dashboard.
    """
    request = st.session_state.pop("refresh_request", None)
    summary = st.session_state.get("refresh_result")
    if request is None and summary is None:
        return False

    st.subheader("Refreshing market data")

    if request is not None:
        summary = _run_refresh(request)
        st.session_state["refresh_result"] = summary
    else:
        _replay_refresh(summary)

    if summary["failures"]:
        st.warning(f"{summary['ok']} of {summary['total']} datasets refreshed. "
                   f"The rest are listed above — the app falls back to any older "
                   f"copy it still has, so those panels keep working.")
    else:
        st.success(f"Refreshed {summary['ok']} datasets · "
                   f"{summary['mb']:.0f} MB · {summary['seconds']:.0f} seconds.")

    if st.button("Back to the dashboard", type="primary"):
        st.session_state.pop("refresh_result", None)
        st.rerun()
    return True


def _active_theme() -> str:
    """Whichever theme Streamlit is currently rendering: 'light' or 'dark'."""
    try:
        return str(st.context.theme.type or "light").lower()
    except Exception:  # noqa: BLE001 - older runtimes and AppTest have no context
        return "light"


def main() -> None:
    # Charts are drawn with explicit colours, so they need to be told which
    # palette to use before anything renders.
    charts.use_theme(_active_theme())

    query = _sidebar()

    st.title("US Real Estate Market Dashboard")
    st.caption("Home prices, rents, supply and the local conditions behind them "
               "— built entirely on free, open data.")

    if _refresh_screen():
        return

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
