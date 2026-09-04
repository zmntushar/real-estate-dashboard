"""Display formatting helpers shared across panels."""
from __future__ import annotations

import math
from datetime import datetime

import pandas as pd


def _bad(v) -> bool:
    return v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v)))


def usd(v, decimals: int = 0) -> str:
    if _bad(v):
        return "—"
    return f"${v:,.{decimals}f}"


def usd_compact(v) -> str:
    if _bad(v):
        return "—"
    v = float(v)
    for cutoff, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(v) >= cutoff:
            return f"${v / cutoff:.1f}{suffix}"
    return f"${v:,.0f}"


def pct(v, decimals: int = 1, signed: bool = False) -> str:
    if _bad(v):
        return "—"
    return f"{v:+.{decimals}f}%" if signed else f"{v:.{decimals}f}%"


def num(v, decimals: int = 0) -> str:
    if _bad(v):
        return "—"
    return f"{v:,.{decimals}f}"


def compact(v) -> str:
    if _bad(v):
        return "—"
    v = float(v)
    for cutoff, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(v) >= cutoff:
            return f"{v / cutoff:.1f}{suffix}"
    return f"{v:,.0f}"


def month(ts) -> str:
    if ts is None or (isinstance(ts, float) and math.isnan(ts)):
        return "—"
    ts = pd.Timestamp(ts)
    return ts.strftime("%b %Y")


def ago(epoch: float | None) -> str:
    if not epoch:
        return "never"
    delta = datetime.now() - datetime.fromtimestamp(epoch)
    mins = int(delta.total_seconds() // 60)
    if mins < 1:
        return "just now"
    if mins < 60:
        return f"{mins} min ago"
    hours = mins // 60
    if hours < 24:
        return f"{hours}h ago"
    return f"{hours // 24}d ago"


def format_metric(value, unit: str) -> str:
    """Format a value according to its declared unit."""
    if unit == "usd":
        return usd(value)
    if unit == "pct":
        return pct(value)
    if unit == "pct_frac":
        return pct(value * 100.0 if not _bad(value) else value)
    if unit == "days":
        return f"{value:,.0f} days" if not _bad(value) else "—"
    if unit == "months":
        return f"{value:,.1f} mo" if not _bad(value) else "—"
    if unit in ("count", "index"):
        return num(value, 0 if unit == "count" else 1)
    return num(value, 1)
