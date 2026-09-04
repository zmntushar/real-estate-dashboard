"""US Census ACS 5-year data via the keyless Census Reporter mirror.

The Census Bureau's own API now requires a key, so we read the same ACS tables
through Census Reporter, which is free and needs no registration. Geographies
are addressed by Census GEOID:

    86000US<zcta>            ZIP code tabulation area
    16000US<st><place>       incorporated place (city)
    05000US<st><county>      county
    31000US<cbsa>            metro area
    04000US<st>              state
    01000US                  nation
"""
from __future__ import annotations

import io
import re

import pandas as pd
import streamlit as st

from ..cache import SourceUnavailable, cached_json, cached_text
from ..config import ACS_TABLES, CENSUS_PLACE_CODES, CENSUS_REPORTER

# Commute-time bucket midpoints in minutes for table B08303.
_COMMUTE_MIDPOINTS = {
    "B08303002": 2.5, "B08303003": 7.0, "B08303004": 12.0, "B08303005": 17.0,
    "B08303006": 22.0, "B08303007": 27.0, "B08303008": 32.0, "B08303009": 37.0,
    "B08303010": 42.0, "B08303011": 52.0, "B08303012": 74.5, "B08303013": 100.0,
}


def zcta_geoid(zip_code: str) -> str:
    return f"86000US{str(zip_code).zfill(5)}"


def place_geoid(state_fp: str, place_fp: str) -> str:
    return f"16000US{str(state_fp).zfill(2)}{str(place_fp).zfill(5)}"


def county_geoid(state_fp: str, county_fp: str) -> str:
    return f"05000US{str(state_fp).zfill(2)}{str(county_fp).zfill(3)}"


@st.cache_data(ttl=60 * 60 * 24 * 7, show_spinner=False)
def place_codes() -> pd.DataFrame:
    """Every US place with its FIPS codes, for city-name lookup."""
    try:
        text = cached_text(CENSUS_PLACE_CODES, ttl_hours=24 * 30, label="Census place codes")
    except SourceUnavailable:
        return pd.DataFrame(columns=["STATE", "STATEFP", "PLACEFP", "PLACENAME", "name_key"])
    df = pd.read_csv(io.StringIO(text), sep="|", dtype=str).fillna("")
    df["name_key"] = (
        df["PLACENAME"].str.lower()
        .str.replace(r"\s+(city|town|village|borough|municipality|cdp|"
                     r"consolidated government|metro government|"
                     r"unified government|urban county)\b.*$", "", regex=True)
        .str.strip()
    )
    df["geoid"] = "16000US" + df["STATEFP"] + df["PLACEFP"]
    return df


def find_place(city: str, state: str | None = None) -> pd.DataFrame:
    """Match a city name (and optional state) to Census place records."""
    df = place_codes()
    if df.empty:
        return df
    key = re.sub(r"\s+", " ", city.strip().lower())
    hit = df[df["name_key"] == key]
    if hit.empty:
        hit = df[df["name_key"].str.startswith(key)]
    if state:
        st_up = state.strip().upper()
        narrowed = hit[hit["STATE"] == st_up]
        if not narrowed.empty:
            hit = narrowed
    # Prefer incorporated places over CDPs when both share a name.
    if "TYPE" in hit.columns and len(hit) > 1:
        inc = hit[hit["TYPE"].str.contains("INCORPORATED", na=False)]
        if not inc.empty:
            hit = inc
    return hit


@st.cache_data(ttl=60 * 60 * 24, show_spinner=False)
def geo_parents(geoid: str) -> dict:
    """Containing county / CBSA / state for a geography."""
    url = f"{CENSUS_REPORTER}/geo/tiger2024/{geoid}/parents"
    try:
        data = cached_json(url, ttl_hours=24 * 14, label=f"Census geography {geoid}")
    except SourceUnavailable:
        return {}
    out = {}
    for p in data.get("parents", []):
        out[p.get("relation", "")] = {
            "geoid": p.get("geoid"),
            "name": p.get("display_name"),
            "sumlevel": p.get("sumlevel"),
        }
    return out


@st.cache_data(ttl=60 * 60 * 24, show_spinner=False)
def acs_tables(geoid: str, tables: tuple[str, ...] = tuple(ACS_TABLES)) -> dict:
    """Raw ACS estimates for one geography, keyed by column id."""
    url = f"{CENSUS_REPORTER}/data/show/latest"
    params = {"table_ids": ",".join(tables), "geo_ids": geoid}
    try:
        data = cached_json(url, ttl_hours=24 * 7, params=params, label=f"ACS data for {geoid}")
    except SourceUnavailable:
        return {}
    block = (data.get("data") or {}).get(geoid)
    if not block:
        return {}
    est: dict[str, float] = {}
    for _table, payload in block.items():
        est.update(payload.get("estimate") or {})
    return {
        "estimates": est,
        "name": (data.get("geography") or {}).get(geoid, {}).get("name", geoid),
        "release": (data.get("release") or {}).get("name", "ACS 5-year"),
    }


def _num(est: dict, key: str) -> float | None:
    v = est.get(key)
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    # Census uses large negative sentinels for suppressed values.
    return None if f < -1e6 else f


def _ratio(num, den):
    if num is None or den in (None, 0):
        return None
    return num / den * 100.0


def profile(geoid: str) -> dict:
    """Derived socioeconomic profile: the 'why people move' indicators."""
    raw = acs_tables(geoid)
    if not raw:
        return {}
    e = raw["estimates"]

    pop = _num(e, "B01003001")
    edu_total = _num(e, "B15003001")
    bachelors_plus = sum(
        v for v in (_num(e, f"B15003{i:03d}") for i in (22, 23, 24, 25)) if v is not None
    ) or None
    hs_plus = sum(
        v for v in (_num(e, f"B15003{i:03d}") for i in range(17, 26)) if v is not None
    ) or None

    pov_total, pov_below = _num(e, "B17001001"), _num(e, "B17001002")
    ten_total = _num(e, "B25003001")
    owner, renter = _num(e, "B25003002"), _num(e, "B25003003")

    lf = _num(e, "B23025003")          # civilian labor force
    unemployed = _num(e, "B23025005")

    commute_total = _num(e, "B08303001")
    weighted = sum(
        (_num(e, k) or 0.0) * mid for k, mid in _COMMUTE_MIDPOINTS.items()
    )
    mean_commute = (weighted / commute_total) if commute_total else None

    return {
        "name": raw["name"],
        "release": raw["release"],
        "population": pop,
        "median_age": _num(e, "B01002001"),
        "median_household_income": _num(e, "B19013001"),
        "per_capita_income": _num(e, "B19301001"),
        "bachelors_plus_pct": _ratio(bachelors_plus, edu_total),
        "hs_plus_pct": _ratio(hs_plus, edu_total),
        "poverty_pct": _ratio(pov_below, pov_total),
        "unemployment_pct": _ratio(unemployed, lf),
        "median_home_value": _num(e, "B25077001"),
        "median_gross_rent": _num(e, "B25064001"),
        "owner_occupied_pct": _ratio(owner, ten_total),
        "renter_occupied_pct": _ratio(renter, ten_total),
        "vacant_units": _num(e, "B25004001"),
        "mean_commute_min": mean_commute,
    }
