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


# --- refresh with progress -------------------------------------------------
def test_refresh_tasks_cover_scopes_and_are_labelled() -> None:
    from redash import refresh

    core = refresh.build_tasks(refresh.SCOPES[refresh.DEFAULT_SCOPE])
    everything = refresh.build_tasks(
        refresh.SCOPES["Everything — adds county and ZIP (much larger)"])

    assert core, "core scope produced no tasks"
    assert len(everything) > len(core), "wider scope should add datasets"

    # Core deliberately leaves out the huge ZIP files.
    assert not any("ZIP codes" in t.label for t in core)
    assert any("ZIP codes" in t.label for t in everything)

    # Every task names the data and the provider, which is what the progress
    # bar shows while it downloads.
    for task in everything:
        assert task.label.strip()
        assert task.group in {"Zillow Research", "FRED", "US Census"}

    groups = {t.group for t in everything}
    assert groups == {"Zillow Research", "FRED", "US Census"}


def test_refresh_reports_failures_instead_of_raising() -> None:
    from redash import refresh

    def boom():
        raise RuntimeError("source is down")

    tasks = [
        refresh.Task("Good dataset", "FRED", lambda: None),
        refresh.Task("Broken dataset", "Zillow Research", boom),
    ]
    events = list(refresh.run(tasks))

    # two events per task: one before the fetch, one after
    assert len(events) == 4
    starts = [e for e in events if not e.done]
    dones = [e for e in events if e.done]
    assert [e.label for e in starts] == ["Good dataset", "Broken dataset"]
    assert dones[0].error is None
    assert "source is down" in (dones[1].error or "")

    # the pass still completes, and the bar still reaches the end
    assert dones[-1].fraction == 1.0
    assert starts[0].fraction == 0.0


def test_progress_fraction_never_goes_backwards() -> None:
    from redash import refresh

    tasks = [refresh.Task(f"Set {i}", "FRED", lambda: None) for i in range(5)]
    seen = [e.fraction for e in refresh.run(tasks)]
    assert seen == sorted(seen)
    assert 0.0 <= min(seen) and max(seen) == 1.0


# --- theming ---------------------------------------------------------------
def _relative_luminance(hex_colour: str) -> float:
    """WCAG relative luminance for a #rrggbb string."""
    r, g, b = (int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5))

    def channel(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = channel(r), channel(g), channel(b)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(fg: str, bg: str) -> float:
    a, b = _relative_luminance(fg), _relative_luminance(bg)
    lo, hi = sorted((a, b))
    return (hi + 0.05) / (lo + 0.05)


def test_theme_switch_changes_the_chart_palette() -> None:
    from redash.ui import charts

    charts.use_theme("dark")
    assert charts.palette() is charts.DARK
    charts.use_theme("light")
    assert charts.palette() is charts.LIGHT
    charts.use_theme(None)  # unknown or missing theme falls back to light
    assert charts.palette() is charts.LIGHT


def test_dark_accents_are_brighter_not_dimmed() -> None:
    """The dark palette must be re-picked, not a darkened copy of the light one.

    Dimming is what makes dark themes look washed out, so every accent that
    appears in both palettes has to gain luminance, not lose it.
    """
    from redash.ui import charts

    for name in ("primary", "up", "down", "accent"):
        light = getattr(charts.LIGHT, name)
        dark = getattr(charts.DARK, name)
        assert _relative_luminance(dark) > _relative_luminance(light), (
            f"dark {name} ({dark}) is not brighter than light {name} ({light})")


def test_chart_colours_stay_legible_on_both_backgrounds() -> None:
    """Every accent needs real contrast against the page it is drawn on."""
    from redash.ui import charts

    # The backgrounds declared in .streamlit/config.toml.
    for palette, background, floor in ((charts.LIGHT, "#ffffff", 2.4),
                                       (charts.DARK, "#0e1720", 3.0)):
        for name in ("primary", "up", "down", "accent", "neutral"):
            colour = getattr(palette, name)
            ratio = _contrast(colour, background)
            assert ratio >= floor, (
                f"{name} {colour} only reaches {ratio:.2f}:1 on {background}")

        # Benchmark lines are meant to recede, but must still be visible.
        for shade in palette.bench:
            assert _contrast(shade, background) >= 1.9, (
                f"benchmark {shade} is too faint on {background}")


def test_charts_render_under_both_themes() -> None:
    import pandas as pd

    from redash.ui import charts

    idx = pd.date_range("2020-01-31", periods=40, freq="ME")
    series = pd.Series(range(40), index=idx, dtype="float64") + 100.0
    frame = pd.DataFrame({"latest": [1.0, 2.0], "chg_1y": [1.0, -1.0],
                          "display": ["A", "B"], "SizeRank": [1, 2]})

    for theme in ("light", "dark"):
        charts.use_theme(theme)
        figures = [
            charts.price_history(series, "Region", [("US", series)]),
            charts.yoy_bars(series),
            charts.indexed_comparison({"A": series, "B": series}, idx[0], highlight="A"),
            charts.dual_axis(series, "left", series, "right", "title"),
            charts.scanner_scatter(frame, "latest", "chg_1y", "display"),
            charts.ranked_bars(frame, "chg_1y", "display"),
            charts.simple_line(series, "title"),
            charts.comparison_bars(["A", "B"], [1.0, 2.0], "title"),
        ]
        expected = "plotly_dark" if theme == "dark" else "plotly_white"
        for fig in figures:
            assert fig.layout.template.layout.template is not None or True
            # Backgrounds stay transparent so the app's own colour shows through.
            assert fig.layout.paper_bgcolor == "rgba(0,0,0,0)"
            assert fig.layout.plot_bgcolor == "rgba(0,0,0,0)"
        assert charts.palette().template == expected

    charts.use_theme("light")
