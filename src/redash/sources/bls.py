"""County unemployment from the BLS public API (v1 needs no key).

Series id layout for Local Area Unemployment Statistics:
    LAUCN <state fips><county fips> 0000000003   -> unemployment rate
    LAUCN <state fips><county fips> 0000000004   -> unemployed, level
"""
from __future__ import annotations

import datetime as _dt

import pandas as pd
import streamlit as st

from ..cache import SourceUnavailable, cached_json
from ..config import BLS_V1

_MONTHS = {f"M{i:02d}": i for i in range(1, 13)}


def county_series_id(state_fips: str, county_fips: str, measure: str = "03") -> str:
    return f"LAUCN{str(state_fips).zfill(2)}{str(county_fips).zfill(3)}00000000{measure}"


@st.cache_data(ttl=60 * 60 * 24, show_spinner=False)
def unemployment_rate(state_fips: str, county_fips: str, years: int = 10) -> pd.Series | None:
    """Monthly county unemployment rate for the trailing `years` years."""
    end = _dt.date.today().year
    # The keyless v1 API rejects spans longer than 10 years (inclusive).
    start = end - min(max(1, years), 10) + 1
    sid = county_series_id(state_fips, county_fips)
    # The keyless v1 API caps each request at a 10-year span.
    payload = {"seriesid": [sid], "startyear": str(start), "endyear": str(end)}
    try:
        data = cached_json(BLS_V1, ttl_hours=24, method="POST", payload=payload,
                           label=f"BLS unemployment {sid}")
    except SourceUnavailable:
        return None
    if data.get("status") != "REQUEST_SUCCEEDED":
        return None
    results = (data.get("Results") or {}).get("series") or []
    if not results:
        return None

    rows = []
    for point in results[0].get("data", []):
        month = _MONTHS.get(point.get("period", ""))
        if month is None:
            continue  # skip annual (M13) rows
        try:
            value = float(point["value"])
        except (KeyError, TypeError, ValueError):
            continue
        rows.append((pd.Timestamp(int(point["year"]), month, 1), value))
    if not rows:
        return None
    s = pd.Series(dict(rows)).sort_index()
    s.index = pd.DatetimeIndex(s.index)
    return s


def county_fips_from_geoid(county_geoid: str) -> tuple[str, str] | None:
    """Split a Census county GEOID ('05000US48453') into state and county FIPS."""
    if not county_geoid or "US" not in county_geoid:
        return None
    code = county_geoid.split("US", 1)[1]
    if len(code) != 5 or not code.isdigit():
        return None
    return code[:2], code[2:]
