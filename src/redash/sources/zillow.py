"""Zillow Research public CSVs — the market backbone of the dashboard.

Every file is a wide table: identifier columns followed by one column per month.
We normalise that into (region metadata, monthly series) pairs.
"""
from __future__ import annotations

import re

import pandas as pd
import streamlit as st

from ..cache import SourceUnavailable, cached_csv
from ..config import ZILLOW_BASE, ZILLOW_FILES, ZILLOW_SA_OVERRIDES

ID_COLS = ["RegionID", "SizeRank", "RegionName", "RegionType", "StateName",
           "State", "City", "Metro", "CountyName"]
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def metric_url(metric: str, level: str) -> str | None:
    spec = ZILLOW_FILES.get(metric)
    if spec is None or level not in spec["levels"]:
        return None
    fname = ZILLOW_SA_OVERRIDES.get((metric, level)) or spec["file"].format(g=level)
    return f"{ZILLOW_BASE}/{spec['folder']}/{fname}"


def date_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if _DATE_RE.match(str(c))]


@st.cache_data(ttl=60 * 60 * 12, show_spinner=False)
def load_metric(metric: str, level: str) -> pd.DataFrame | None:
    """Load one Zillow metric at one geography level. None if unpublished."""
    url = metric_url(metric, level)
    if url is None:
        return None
    try:
        df = cached_csv(url, label=f"Zillow {metric} ({level})")
    except SourceUnavailable:
        return None
    if "RegionName" not in df.columns:
        return None
    df["RegionName"] = df["RegionName"].astype("string")
    if level == "Zip":
        # ZIPs arrive as integers in some vintages; normalise to 5-digit strings.
        df["RegionName"] = df["RegionName"].str.replace(r"\.0$", "", regex=True).str.zfill(5)
    return df


@st.cache_data(ttl=60 * 60 * 12, show_spinner=False)
def region_directory(level: str) -> pd.DataFrame:
    """Searchable index of every region published at a level (from ZHVI)."""
    df = load_metric("zhvi", level)
    if df is None or df.empty:
        return pd.DataFrame(columns=["RegionID", "RegionName", "State", "label", "SizeRank"])

    keep = [c for c in ID_COLS if c in df.columns]
    out = df[keep].copy()
    out["level"] = level

    if level == "Zip":
        out["label"] = (out["RegionName"] + " — " + out.get("City", "").fillna("")
                        + ", " + out.get("State", "").fillna(""))
    elif level == "City":
        out["label"] = out["RegionName"] + ", " + out.get("State", "").fillna("")
    elif level == "County":
        state = out["StateName"] if "StateName" in out else out.get("State", "")
        out["label"] = out["RegionName"] + ", " + pd.Series(state, index=out.index).fillna("")
    else:  # Metro, State
        out["label"] = out["RegionName"]

    out["label"] = out["label"].astype("string").str.replace(r",\s*$", "", regex=True)
    return out.sort_values("SizeRank").reset_index(drop=True)


def series_for(metric: str, level: str, region_id) -> pd.Series | None:
    """Monthly time series for one region, indexed by month-end timestamps."""
    df = load_metric(metric, level)
    if df is None or df.empty:
        return None
    row = df.loc[df["RegionID"] == region_id]
    if row.empty:
        return None
    cols = date_columns(df)
    if not cols:
        return None
    values = pd.to_numeric(row.iloc[0][cols], errors="coerce")
    s = pd.Series(values.to_numpy(dtype="float64"), index=pd.to_datetime(cols))
    s = s.dropna()
    return s if not s.empty else None


def panel_for(level: str, region_id, metrics: list[str]) -> dict[str, pd.Series]:
    """All requested metrics for one region, skipping unavailable ones."""
    out: dict[str, pd.Series] = {}
    for m in metrics:
        s = series_for(m, level, region_id)
        if s is not None:
            out[m] = s
    return out


@st.cache_data(ttl=60 * 60 * 12, show_spinner=False)
def latest_snapshot(metric: str, level: str) -> pd.DataFrame:
    """Latest value plus trailing changes for every region at a level.

    Powers the national scanner. Returns one row per region with the most
    recent observation and 1m / 3m / 1y / 3y / 5y percentage changes.
    """
    df = load_metric(metric, level)
    if df is None or df.empty:
        return pd.DataFrame()

    cols = date_columns(df)
    if not cols:
        return pd.DataFrame()
    cols = sorted(cols)
    vals = df[cols].apply(pd.to_numeric, errors="coerce")

    keep = [c for c in ID_COLS if c in df.columns]
    out = df[keep].copy()
    out["level"] = level

    last_idx = vals.notna().to_numpy().cumsum(axis=1).argmax(axis=1)
    arr = vals.to_numpy()
    n = len(cols)
    rows = range(len(out))

    def at(offset_months: int):
        """Value `offset_months` before each row's own last observation."""
        idx = last_idx - offset_months
        valid = idx >= 0
        picked = [arr[i, idx[i]] if valid[i] else float("nan") for i in rows]
        return pd.Series(picked, index=out.index, dtype="float64")

    latest = pd.Series([arr[i, last_idx[i]] for i in rows], index=out.index, dtype="float64")
    out["latest"] = latest
    out["as_of"] = [cols[last_idx[i]] for i in rows]

    for label, months in (("chg_1m", 1), ("chg_3m", 3), ("chg_1y", 12),
                          ("chg_3y", 36), ("chg_5y", 60)):
        prior = at(months)
        out[label] = (latest / prior - 1.0) * 100.0

    out = out[latest.notna()].copy()
    if n:
        out.attrs["as_of_max"] = cols[-1]
    return out.reset_index(drop=True)


def available_metrics(level: str) -> list[str]:
    return [m for m, spec in ZILLOW_FILES.items() if level in spec["levels"]]


@st.cache_data(ttl=60 * 60 * 12, show_spinner=False)
def combined_snapshot(level: str, extra_metrics: tuple[str, ...] = ("price_cuts", "days_to_pending",
                                                                   "inventory", "zori")) -> pd.DataFrame:
    """ZHVI snapshot for every region, joined with current supply-side metrics.

    This is the table behind the national scanner: one row per region carrying
    price level, trailing changes, and the market-friction indicators that feed
    the momentum score.
    """
    base = latest_snapshot("zhvi", level)
    if base.empty:
        return base
    out = base.copy()

    for metric in extra_metrics:
        if level not in ZILLOW_FILES.get(metric, {}).get("levels", []):
            continue
        snap = latest_snapshot(metric, level)
        if snap.empty:
            continue
        cols = {"latest": metric, "chg_1y": f"{metric}_chg_1y"}
        piece = snap[["RegionID", "latest", "chg_1y"]].rename(columns=cols)
        out = out.merge(piece, on="RegionID", how="left")

    if "zori" in out.columns:
        # Gross rent yield: annual asking rent over typical home value.
        out["rent_yield"] = out["zori"] * 12.0 / out["latest"].replace(0, pd.NA) * 100.0
    return out
