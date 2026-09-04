"""Page renderers for the dashboard.

Each render_* function owns one tab. They pull from the source modules, derive
what they need through `analytics`, and draw with `charts`. Anything that can
be missing upstream degrades to a note rather than an exception.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from .. import analytics as an
from ..cache import cache_stats
from ..config import DISCLAIMER, GEO_LABEL, ZILLOW_FILES
from ..geo import Region, peer_regions, short_metro_name
from ..sources import bls, census, fbi, fred, zillow
from . import charts
from .format import ago, compact, month, num, pct, usd, usd_compact

# Metrics shown on the overview, in display order.
OVERVIEW_METRICS = ["zhvi", "median_sale_price", "zori", "inventory",
                    "new_listings", "days_to_pending", "price_cuts"]


# ---------------------------------------------------------------------------
# shared pieces
# ---------------------------------------------------------------------------
def _state_badge(chg_1y: float | None, chg_3m: float | None) -> None:
    state, colour = an.classify_market(chg_1y, chg_3m)
    icon = {"green": "📈", "orange": "➖", "red": "📉", "gray": "❓"}[colour]
    st.badge(f"{icon} {state}", color=colour if colour != "gray" else "grey")


def _delta(value: float | None) -> str | None:
    return None if value is None or pd.isna(value) else f"{value:+.1f}%"


@st.cache_data(ttl=60 * 60 * 12, show_spinner=False)
def _peer_series(level: str, region_id: int, metric: str) -> pd.Series | None:
    return zillow.series_for(metric, level, region_id)


def _resolve_metric(region: Region, metric: str,
                    peers: list[tuple[str, str, int]]) -> tuple[pd.Series | None, str]:
    """Series for a metric at the region's own level, else its parent metro.

    Zillow does not publish supply-side metrics for ZIP codes, so we fall back
    to the containing metro and say so rather than showing nothing.
    """
    levels = ZILLOW_FILES.get(metric, {}).get("levels", [])
    if region.level in levels:
        s = zillow.series_for(metric, region.level, region.region_id)
        if s is not None:
            return s, ""
    for level, name, rid in peers:
        if level in levels and name != "United States":
            s = _peer_series(level, rid, metric)
            if s is not None:
                return s, name
    return None, ""


# ---------------------------------------------------------------------------
# 1. Market overview
# ---------------------------------------------------------------------------
def render_overview(region: Region) -> None:
    with st.spinner(f"Loading Zillow home value history for {region.name}…"):
        peers = peer_regions(region)
        zhvi = zillow.series_for("zhvi", region.level, region.region_id)

    if zhvi is None or zhvi.empty:
        st.warning(f"Zillow does not publish a home value index for "
                   f"{region.label}. Try a larger geography.")
        return

    chg_1y = an.pct_change_over(zhvi, 12)
    chg_3m = an.pct_change_over(zhvi, 3)
    chg_1m = an.pct_change_over(zhvi, 1)
    chg_5y = an.pct_change_over(zhvi, 60)

    head_left, head_right = st.columns([3, 1])
    with head_left:
        st.subheader(region.label)
        bits = [GEO_LABEL.get(region.level, region.level)]
        if region.metro and region.level in ("Zip", "City"):
            bits.append(region.metro)
        if region.county:
            bits.append(region.county)
        st.caption(" · ".join(bits) + f" · data through {month(zhvi.index[-1])}")
    with head_right:
        _state_badge(chg_1y, chg_3m)

    # --- headline price KPIs -------------------------------------------------
    with st.spinner("Loading sale prices and rents…"):
        msp, msp_src = _resolve_metric(region, "median_sale_price", peers)
        zori, zori_src = _resolve_metric(region, "zori", peers)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Typical home value", usd(zhvi.iloc[-1]), _delta(chg_1y),
              help="Zillow Home Value Index: the typical value for homes in the "
                   "35th-65th percentile range. Delta is year over year.",
              border=True)
    c2.metric("Median sale price",
              usd(msp.iloc[-1]) if msp is not None else "—",
              _delta(an.pct_change_over(msp, 12)),
              help=f"Median price of homes that actually sold."
                   + (f" Source geography: {msp_src}." if msp_src else ""),
              border=True)
    c3.metric("Typical rent",
              usd(zori.iloc[-1]) if zori is not None else "—",
              _delta(an.pct_change_over(zori, 12)),
              help="Zillow Observed Rent Index, smoothed asking rent."
                   + (f" Source geography: {zori_src}." if zori_src else ""),
              border=True)
    yield_pct = an.gross_rent_yield(
        float(zhvi.iloc[-1]), float(zori.iloc[-1]) if zori is not None else None)
    c4.metric("Gross rent yield", pct(yield_pct),
              help="Annual asking rent as a share of typical home value, before "
                   "costs. A rough income-versus-price gauge.",
              border=True)

    # --- momentum KPIs -------------------------------------------------------
    with st.spinner("Loading inventory, days on market and price cuts…"):
        dtp, dtp_src = _resolve_metric(region, "days_to_pending", peers)
        cuts, cuts_src = _resolve_metric(region, "price_cuts", peers)
        inv, inv_src = _resolve_metric(region, "inventory", peers)

    d1, d2, d3, d4 = st.columns(4)
    d1.metric("1-month change", pct(chg_1m, signed=True), border=True)
    d2.metric("5-year change", pct(chg_5y, signed=True),
              help="Cumulative change in typical home value over five years.",
              border=True)
    d3.metric("Days to pending",
              f"{dtp.iloc[-1]:,.0f}" if dtp is not None else "—",
              _delta(an.pct_change_over(dtp, 12)), delta_color="inverse",
              help="Mean days from listing to pending sale. Rising means a "
                   "slowing market." + (f" Source: {dtp_src}." if dtp_src else ""),
              border=True)
    d4.metric("Listings with a price cut",
              pct(cuts.iloc[-1] * 100.0) if cuts is not None else "—",
              _delta(an.pct_change_over(cuts, 12)), delta_color="inverse",
              help="Share of active listings that cut their price this month."
                   + (f" Source: {cuts_src}." if cuts_src else ""),
              border=True)

    st.divider()

    # --- price history and momentum -----------------------------------------
    left, right = st.columns([3, 2])
    with left:
        bench = []
        with st.spinner("Loading benchmark markets…"):
            for level, name, rid in peers:
                s = _peer_series(level, rid, "zhvi")
                if s is not None:
                    bench.append((name, s))
        st.plotly_chart(
            charts.price_history(zhvi, region.label, bench,
                                 title="Typical home value over time"),
            width="stretch")
    with right:
        st.plotly_chart(
            charts.yoy_bars(an.yoy_series(zhvi),
                            title="Year-over-year price change"),
            width="stretch")

    # --- relative growth -----------------------------------------------------
    horizon = st.select_slider(
        "Compare growth since", options=["1 year", "3 years", "5 years",
                                         "10 years", "2000"],
        value="5 years", key="overview_horizon")
    offsets = {"1 year": 12, "3 years": 36, "5 years": 60, "10 years": 120}
    if horizon == "2000":
        start = zhvi.index[0]
    else:
        start = zhvi.index[-1] - pd.DateOffset(months=offsets[horizon])

    rebased = {region.label: an.rebase(zhvi, start)}
    for level, name, rid in peers:
        s = _peer_series(level, rid, "zhvi")
        if s is not None:
            rebased[name] = an.rebase(s, start)
    rebased = {k: v for k, v in rebased.items() if v is not None}
    if len(rebased) > 1:
        st.plotly_chart(
            charts.indexed_comparison(rebased, start, highlight=region.label,
                                      title="Growth against larger markets"),
            width="stretch")

    # --- supply and demand ---------------------------------------------------
    if inv is not None or dtp is not None:
        note = inv_src or dtp_src
        st.plotly_chart(
            charts.dual_axis(inv, "Homes for sale", dtp, "Days to pending",
                             title="Supply and speed of sale"
                                   + (f" — {note}" if note else ""),
                             right_suffix="d"),
            width="stretch")
        if note:
            st.caption(f"Zillow publishes inventory and days-to-pending at metro "
                       f"level and above, so these show {note}.")

    st.divider()

    # --- affordability -------------------------------------------------------
    st.markdown("#### Affordability at today's rates")
    with st.spinner("Loading mortgage rates (FRED) and local income (Census)…"):
        rate = fred.mortgage_rate_now()
        profile = census.profile(region.census_geoid) if region.census_geoid else {}
    income = profile.get("median_household_income")

    a1, a2 = st.columns([1, 2])
    with a1:
        down = st.slider("Down payment %", 0, 50, 20, 5, key="down_pct")
    aff = an.affordability(float(zhvi.iloc[-1]), income, rate, down_payment_pct=down)

    f1, f2, f3, f4 = st.columns(4)
    f1.metric("30-yr mortgage rate", pct(rate, 2),
              help="Current Freddie Mac average via FRED.", border=True)
    f2.metric("Monthly payment", usd(aff["monthly_total"]),
              help="Principal, interest, plus about 1.5% of value a year for "
                   "property tax and insurance.", border=True)
    f3.metric("Income needed", usd(aff["income_needed"]),
              help="Gross household income for this payment to sit at 28% of "
                   "income, a common lender threshold.", border=True)
    f4.metric("Cost as share of local income", pct(aff["income_share_pct"]),
              help="Payment against local median household income (ACS). Over "
                   "30% is generally considered cost-burdened.", border=True)

    if aff["price_to_income"]:
        ratio = aff["price_to_income"]
        verdict = ("historically affordable" if ratio < 3 else
                   "moderately stretched" if ratio < 5 else "severely stretched")
        st.caption(f"Home value is **{ratio:.1f}×** local median household income "
                   f"({usd(income)}) — {verdict}. A ratio near 3 was the long-run "
                   f"US norm.")
    elif not region.census_geoid:
        st.caption("Local income is not available for this geography, so the "
                   "income-based measures are blank.")

    # --- trailing returns ----------------------------------------------------
    with st.expander("Trailing returns and drawdown"):
        table = an.growth_table(zhvi)
        st.dataframe(
            table, hide_index=True, width="stretch",
            column_config={
                "Change %": st.column_config.NumberColumn(format="%+.1f%%"),
                "Annualised %": st.column_config.NumberColumn(format="%+.1f%%"),
            })
        dd = an.drawdown_from_peak(zhvi)
        if dd:
            gap, peak_at = dd
            if gap < -0.5:
                st.caption(f"Currently **{gap:.1f}%** below the peak of "
                           f"{usd(zhvi.max())} set in {month(peak_at)}.")
            else:
                st.caption(f"At or near its all-time peak ({month(peak_at)}).")


# ---------------------------------------------------------------------------
# 2. National scanner
# ---------------------------------------------------------------------------
SIZE_TIERS = {
    "Major markets": 100,
    "Large + mid-size": 400,
    "Include smaller markets": 1500,
    "Everything": 10 ** 9,
}


def render_scanner(region: Region | None) -> None:
    st.subheader("Where the market is rising and falling")
    st.caption("Every published region ranked on price change and momentum. "
               "Small regions swing hardest, so start with the larger tiers.")

    c1, c2, c3 = st.columns([1, 1, 1])
    level = c1.selectbox("Geography", ["Metro", "City", "County", "Zip", "State"],
                         key="scan_level")
    tier = c2.selectbox("Market size", list(SIZE_TIERS), key="scan_tier")
    window = c3.selectbox("Ranked by",
                          {"chg_1y": "1-year change", "chg_3m": "3-month change",
                           "chg_1m": "1-month change", "chg_5y": "5-year change",
                           "momentum": "Momentum score"},
                          format_func=lambda k: {"chg_1y": "1-year change",
                                                 "chg_3m": "3-month change",
                                                 "chg_1m": "1-month change",
                                                 "chg_5y": "5-year change",
                                                 "momentum": "Momentum score"}[k],
                          key="scan_window")

    with st.spinner(f"Loading Zillow home values, rents and market friction "
                    f"for every {GEO_LABEL.get(level, level).lower()}…"):
        table = zillow.combined_snapshot(level)

    if table.empty:
        st.warning("That geography level is not available right now.")
        return

    table = table.copy()
    table["momentum"] = an.momentum_score(table)
    table = table[table["SizeRank"] <= SIZE_TIERS[tier]]

    states = sorted({s for s in table.get("StateName", pd.Series(dtype=str)).dropna().unique()}
                    | {s for s in table.get("State", pd.Series(dtype=str)).dropna().unique()})
    chosen = st.multiselect("Filter to states (optional)", states, key="scan_states")
    if chosen:
        col = "State" if "State" in table else "StateName"
        table = table[table[col].isin(chosen)]

    if table.empty:
        st.info("No regions match those filters.")
        return

    table["display"] = table.get("label", table["RegionName"])
    if "City" in table.columns and level == "Zip":
        table["display"] = (table["RegionName"] + " · " + table["City"].fillna("")
                            + ", " + table["State"].fillna(""))
    elif "State" in table.columns and level == "City":
        table["display"] = table["RegionName"] + ", " + table["State"].fillna("")

    ranked = table.dropna(subset=[window])
    as_of = table["as_of"].max() if "as_of" in table else None
    st.caption(f"{len(table):,} regions · data through {month(as_of)}")

    top = ranked.nlargest(15, window)
    bottom = ranked.nsmallest(15, window)
    label_map = {"chg_1y": "1-year change", "chg_3m": "3-month change",
                 "chg_1m": "1-month change", "chg_5y": "5-year change",
                 "momentum": "momentum"}
    suffix = "" if window == "momentum" else "%"

    left, right = st.columns(2)
    with left:
        st.plotly_chart(charts.ranked_bars(top, window, "display",
                                           f"Rising fastest — {label_map[window]}",
                                           suffix=suffix), width="stretch")
    with right:
        st.plotly_chart(charts.ranked_bars(bottom, window, "display",
                                           f"Falling hardest — {label_map[window]}",
                                           suffix=suffix), width="stretch")

    scatter = ranked.dropna(subset=["latest", "chg_1y"])
    if not scatter.empty:
        st.plotly_chart(
            charts.scanner_scatter(
                scatter.nsmallest(600, "SizeRank"), "latest", "chg_1y", "display",
                size_col=None,
                x_title="Typical home value ($)", y_title="1-year change",
                title="Price level against 1-year growth"),
            width="stretch")
        st.caption("Each dot is a market. Upper-left is cheap and appreciating; "
                   "lower-right is expensive and cooling.")

    st.markdown("#### Full table")
    cols = ["display", "latest", "chg_1m", "chg_3m", "chg_1y", "chg_3y", "chg_5y",
            "momentum"]
    for extra in ("zori", "rent_yield", "days_to_pending", "price_cuts", "inventory"):
        if extra in table.columns:
            cols.append(extra)
    view = table[[c for c in cols if c in table.columns]].sort_values(
        window, ascending=False)
    if "price_cuts" in view.columns:
        view = view.assign(price_cuts=view["price_cuts"] * 100.0)

    st.dataframe(
        view, hide_index=True, width="stretch", height=440,
        column_config={
            "display": st.column_config.TextColumn("Region", width="medium"),
            "latest": st.column_config.NumberColumn("Home value", format="$%,d"),
            "chg_1m": st.column_config.NumberColumn("1m", format="%+.1f%%"),
            "chg_3m": st.column_config.NumberColumn("3m", format="%+.1f%%"),
            "chg_1y": st.column_config.NumberColumn("1y", format="%+.1f%%"),
            "chg_3y": st.column_config.NumberColumn("3y", format="%+.1f%%"),
            "chg_5y": st.column_config.NumberColumn("5y", format="%+.1f%%"),
            "momentum": st.column_config.ProgressColumn(
                "Momentum", format="%.0f", min_value=0, max_value=100),
            "zori": st.column_config.NumberColumn("Rent", format="$%,d"),
            "rent_yield": st.column_config.NumberColumn("Yield", format="%.1f%%"),
            "days_to_pending": st.column_config.NumberColumn("Days", format="%.0f"),
            "price_cuts": st.column_config.NumberColumn("Price cuts", format="%.1f%%"),
            "inventory": st.column_config.NumberColumn("Inventory", format="%,d"),
        })
    st.caption("Momentum blends 1-year and 3-month price change, acceleration "
               "against the 3-year pace, price cuts and days to pending, then "
               "ranks it against the other regions shown. 100 is the hottest.")


# ---------------------------------------------------------------------------
# 3. Livability
# ---------------------------------------------------------------------------
def _short_geo_name(relation: str, name: str) -> str:
    """Keep comparison axis labels short enough to read.

    CBSA names run long ("Austin-Round Rock-San Marcos, TX"), which overflows a
    bar chart axis, so collapse them to their lead city.
    """
    name = name.replace(" Metro Area", "")
    if relation == "CBSA":
        return f"{short_metro_name(name) or name} metro"
    return name


def _profile_row(profile: dict) -> None:
    c = st.columns(4)
    c[0].metric("Population", compact(profile.get("population")), border=True)
    c[1].metric("Median household income", usd(profile.get("median_household_income")),
                border=True)
    c[2].metric("Bachelor's degree or higher", pct(profile.get("bachelors_plus_pct")),
                help="Share of adults 25 and over.", border=True)
    c[3].metric("Poverty rate", pct(profile.get("poverty_pct")), border=True)

    c = st.columns(4)
    c[0].metric("Median age", num(profile.get("median_age"), 1), border=True)
    c[1].metric("Unemployment (ACS)", pct(profile.get("unemployment_pct")), border=True)
    c[2].metric("Owner-occupied", pct(profile.get("owner_occupied_pct")),
                help="Share of occupied homes lived in by their owner.", border=True)
    c[3].metric("Mean commute", f"{profile['mean_commute_min']:.0f} min"
                if profile.get("mean_commute_min") else "—", border=True)


def render_livability(region: Region) -> None:
    st.subheader(f"Who lives in {region.name}, and what it costs them")

    if not region.census_geoid:
        st.info("Census demographics are matched for ZIP codes and cities. "
                "Search a ZIP or a city name to see this panel.")
        return

    with st.spinner("Loading Census demographics (ACS)…"):
        profile = census.profile(region.census_geoid)
    if not profile:
        st.warning("Census did not return a profile for this geography.")
        return

    st.caption(f"American Community Survey · {profile.get('release', '5-year')} · "
               f"{profile.get('name', region.label)}")
    _profile_row(profile)

    # --- against its parents -------------------------------------------------
    parents = [(rel, node) for rel, node in region.parents.items()
               if rel in ("county", "CBSA", "state", "nation")]
    peer_profiles: list[tuple[str, dict]] = [(region.name, profile)]
    with st.spinner("Loading Census data for the surrounding county, metro and state…"):
        for rel, node in parents:
            gid = node.get("geoid")
            if not gid:
                continue
            p = census.profile(gid)
            if p:
                peer_profiles.append(
                    (_short_geo_name(rel, node.get("name", rel)), p))

    if len(peer_profiles) > 1:
        st.markdown("#### How it compares")

        indicators = [
            ("median_household_income", "Median household income", "$", ""),
            ("bachelors_plus_pct", "Bachelor's degree or higher", "", "%"),
            ("poverty_pct", "Poverty rate", "", "%"),
            ("median_gross_rent", "Median gross rent", "$", ""),
        ]
        cols = st.columns(2)
        for i, (key, title, prefix, suffix) in enumerate(indicators):
            labels, values = [], []
            for name, p in peer_profiles:
                if p.get(key) is not None:
                    labels.append(name)
                    values.append(p[key])
            if len(values) > 1:
                cols[i % 2].plotly_chart(
                    charts.comparison_bars(labels, values, title,
                                           suffix=suffix, prefix=prefix),
                    width="stretch")

    # --- housing cost burden -------------------------------------------------
    st.markdown("#### Housing costs")
    h = st.columns(4)
    h[0].metric("Median home value (ACS)", usd(profile.get("median_home_value")),
                help="Self-reported owner estimate, so it lags Zillow's index.",
                border=True)
    h[1].metric("Median gross rent", usd(profile.get("median_gross_rent")), border=True)
    h[2].metric("Renter-occupied", pct(profile.get("renter_occupied_pct")), border=True)
    h[3].metric("Vacant units", compact(profile.get("vacant_units")), border=True)

    rent, income = profile.get("median_gross_rent"), profile.get("median_household_income")
    if rent and income:
        burden = rent * 12.0 / income * 100.0
        st.caption(f"Median rent takes **{burden:.0f}%** of median household "
                   f"income. Above 30% is the federal cost-burden threshold.")

    # --- labour market -------------------------------------------------------
    fips = region.county_fips
    if fips:
        with st.spinner("Loading county unemployment (BLS)…"):
            series = bls.unemployment_rate(*fips)
        county_name = (region.parents.get("county") or {}).get("name", "county")
        if series is not None and not series.empty:
            st.markdown("#### Local labour market")
            st.plotly_chart(
                charts.simple_line(series,
                                   f"Unemployment rate — {county_name}",
                                   y_suffix="%"),
                width="stretch")
            st.caption(f"Bureau of Labor Statistics, county level. Latest: "
                       f"{series.iloc[-1]:.1f}% ({month(series.index[-1])}).")

    # --- crime ---------------------------------------------------------------
    _render_crime(region)


def _render_crime(region: Region) -> None:
    st.markdown("#### Crime")
    key = fbi.api_key()
    state = region.state if region.state and len(region.state) == 2 else None
    if not state:
        st.caption("Crime statistics are keyed to states; no state resolved here.")
        return
    if not key:
        st.info("Add a free FBI Crime Data Explorer key in the sidebar to show "
                "violent and property crime trends. Every other panel in this "
                "app needs no key at all.")
        return

    frames = []
    for offense in ("violent-crime", "property-crime"):
        df = fbi.state_rates(state, offense, key)
        if df is not None and not df.empty:
            frames.append((fbi.OFFENSES[offense], df))
    if not frames:
        st.caption("The FBI API returned no data for this state — the key may be "
                   "invalid or the series unpublished.")
        return

    cols = st.columns(len(frames))
    for col, (name, df) in zip(cols, frames):
        local = df[df["scope"] != "United States"] if "scope" in df else df
        s = pd.Series(local["rate"].to_numpy(),
                      index=pd.to_datetime(local["year"], format="%Y"))
        col.plotly_chart(
            charts.simple_line(s.sort_index(), f"{name} rate — {state}",
                               y_suffix=" /100k"),
            width="stretch")
    st.caption("FBI Crime Data Explorer, offences per 100,000 people, state level.")


# ---------------------------------------------------------------------------
# 4. Compare
# ---------------------------------------------------------------------------
def render_compare(region: Region | None) -> None:
    st.subheader("Compare markets side by side")

    level = st.selectbox("Geography", ["Metro", "City", "County", "State", "Zip"],
                         key="cmp_level")
    directory = zillow.region_directory(level)
    if directory.empty:
        st.warning("That geography is unavailable.")
        return

    options = directory["label"].dropna().astype(str).tolist()
    default = []
    if region is not None and region.level == level:
        match = [o for o in options if o.startswith(region.name)]
        default = match[:1]
    if not default:
        default = options[1:4]

    picked = st.multiselect("Markets", options, default=default,
                            max_selections=6, key="cmp_regions")
    if not picked:
        st.info("Pick at least one market.")
        return

    rows = directory[directory["label"].isin(picked)]
    metric = st.selectbox(
        "Metric", ["zhvi", "zori", "median_sale_price", "days_to_pending",
                   "price_cuts", "inventory"],
        format_func=lambda m: ZILLOW_FILES[m]["label"], key="cmp_metric")
    if level not in ZILLOW_FILES[metric]["levels"]:
        st.warning(f"{ZILLOW_FILES[metric]['label']} is not published at "
                   f"{GEO_LABEL[level].lower()} level.")
        return

    series_map: dict[str, pd.Series] = {}
    with st.spinner(f"Loading {ZILLOW_FILES[metric]['label'].lower()} for "
                    f"{len(rows)} markets…"):
        for _, row in rows.iterrows():
            s = _peer_series(level, int(row["RegionID"]), metric)
            if s is not None:
                series_map[str(row["label"])] = s
    if not series_map:
        st.warning("No data for those markets.")
        return

    summary = []
    for label, s in series_map.items():
        summary.append({
            "Market": label,
            "Latest": float(s.iloc[-1]),
            "1m": an.pct_change_over(s, 1),
            "3m": an.pct_change_over(s, 3),
            "1y": an.pct_change_over(s, 12),
            "3y": an.pct_change_over(s, 36),
            "5y": an.pct_change_over(s, 60),
            "5y annualised": an.cagr(s, 60),
        })
    unit = ZILLOW_FILES[metric]["unit"]
    fmt = "$%,d" if unit == "usd" else ("%.3f" if unit == "pct_frac" else "%,.0f")
    st.dataframe(
        pd.DataFrame(summary), hide_index=True, width="stretch",
        column_config={
            "Latest": st.column_config.NumberColumn(format=fmt),
            "1m": st.column_config.NumberColumn(format="%+.1f%%"),
            "3m": st.column_config.NumberColumn(format="%+.1f%%"),
            "1y": st.column_config.NumberColumn(format="%+.1f%%"),
            "3y": st.column_config.NumberColumn(format="%+.1f%%"),
            "5y": st.column_config.NumberColumn(format="%+.1f%%"),
            "5y annualised": st.column_config.NumberColumn(format="%+.1f%%"),
        })

    years = st.select_slider("History", [3, 5, 10, 15, 25], value=10,
                             key="cmp_years")
    cutoff = max(s.index[-1] for s in series_map.values()) - pd.DateOffset(years=years)
    mode = st.radio("View", ["Indexed to 100", "Absolute"], horizontal=True,
                    key="cmp_mode")

    if mode == "Indexed to 100":
        rebased = {k: an.rebase(v, cutoff) for k, v in series_map.items()}
        rebased = {k: v for k, v in rebased.items() if v is not None}
        st.plotly_chart(
            charts.indexed_comparison(rebased, cutoff,
                                      title=ZILLOW_FILES[metric]["label"]),
            width="stretch")
    else:
        fig = charts.price_history(
            None, "", [(k, v[v.index >= cutoff]) for k, v in series_map.items()],
            title=ZILLOW_FILES[metric]["label"],
            y_prefix="$" if unit == "usd" else "")
        st.plotly_chart(fig, width="stretch")


# ---------------------------------------------------------------------------
# 5. Macro backdrop
# ---------------------------------------------------------------------------
def render_macro() -> None:
    st.subheader("National backdrop")
    st.caption("The rate and supply environment every local market sits inside. "
               "Source: FRED, Federal Reserve Bank of St. Louis.")

    with st.spinner("Loading macro series from FRED…"):
        fred.series("MORTGAGE30US")  # warms every frequency bundle up front

    tiles = [("MORTGAGE30US", "%"), ("CSUSHPINSA", ""), ("MSPUS", "$"),
             ("MSACSR", " mo")]
    cols = st.columns(4)
    for col, (sid, suffix) in zip(cols, tiles):
        got = fred.latest(sid)
        if got is None:
            col.metric(fred.label(sid), "—", border=True)
            continue
        value, when = got
        text = usd_compact(value) if suffix == "$" else (
            f"{value:,.2f}{suffix}" if suffix else f"{value:,.1f}")
        series = fred.series(sid)
        delta = an.pct_change_over(series, 12) if series is not None else None
        col.metric(fred.label(sid), text, _delta(delta),
                   help=f"Latest observation {month(when)}.", border=True)

    charts_grid = [("MORTGAGE30US", "%", False), ("CSUSHPINSA", "", True),
                   ("MSPUS", "$", True), ("HOUST", "", False),
                   ("MSACSR", "", False), ("UNRATE", "%", False)]
    for i in range(0, len(charts_grid), 2):
        cols = st.columns(2)
        for col, (sid, suffix, fill) in zip(cols, charts_grid[i:i + 2]):
            s = fred.series(sid)
            if s is None:
                col.info(f"{fred.label(sid)} unavailable right now.")
                continue
            s = s[s.index >= s.index.max() - pd.DateOffset(years=25)]
            col.plotly_chart(
                charts.simple_line(
                    s, fred.label(sid),
                    y_prefix="$" if suffix == "$" else "",
                    y_suffix="%" if suffix == "%" else "", fill=fill),
                width="stretch")

    st.caption("Mortgage rates drive affordability directly: every point of rate "
               "moves the payment on a median-priced home by roughly 10%.")


# ---------------------------------------------------------------------------
# about / footer
# ---------------------------------------------------------------------------
def render_about() -> None:
    st.subheader("Where this data comes from")
    st.markdown("""
