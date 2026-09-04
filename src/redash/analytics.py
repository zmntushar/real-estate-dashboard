"""Derived market analytics: growth, affordability, yield, and momentum.

Everything here is computed from the raw public series; nothing is estimated or
imputed. Functions return None rather than guessing when inputs are missing.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MONTHS = {"1m": 1, "3m": 3, "6m": 6, "1y": 12, "3y": 36, "5y": 60, "10y": 120}


def pct_change_over(s: pd.Series | None, months: int) -> float | None:
    """Percentage change over the trailing `months` months of a series."""
    if s is None or len(s) <= months:
        return None
    now, prior = s.iloc[-1], s.iloc[-1 - months]
    if not np.isfinite(now) or not np.isfinite(prior) or prior == 0:
        return None
    return float((now / prior - 1.0) * 100.0)


def cagr(s: pd.Series | None, months: int) -> float | None:
    """Annualised growth rate over a trailing window."""
    if s is None or len(s) <= months or months <= 0:
        return None
    now, prior = s.iloc[-1], s.iloc[-1 - months]
    if not np.isfinite(now) or not np.isfinite(prior) or prior <= 0 or now <= 0:
        return None
    years = months / 12.0
    return float(((now / prior) ** (1.0 / years) - 1.0) * 100.0)


def drawdown_from_peak(s: pd.Series | None) -> tuple[float, pd.Timestamp] | None:
    """How far below its all-time peak the series currently sits."""
    if s is None or s.empty:
        return None
    peak_idx = s.idxmax()
    peak = float(s.loc[peak_idx])
    if peak <= 0:
        return None
    return float((s.iloc[-1] / peak - 1.0) * 100.0), peak_idx


def growth_table(s: pd.Series | None) -> pd.DataFrame:
    """Standard trailing-return table for a price series."""
    rows = []
    for label, months in MONTHS.items():
        chg = pct_change_over(s, months)
        rows.append({
            "Horizon": label.upper(),
            "Change %": chg,
            "Annualised %": cagr(s, months) if months >= 12 else None,
        })
    return pd.DataFrame(rows)


def monthly_payment(principal: float, annual_rate_pct: float, years: int = 30) -> float | None:
    """Level-payment mortgage instalment (principal and interest only)."""
    if principal is None or principal <= 0 or annual_rate_pct is None:
        return None
    r = annual_rate_pct / 100.0 / 12.0
    n = years * 12
    if r <= 0:
        return principal / n
    return float(principal * r / (1.0 - (1.0 + r) ** -n))


def affordability(home_value: float | None, household_income: float | None,
                  mortgage_rate: float | None, down_payment_pct: float = 20.0,
                  tax_ins_pct: float = 1.5) -> dict:
    """Monthly cost and income share for a typical home at current rates.

    `tax_ins_pct` approximates property tax plus insurance as an annual
    percentage of value - a national rule of thumb, not a local quote.
    """
    out: dict = {"monthly_pi": None, "monthly_total": None,
                 "income_share_pct": None, "price_to_income": None,
                 "income_needed": None}
    if not home_value or home_value <= 0:
        return out

    principal = home_value * (1.0 - down_payment_pct / 100.0)
    pi = monthly_payment(principal, mortgage_rate or 0.0)
    if pi is None:
        return out
    escrow = home_value * (tax_ins_pct / 100.0) / 12.0
    total = pi + escrow
    out["monthly_pi"] = pi
    out["monthly_total"] = total
    # Lenders commonly size housing cost at ~28% of gross income.
    out["income_needed"] = total * 12.0 / 0.28
    if household_income and household_income > 0:
        out["income_share_pct"] = total * 12.0 / household_income * 100.0
        out["price_to_income"] = home_value / household_income
    return out


def gross_rent_yield(home_value: float | None, monthly_rent: float | None) -> float | None:
    """Annual rent as a percentage of home value (gross, before costs)."""
    if not home_value or not monthly_rent or home_value <= 0:
        return None
    return float(monthly_rent * 12.0 / home_value * 100.0)


def _z(series: pd.Series) -> pd.Series:
    """Z-score that tolerates all-NaN and zero-variance inputs."""
    v = pd.to_numeric(series, errors="coerce")
    sd = v.std(skipna=True)
    if not np.isfinite(sd) or sd == 0:
        return pd.Series(0.0, index=v.index)
    return (v - v.mean(skipna=True)) / sd


def momentum_score(df: pd.DataFrame) -> pd.Series:
    """Composite 0-100 market-heat score, as a percentile against peers.

    Blends the level and acceleration of price growth with supply-side friction
    (price cuts, time on market). Components are z-scored across the peer set
    and averaged using only the components each row actually has, so a region
    missing one input is still scored rather than dropped. The blend is then
    converted to a percentile: 90 means hotter than 90% of the regions in the
    same table.
    """
    parts: list[tuple[pd.Series, float]] = []

    if "chg_1y" in df:
        parts.append((_z(df["chg_1y"]), 0.35))
    if "chg_3m" in df:
        parts.append((_z(df["chg_3m"]), 0.25))
    if "chg_1y" in df and "chg_3y" in df:
        # Acceleration: the last year against the 3-year annualised pace.
        parts.append((_z(df["chg_1y"] - df["chg_3y"] / 3.0), 0.20))
    if "price_cuts" in df:
        parts.append((-_z(df["price_cuts"]), 0.10))
    if "days_to_pending" in df:
        parts.append((-_z(df["days_to_pending"]), 0.10))

    if not parts:
        return pd.Series(np.nan, index=df.index)

    weighted = pd.DataFrame(0.0, index=df.index, columns=["sum", "weight"])
    for component, weight in parts:
        present = component.notna()
        weighted.loc[present, "sum"] += component[present] * weight
        weighted.loc[present, "weight"] += weight

    blended = weighted["sum"] / weighted["weight"].replace(0.0, np.nan)
    if blended.notna().sum() < 2:
        return pd.Series(np.nan, index=df.index)
    return (blended.rank(pct=True) * 100.0).round(1)


def classify_market(chg_1y: float | None, chg_3m: float | None) -> tuple[str, str]:
    """Plain-language market state from year-over-year and recent momentum."""
    if chg_1y is None or not np.isfinite(chg_1y):
        return "Unknown", "gray"
    if chg_1y >= 8:
        return "Rising fast", "green"
    if chg_1y >= 3:
        return "Rising", "green"
    if chg_1y >= 0:
        if chg_3m is not None and np.isfinite(chg_3m) and chg_3m < 0:
            return "Flattening", "orange"
        return "Flat / slow growth", "orange"
    if chg_1y >= -5:
        return "Cooling", "orange"
    return "Falling", "red"


def yoy_series(s: pd.Series | None) -> pd.Series | None:
    """Year-over-year percentage change through time."""
    if s is None or len(s) < 13:
        return None
    return (s / s.shift(12) - 1.0).dropna() * 100.0


def rebase(s: pd.Series | None, at: pd.Timestamp | None = None) -> pd.Series | None:
    """Index a series to 100 at a chosen date, for like-for-like comparison."""
    if s is None or s.empty:
        return None
    if at is not None:
        s = s[s.index >= at]
        if s.empty:
            return None
    base = s.iloc[0]
    if not np.isfinite(base) or base == 0:
        return None
    return s / base * 100.0
