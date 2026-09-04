"""Resolve free-text user input to a region across every data source.

A user types "78701", "Austin, TX", or "Boston" and we need to line up the
Zillow region (market data) with a Census GEOID (demographics) and a county
FIPS (labour data). This module owns that reconciliation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd
import streamlit as st

from .config import STATE_NAMES
from .sources import census, zillow

ZIP_RE = re.compile(r"^\s*(\d{5})(?:-\d{4})?\s*$")
STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID",
    "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO",
    "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA",
    "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "PR",
}


@dataclass
class Region:
    """A resolved place, with handles into each data source."""
    level: str                    # Zip | City | County | Metro | State
    region_id: int                # Zillow RegionID
    name: str                     # e.g. "78701" or "Austin"
    label: str                    # display label
    state: str | None = None
    city: str | None = None
    metro: str | None = None
    county: str | None = None
    census_geoid: str | None = None
    parents: dict = field(default_factory=dict)

    @property
    def county_fips(self) -> tuple[str, str] | None:
        node = self.parents.get("county") or {}
        gid = node.get("geoid")
        if not gid or "US" not in gid:
            return None
        code = gid.split("US", 1)[1]
        return (code[:2], code[2:]) if len(code) == 5 and code.isdigit() else None

    @property
    def metro_geoid(self) -> str | None:
        return (self.parents.get("CBSA") or {}).get("geoid")

    @property
    def state_geoid(self) -> str | None:
        return (self.parents.get("state") or {}).get("geoid")


def parse_query(text: str) -> dict:
    """Split raw input into a ZIP, or a place name plus optional state."""
    text = (text or "").strip()
    if not text:
        return {"kind": "empty"}
    m = ZIP_RE.match(text)
    if m:
        return {"kind": "zip", "zip": m.group(1)}

    state = None
    body = text
    if "," in text:
        head, tail = text.rsplit(",", 1)
        tail = tail.strip().upper()
        if tail in STATES:
            body, state = head.strip(), tail
    else:
        parts = text.split()
        if len(parts) > 1 and parts[-1].upper() in STATES:
            body, state = " ".join(parts[:-1]), parts[-1].upper()
    return {"kind": "place", "name": body.strip(), "state": state}


@st.cache_data(ttl=60 * 60 * 12, show_spinner=False)
def search_regions(text: str, limit: int = 25) -> pd.DataFrame:
    """Rank candidate Zillow regions matching the query, biggest first."""
    q = parse_query(text)
    if q["kind"] == "empty":
        return pd.DataFrame()

    frames = []
    if q["kind"] == "zip":
        d = zillow.region_directory("Zip")
        if not d.empty:
            frames.append(d[d["RegionName"] == q["zip"]])
    else:
        name = q["name"].lower().strip()
        state = q.get("state")
        for level in ("City", "Metro", "County", "State"):
            d = zillow.region_directory(level)
            if d.empty:
                continue
            rn = d["RegionName"].astype("string").str.lower()
            # Metro names look like "Austin-Round Rock, TX"; match the leading city.
            hit = d[rn.str.split(",").str[0].str.split("-").str[0].str.strip().eq(name)
                    | rn.eq(name)]
            if state and "State" in d.columns:
                narrowed = hit[hit["State"].astype("string").str.upper() == state]
                if not narrowed.empty:
                    hit = narrowed
            elif state and level == "Metro":
                # rn is indexed on the whole directory; align it to the subset.
                narrowed = hit[rn.loc[hit.index].str.upper().str.endswith(state)]
                if not narrowed.empty:
                    hit = narrowed
            if not hit.empty:
                frames.append(hit)

    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    # Prefer specific geographies, then population size.
    order = {"Zip": 0, "City": 1, "Metro": 2, "County": 3, "State": 4}
    out["_rank"] = out["level"].map(order).fillna(9)
    return (out.sort_values(["_rank", "SizeRank"])
               .drop(columns="_rank")
               .head(limit)
               .reset_index(drop=True))


def _census_geoid_for(row: pd.Series) -> str | None:
    """Best-effort Census GEOID for a Zillow region row."""
    level = row["level"]
    if level == "Zip":
        return census.zcta_geoid(str(row["RegionName"]))
    if level == "City":
        state = row.get("State")
        hit = census.find_place(str(row["RegionName"]),
                               str(state) if isinstance(state, str) else None)
        if not hit.empty:
            return str(hit.iloc[0]["geoid"])
    return None


def build_region(row: pd.Series) -> Region:
    """Turn a search result row into a fully resolved Region."""
    def get(col):
        v = row.get(col)
        return None if v is None or (isinstance(v, float) and pd.isna(v)) else (
            str(v) if not isinstance(v, str) else v)

    region = Region(
        level=str(row["level"]),
        region_id=int(row["RegionID"]),
        name=str(row["RegionName"]),
        label=str(row.get("label") or row["RegionName"]),
        state=get("State") or get("StateName"),
        city=get("City"),
        metro=get("Metro"),
        county=get("CountyName"),
    )
    region.census_geoid = _census_geoid_for(row)
    if region.census_geoid:
        region.parents = census.geo_parents(region.census_geoid)
    return region


def short_metro_name(long_name: str | None) -> str | None:
    """Convert a CBSA-style name to Zillow's short metro name.

    ZIP and City rows carry "Austin-Round Rock-Georgetown, TX", while the Metro
    files publish the same market as "Austin, TX".
    """
    if not long_name:
        return None
    head, _, tail = long_name.partition(",")
    lead = head.split("-")[0].strip()
    # Multi-state metros ("Boston-Cambridge-Newton, MA-NH") publish under the
    # first state only ("Boston, MA").
    state = tail.strip().split("-")[0].strip()
    return f"{lead}, {state}" if state else lead


def peer_regions(region: Region) -> list[tuple[str, str, int]]:
    """Larger geographies containing this one, for benchmark comparison.

    Returns (level, display name, Zillow RegionID) tuples.
    """
    out: list[tuple[str, str, int]] = []
    seen: set[tuple[str, int]] = set()

    def add(level: str, name: str | None):
        if not name:
            return
        d = zillow.region_directory(level)
        if d.empty:
            return
        hit = d[d["RegionName"].astype("string").str.lower() == name.lower()]
        if hit.empty:
            return
        row = hit.iloc[0]
        key = (level, int(row["RegionID"]))
        if key in seen:
            return
        seen.add(key)
        name_out = str(row["RegionName"])
        if level == "Metro" and name_out != "United States":
            name_out = f"{name_out} metro"
        out.append((level, name_out, int(row["RegionID"])))

    if region.level in ("Zip", "City", "County"):
        add("Metro", short_metro_name(region.metro))
    if region.level in ("Zip", "City", "County", "Metro"):
        abbr = (region.state or "").upper()
        add("State", STATE_NAMES.get(abbr, region.state))
    add("Metro", "United States")  # Zillow publishes the national line at metro level
    return [p for p in out if p[2] != region.region_id]
