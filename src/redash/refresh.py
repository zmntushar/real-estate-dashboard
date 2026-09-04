"""Cache warm-up with progress reporting.

The dashboard normally downloads each dataset the first time a panel needs it,
which makes a cold start feel like a series of unexplained pauses. This module
turns that into one explicit pass: a known list of datasets, fetched in order,
each announced by name so the wait is legible.

It deliberately calls the download layer rather than the Streamlit-memoised
loaders, so a full refresh does not hold thirty large DataFrames in memory at
once. Pages repopulate their own caches from the warm files afterwards.
"""
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Callable

from . import cache
from .config import (CENSUS_PLACE_CODES, FRED_CSV, FRED_GROUPS, ZILLOW_FILES)
from .sources import zillow

# How much of the country to pull. ZIP and county files are by far the largest,
# so they are opt-in rather than forced on everyone who clicks refresh.
SCOPES: dict[str, tuple[str, ...]] = {
    "Core markets — metro, state, city": ("Metro", "State", "City"),
    "Everything — adds county and ZIP (much larger)": (
        "Metro", "State", "City", "County", "Zip"),
}
DEFAULT_SCOPE = next(iter(SCOPES))

# Fetch the coarse geographies first so the dashboard becomes usable early.
_LEVEL_ORDER = {"Metro": 0, "State": 1, "City": 2, "County": 3, "Zip": 4}
_LEVEL_PLURAL = {
    "Metro": "metro areas",
    "State": "states",
    "City": "cities",
    "County": "counties",
    "Zip": "ZIP codes",
}


@dataclass(frozen=True)
class Task:
    """One dataset to download."""
    label: str          # human description, shown in the progress bar
    group: str          # which provider it comes from
    fetch: Callable[[], object]


@dataclass(frozen=True)
class Progress:
    """Emitted twice per task: once before the fetch, once after."""
    index: int
    total: int
    label: str
    group: str
    done: bool
    mb: float = 0.0
    error: str | None = None

    @property
    def fraction(self) -> float:
        base = self.index if self.done else self.index - 1
        return min(1.0, max(0.0, base / self.total)) if self.total else 1.0


def _zillow_task(metric: str, level: str) -> Task | None:
    url = zillow.metric_url(metric, level)
    if url is None:
        return None
    spec = ZILLOW_FILES[metric]
    label = f"{spec['label']} — {_LEVEL_PLURAL.get(level, level)}"
    return Task(label=label, group="Zillow Research",
                fetch=lambda: cache.cached_csv(url, ttl_hours=0, label=label))


def build_tasks(levels: tuple[str, ...] = ()) -> list[Task]:
    """Every dataset the app can use at the requested geography levels."""
    wanted = set(levels or SCOPES[DEFAULT_SCOPE])
    tasks: list[Task] = []

    ordered_levels = sorted(wanted, key=lambda lv: _LEVEL_ORDER.get(lv, 99))
    for level in ordered_levels:
        for metric, spec in ZILLOW_FILES.items():
            if level not in spec["levels"]:
                continue
            task = _zillow_task(metric, level)
            if task is not None:
                tasks.append(task)

    for freq, ids in FRED_GROUPS.items():
        url = FRED_CSV.format(series=",".join(ids))
        label = f"Mortgage rates and macro indicators — {freq}"
        tasks.append(Task(label=label, group="FRED",
                          fetch=lambda u=url, l=label: cache.cached_csv(
                              u, ttl_hours=0, label=l)))

    tasks.append(Task(
        label="Census place name index (city lookup)",
        group="US Census",
        fetch=lambda: cache.cached_text(CENSUS_PLACE_CODES, ttl_hours=0,
                                        label="Census place codes")))
    return tasks


def _cache_mb() -> float:
    return cache.cache_stats()["mb"]


def run(tasks: list[Task]) -> Iterator[Progress]:
    """Download each task in turn, yielding progress before and after.

    A failing source yields an error rather than raising, so one dead endpoint
    does not abandon the rest of the refresh.
    """
    total = len(tasks)
    for index, task in enumerate(tasks, start=1):
        yield Progress(index, total, task.label, task.group, done=False)

        before = _cache_mb()
        error: str | None = None
        try:
            task.fetch()
        except Exception as exc:  # noqa: BLE001 - report, never abort the pass
            error = str(exc)
            if len(error) > 180:
                error = error[:177] + "..."

        yield Progress(index, total, task.label, task.group, done=True,
                       mb=max(0.0, _cache_mb() - before), error=error)
