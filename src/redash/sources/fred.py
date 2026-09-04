"""Macro housing indicators from FRED (St. Louis Fed).

Uses the keyless fredgraph.csv endpoint. FRED drops connections under bursty
traffic, so we fetch one bundled request per frequency group (weekly, monthly,
quarterly) instead of one request per series.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from ..cache import SourceUnavailable, cached_csv
from ..config import FRED_CSV, FRED_GROUPS, FRED_SERIES


@st.cache_data(ttl=60 * 60 * 12, show_spinner=False)
def _bundle(freq: str) -> pd.DataFrame:
    """All series sharing one frequency, in a single request."""
    ids = FRED_GROUPS.get(freq, [])
    if not ids:
        return pd.DataFrame()
    try:
        df = cached_csv(FRED_CSV.format(series=",".join(ids)), label=f"FRED {freq} series")
    except SourceUnavailable:
        return pd.DataFrame()
    if df.empty or df.shape[1] < 2:
        return pd.DataFrame()
    df = df.copy()
    df.index = pd.to_datetime(df[df.columns[0]], errors="coerce")
    df = df[df.index.notna()].drop(columns=[df.columns[0]])
    return df.apply(pd.to_numeric, errors="coerce")  # FRED writes "." for gaps


def series(series_id: str) -> pd.Series | None:
    """One FRED series as a date-indexed float Series."""
    meta = FRED_SERIES.get(series_id)
    if meta is None:
        return None
    df = _bundle(meta[2])
    if df.empty or series_id not in df.columns:
        return None
    s = df[series_id].dropna().astype("float64")
    return s if not s.empty else None


def label(series_id: str) -> str:
    return FRED_SERIES.get(series_id, (series_id, "", ""))[0]


def unit(series_id: str) -> str:
    return FRED_SERIES.get(series_id, (series_id, "", ""))[1]


def latest(series_id: str) -> tuple[float, pd.Timestamp] | None:
    s = series(series_id)
    if s is None or s.empty:
        return None
    return float(s.iloc[-1]), s.index[-1]


def mortgage_rate_now(default: float = 6.5) -> float:
    """Current 30-year fixed rate; falls back to a sane default if FRED is down."""
    got = latest("MORTGAGE30US")
    return got[0] if got else default
