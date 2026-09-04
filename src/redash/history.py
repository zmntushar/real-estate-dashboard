"""Recent-search history, persisted to disk.

Kept in a small JSON file next to the cache so it survives restarts - session
state alone would forget every search the moment the app is closed.

Entries are recorded only once a search actually resolves to a place, and are
stored in canonical form ("Austin, TX" rather than whatever was typed), so
replaying one lands on the same region without going through disambiguation
again.
"""
from __future__ import annotations

import datetime as _dt
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .config import ROOT

HISTORY_PATH = ROOT / "data" / "search_history.json"
MAX_ENTRIES = 12


@dataclass(frozen=True)
class Entry:
    query: str   # canonical text that re-resolves to this place
    label: str   # what to show in the sidebar
    level: str   # Zip / City / County / Metro / State
    at: str      # ISO timestamp of the most recent visit

    @property
    def key(self) -> str:
        return self.query.strip().casefold()


def canonical(region) -> Entry:
    """Turn a resolved Region into the entry we store.

    A bare city name can match several states, so cities are stored with their
    state attached - that is what makes a replayed search unambiguous.
    """
    name = str(region.name)
    if region.level == "City" and region.state:
        query = f"{name}, {region.state}"
    else:
        query = name
    return Entry(
        query=query,
        label=str(region.label or query),
        level=str(region.level),
        at=_dt.datetime.now().isoformat(timespec="seconds"),
    )


def remember(entries: list[Entry], entry: Entry,
             limit: int = MAX_ENTRIES) -> list[Entry]:
    """Move-to-front, de-duplicated, capped. Pure - does not touch disk."""
    kept = [e for e in entries if e.key != entry.key]
    return [entry, *kept][:limit]


def load(path: Path | None = None) -> list[Entry]:
    path = path or HISTORY_PATH
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []  # unreadable or corrupt: start clean rather than crash
    if not isinstance(raw, list):
        return []

    out: list[Entry] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        query = str(item.get("query", "")).strip()
        if not query:
            continue
        out.append(Entry(
            query=query,
            label=str(item.get("label") or query),
            level=str(item.get("level", "")),
            at=str(item.get("at", "")),
        ))
    return out[:MAX_ENTRIES]


def save(entries: list[Entry], path: Path | None = None) -> None:
    path = path or HISTORY_PATH
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps([asdict(e) for e in entries], indent=1),
            encoding="utf-8")
    except OSError:
        pass  # history is a convenience; never break the app over it


def clear(path: Path | None = None) -> None:
    path = path or HISTORY_PATH
    try:
        (path or HISTORY_PATH).unlink(missing_ok=True)
    except OSError:
        pass