| Panel | Source | Coverage | Key needed |
|---|---|---|---|
| Home values, rents, inventory, days to pending, price cuts | [Zillow Research](https://www.zillow.com/research/data/) | ZIP, city, county, metro, state — monthly since 2000 | No |
| Income, education, poverty, tenure, commute | US Census ACS via [Census Reporter](https://censusreporter.org) | ZIP, city, county, metro, state | No |
| Mortgage rates, Case-Shiller, housing starts | [FRED](https://fred.stlouisfed.org), St. Louis Fed | National | No |
| County unemployment | [BLS](https://www.bls.gov/developers/) Local Area Unemployment Statistics | County, monthly | No |
| Violent and property crime | [FBI Crime Data Explorer](https://cde.ucr.cjis.gov) | State, annual | Free key |

**Reading the numbers.** Zillow's home value index tracks the typical home in
the 35th–65th percentile of a market, smoothed and seasonally adjusted, so it
moves differently from median sale price, which reflects whatever mix of homes
happened to sell. ACS figures are multi-year survey estimates, so a small ZIP
carries a wide margin of error and the release lags the market data by a year or
more. Momentum is relative to the regions on screen, not an absolute scale.
""")
    stats = cache_stats()
    st.caption(f"Local cache: {stats['files']} files, {stats['mb']:.1f} MB, "
               f"last refreshed {ago(stats['newest'])}.")
    st.caption(DISCLAIMER)
