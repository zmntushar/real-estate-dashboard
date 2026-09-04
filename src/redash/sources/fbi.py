"""Crime rates from the FBI Crime Data Explorer.

This is the one source that needs a key, and it is free: request one at
https://api.data.gov/signup/ and paste it into the sidebar, or set it in
.streamlit/secrets.toml as FBI_API_KEY. Without a key the app simply hides the
crime panel rather than failing.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from ..cache import SourceUnavailable, cached_json
from ..config import FBI_CDE

OFFENSES = {
    "violent-crime": "Violent crime",
    "homicide": "Homicide",
    "robbery": "Robbery",
    "aggravated-assault": "Aggravated assault",
    "burglary": "Burglary",
    "larceny": "Larceny / theft",
    "motor-vehicle-theft": "Motor vehicle theft",
    "property-crime": "Property crime",
}


def api_key() -> str | None:
    """Key from the sidebar, else Streamlit secrets, else None."""
    key = st.session_state.get("fbi_api_key")
    if key:
        return key.strip()
    try:
        secret = st.secrets.get("FBI_API_KEY")  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001 - no secrets file configured
        return None
    return str(secret).strip() if secret else None


@st.cache_data(ttl=60 * 60 * 24 * 7, show_spinner=False)
def state_rates(state_abbr: str, offense: str, key: str,
                from_year: int = 2015, to_year: int = 2024) -> pd.DataFrame | None:
    """Offense rate per 100k for a state, by year."""
    url = f"{FBI_CDE}/summarized/state/{state_abbr}/{offense}"
    params = {"from": str(from_year), "to": str(to_year), "API_KEY": key}
    try:
        data = cached_json(url, ttl_hours=24 * 30, params=params,
                           label=f"FBI {offense} for {state_abbr}")
    except SourceUnavailable:
        return None

    offenses = (data or {}).get("offenses", {})
    rates = offenses.get("rates", {}) if isinstance(offenses, dict) else {}
    if not rates:
        return None

    frames = []
    for scope, by_year in rates.items():
        if not isinstance(by_year, dict):
            continue
        rows = []
        for year, value in by_year.items():
            try:
                rows.append((int(year), float(value)))
            except (TypeError, ValueError):
                continue
        if rows:
            frames.append(pd.DataFrame(rows, columns=["year", "rate"]).assign(scope=scope))
    if not frames:
        return None
    return pd.concat(frames, ignore_index=True).sort_values(["scope", "year"])
