"""Crime rates from the FBI Crime Data Explorer.

This is the one source that needs a key, and it is free: request one at
https://api.data.gov/signup/ and paste it into the sidebar, or set it in
.streamlit/secrets.toml as FBI_API_KEY. Without a key the app hides the crime
panel rather than failing.

The summarized endpoint returns monthly rates per 100,000 people, keyed by
"MM-YYYY", under scope labels of the form "<area> <measure>":

    offenses.rates = {
        "Texas Offenses":          {"01-2015": 32.13, ...},
        "Texas Clearances":        {...},
        "United States Offenses":  {...},
        "United States Clearances":{...},
    }

Note the `from` and `to` parameters are MM-YYYY, not bare years - passing a year
returns HTTP 400.
"""
from __future__ import annotations

import datetime as _dt

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

NATION = "United States"
OFFENCES_MEASURE = "Offenses"


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


def _split_scope(scope: str) -> tuple[str, str]:
    """"Texas Offenses" -> ("Texas", "Offenses")."""
    for measure in ("Offenses", "Clearances"):
        suffix = f" {measure}"
        if scope.endswith(suffix):
            return scope[: -len(suffix)].strip(), measure
    return scope.strip(), ""


@st.cache_data(ttl=60 * 60 * 24 * 7, show_spinner=False)
def state_rates(state_abbr: str, offense: str, key: str,
                years: int = 10) -> pd.DataFrame | None:
    """Monthly offence rates per 100k for a state and the nation.

    Returns tidy rows of (date, rate, area, measure), or None if the API has
    nothing for this state and offence.
    """
    today = _dt.date.today()
    params = {
        "from": f"01-{today.year - years}",
        "to": f"12-{today.year}",
        "API_KEY": key,
    }
    url = f"{FBI_CDE}/summarized/state/{state_abbr}/{offense}"
    try:
        data = cached_json(url, ttl_hours=24 * 30, params=params,
                           label=f"FBI {offense} for {state_abbr}")
    except SourceUnavailable:
        return None

    offenses = (data or {}).get("offenses")
    rates = offenses.get("rates") if isinstance(offenses, dict) else None
    if not isinstance(rates, dict) or not rates:
        return None

    rows: list[dict] = []
    for scope, by_month in rates.items():
        if not isinstance(by_month, dict):
            continue
        area, measure = _split_scope(str(scope))
        for month, value in by_month.items():
            when = pd.to_datetime(month, format="%m-%Y", errors="coerce")
            if pd.isna(when):
                continue
            try:
                rate = float(value)
            except (TypeError, ValueError):
                continue
            rows.append({"date": when, "rate": rate,
                         "area": area, "measure": measure})

    if not rows:
        return None
    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)


def areas(df: pd.DataFrame) -> tuple[str | None, str | None]:
    """The state area label and the national one, as the API spelled them."""
    names = list(dict.fromkeys(df["area"].tolist()))
    state = next((n for n in names if n != NATION), None)
    nation = NATION if NATION in names else None
    return state, nation


def trailing_12m(df: pd.DataFrame, area: str,
                 measure: str = OFFENCES_MEASURE) -> pd.Series | None:
    """Rolling 12-month offence rate per 100k for one area.

    The API reports a rate for each individual month, which is both seasonal
    and an order of magnitude below the annual figures people recognise.
    Summing a trailing year turns it into the familiar "offences per 100,000
    residents per year" while staying current.
    """
    subset = df[(df["area"] == area) & (df["measure"] == measure)]
    if subset.empty:
        return None
    series = subset.set_index("date")["rate"].astype("float64").sort_index()
    series = series[~series.index.duplicated(keep="last")]
    if len(series) < 12:
        return None
    return series.rolling(12).sum().dropna()
