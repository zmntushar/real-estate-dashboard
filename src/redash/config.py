"""Central configuration: data source URLs, metric registry, and app constants.

Every source listed here is free and open. Only the FBI crime module needs a
(free) api.data.gov key; everything else is fully keyless.
"""
from __future__ import annotations

from pathlib import Path

APP_TITLE = "US Real Estate Market Dashboard"
APP_ICON = "🏙️"

ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = ROOT / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# How long a downloaded file stays fresh on disk. Zillow publishes monthly.
CACHE_TTL_HOURS = 24
REQUEST_TIMEOUT = 45
# FRED sits behind a CDN that tarpits both unrecognised and browser-like user
# agents; Census Reporter rejects the bare python-requests default. A curl-style
# token that still names this app is the one form every source accepts.
USER_AGENT = "curl/8.4.0 (real-estate-dashboard)"

# --------------------------------------------------------------------------
# Zillow Research public CSVs  (https://www.zillow.com/research/data/)
# --------------------------------------------------------------------------
ZILLOW_BASE = "https://files.zillowstatic.com/research/public_csvs"

# metric key -> (folder, filename template per geo level)
# `{g}` is substituted with Zip / City / Metro / State / County.
ZILLOW_FILES: dict[str, dict] = {
    "zhvi": {
        "folder": "zhvi",
        "file": "{g}_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv",
        "levels": ["Zip", "City", "County", "Metro", "State"],
        "label": "Typical home value (ZHVI)",
        "unit": "usd",
    },
    "zori": {
        "folder": "zori",
        "file": "{g}_zori_uc_sfrcondomfr_sm_month.csv",
        "levels": ["Zip", "City", "County", "Metro"],
        "label": "Typical asking rent (ZORI)",
        "unit": "usd",
    },
    "median_sale_price": {
        "folder": "median_sale_price",
        "file": "{g}_median_sale_price_uc_sfrcondo_sm_month.csv",
        "levels": ["Zip", "City", "County", "Metro", "State"],
        "label": "Median sale price",
        "unit": "usd",
    },
    "inventory": {
        "folder": "invt_fs",
        "file": "{g}_invt_fs_uc_sfrcondo_sm_month.csv",
        "levels": ["City", "County", "Metro", "State"],
        "label": "Homes for sale (inventory)",
        "unit": "count",
    },
    "new_listings": {
        "folder": "new_listings",
        "file": "{g}_new_listings_uc_sfrcondo_sm_month.csv",
        "levels": ["City", "County", "Metro", "State"],
        "label": "New listings",
        "unit": "count",
    },
    "days_to_pending": {
        "folder": "mean_doz_pending",
        "file": "{g}_mean_doz_pending_uc_sfrcondo_sm_month.csv",
        "levels": ["City", "County", "Metro", "State"],
        "label": "Mean days to pending",
        "unit": "days",
    },
    "price_cuts": {
        "folder": "perc_listings_price_cut",
        "file": "{g}_perc_listings_price_cut_uc_sfrcondo_sm_month.csv",
        "levels": ["City", "County", "Metro", "State"],
        "label": "Share of listings with a price cut",
        "unit": "pct_frac",
    },
    "sales_count": {
        "folder": "sales_count_now",
        "file": "{g}_sales_count_now_uc_sfrcondo_month.csv",
        "levels": ["Metro"],
        "label": "Home sales (count)",
        "unit": "count",
    },
}

# Some metrics use the seasonally adjusted "sm_sa_month" suffix at certain levels.
ZILLOW_SA_OVERRIDES = {
    ("median_sale_price", "Metro"): "Metro_median_sale_price_uc_sfrcondo_sm_sa_month.csv",
    ("median_sale_price", "City"): "City_median_sale_price_uc_sfrcondo_sm_sa_month.csv",
    ("median_sale_price", "State"): "State_median_sale_price_uc_sfrcondo_sm_sa_month.csv",
    ("zori", "Zip"): "Zip_zori_uc_sfrcondomfr_sm_month.csv",
}

GEO_LEVELS = ["Zip", "City", "County", "Metro", "State"]
GEO_LABEL = {
    "Zip": "ZIP code",
    "City": "City",
    "County": "County",
    "Metro": "Metro area",
    "State": "State",
}

# --------------------------------------------------------------------------
# FRED — keyless CSV download endpoint
# --------------------------------------------------------------------------
FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"

FRED_SERIES = {
    # series id: (label, unit, frequency group)
    "MORTGAGE30US": ("30-year fixed mortgage rate", "%", "weekly"),
    "CSUSHPINSA": ("Case-Shiller US National Home Price Index", "index", "monthly"),
    "HOUST": ("Housing starts (thousands, SAAR)", "count", "monthly"),
    "MSACSR": ("Months' supply of new houses", "months", "monthly"),
    "UNRATE": ("US unemployment rate", "%", "monthly"),
    "FIXHAI": ("Housing affordability index (composite)", "index", "monthly"),
    "MSPUS": ("Median sales price of houses sold (US)", "usd", "quarterly"),
    "RRVRUSQ156N": ("Rental vacancy rate", "%", "quarterly"),
}

# FRED returns a plain CSV when every requested series shares a frequency, and a
# ZIP archive when they do not - so we batch one request per frequency group.
FRED_GROUPS: dict[str, list[str]] = {}
for _sid, (_lbl, _unit, _freq) in FRED_SERIES.items():
    FRED_GROUPS.setdefault(_freq, []).append(_sid)

# --------------------------------------------------------------------------
# Census — ACS 5-year via the keyless Census Reporter mirror
# --------------------------------------------------------------------------
CENSUS_REPORTER = "https://api.censusreporter.org/1.0"
CENSUS_PLACE_CODES = (
    "https://www2.census.gov/geo/docs/reference/codes2020/national_place2020.txt"
)
CENSUS_COUNTY_CODES = (
    "https://www2.census.gov/geo/docs/reference/codes2020/national_county2020.txt"
)

# ACS tables pulled for the livability panel.
ACS_TABLES = [
    "B01003",  # total population
    "B01002",  # median age
    "B19013",  # median household income
    "B19301",  # per capita income
    "B15003",  # educational attainment (25+)
    "B17001",  # poverty status
    "B25077",  # median home value (owner-occupied)
    "B25064",  # median gross rent
    "B25003",  # tenure (owner vs renter)
    "B25004",  # vacancy status
    "B08303",  # travel time to work
    "B23025",  # employment status
]

# --------------------------------------------------------------------------
# BLS — keyless v1 timeseries API (county unemployment)
# --------------------------------------------------------------------------
BLS_V1 = "https://api.bls.gov/publicAPI/v1/timeseries/data/"

# --------------------------------------------------------------------------
# FBI Crime Data Explorer (optional; free key from api.data.gov)
# --------------------------------------------------------------------------
FBI_CDE = "https://api.usa.gov/crime/fbi/cde"

DISCLAIMER = (
    "Data is sourced from public, free datasets: Zillow Research, the US Census "
    "Bureau (ACS 5-year), FRED (St. Louis Fed), and the Bureau of Labor Statistics. "
    "Figures are indicative market statistics, not an appraisal or investment advice."
)

# Zillow's State files use full names while ZIP/City rows carry abbreviations.
STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii",
    "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming", "PR": "Puerto Rico",
}
