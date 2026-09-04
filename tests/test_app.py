"""Integration checks.

`AppTest` runs the real Streamlit script in-process, so these catch exceptions
in any panel across a range of geographies — including places with sparse data,
which is where the graceful-degradation paths matter.

Run with:  .venv/Scripts/python.exe -m pytest tests -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

APP = str(ROOT / "app.py")
TIMEOUT = 300

# A ZIP, big cities, a cooling Sun Belt metro, and an expensive small ZIP.
QUERIES = ["Austin, TX", "02138", "Detroit, MI", "Boise, ID", "90210"]


def _run(query: str) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=TIMEOUT)
    at.session_state["query"] = query
    at.run()
    return at


@pytest.mark.parametrize("query", QUERIES)
def test_app_renders_without_exception(query: str) -> None:
    at = _run(query)
    assert not at.exception, [e.value for e in at.exception]


def test_unknown_place_warns_instead_of_crashing() -> None:
    at = _run("Nowhereville, ZZ")
    assert not at.exception
    assert any("No published market" in w.value for w in at.warning)


def test_empty_query_is_handled() -> None:
    at = _run("")
    assert not at.exception


def test_headline_metrics_present() -> None:
    at = _run("Austin, TX")
    labels = [m.label for m in at.metric]
    for expected in ("Typical home value", "Median sale price", "Typical rent"):
        assert expected in labels, f"missing KPI: {expected}"


# --- data layer -----------------------------------------------------------
def test_zillow_snapshot_shapes() -> None:
    from redash.sources import zillow

    snap = zillow.latest_snapshot("zhvi", "Metro")
    assert not snap.empty
    assert {"latest", "chg_1y", "chg_5y", "as_of"} <= set(snap.columns)
    assert snap["latest"].notna().all()


def test_momentum_is_scored_for_every_region() -> None:
    from redash import analytics
    from redash.sources import zillow

    table = zillow.combined_snapshot("Metro")
    score = analytics.momentum_score(table)
    assert score.notna().all()
    assert score.between(0, 100).all()


def test_geo_resolves_zip_city_and_state() -> None:
    from redash import geo

    zip_hit = geo.build_region(geo.search_regions("02138").iloc[0])
    assert zip_hit.level == "Zip"
    assert zip_hit.county_fips == ("25", "017")
    assert "Boston, MA metro" in [p[1] for p in geo.peer_regions(zip_hit)]

    city = geo.build_region(geo.search_regions("Austin, TX").iloc[0])
    assert city.census_geoid == "16000US4805000"


def test_affordability_maths() -> None:
    from redash import analytics

    # $500k home, 20% down, 6% for 30 years -> ~$2,398 principal and interest.
    payment = analytics.monthly_payment(400_000, 6.0, 30)
    assert 2_390 < payment < 2_410

    aff = analytics.affordability(500_000, 100_000, 6.0)
    assert aff["monthly_total"] > payment  # escrow is added on top
    assert aff["price_to_income"] == pytest.approx(5.0)


def test_missing_inputs_return_none_not_zero() -> None:
    from redash import analytics

    assert analytics.pct_change_over(None, 12) is None
    assert analytics.gross_rent_yield(None, 2000) is None
    assert analytics.cagr(None, 12) is None
    assert analytics.affordability(None, None, None)["monthly_total"] is None
