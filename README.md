# US Real Estate Market Dashboard

A Streamlit dashboard for US housing markets. Type a city or ZIP code and get
the market picture — prices, rents, supply, momentum, affordability — plus the
income, education and labour indicators behind why people move between places.

Every data source is free and open. Nothing here needs a paid API, and only the
optional crime panel needs a key at all.

![tabs: Market overview · National scanner · Livability · Compare · Macro · Sources](https://img.shields.io/badge/streamlit-app-0e9aa7)

## Quick start

Double-click **`install.bat`**, then double-click **`start_app.bat`**. That is
the whole setup — the first script builds the environment, the second opens the
dashboard in your browser.

You only need Python 3.10 or newer installed
([python.org/downloads](https://www.python.org/downloads/), tick *Add python.exe
to PATH*). `install.bat` creates its own virtual environment in `.venv\` and
touches nothing else on the machine.

| Command | What it does |
|---|---|
| `install.bat` | Create the environment, or update every package to the newest version allowed by `requirements.txt`. Safe to re-run any time. |
| `install.bat --dev` | The same, plus the test dependencies. |
| `install.bat --clean` | Delete `.venv\` and rebuild from scratch. Use this if an upgrade ever breaks something. |
| `start_app.bat` | Open the dashboard. |
| `start_app.bat --port 8600` | Use a different port if 8501 is taken. |

**Updates are handled for you.** `install.bat` always installs with `--upgrade`,
so re-running it pulls in newer releases of Streamlit, pandas and the rest.
`start_app.bat` records a hash of `requirements.txt` after each install and
compares it on every launch — if the file has changed, or the environment is
missing or broken, it runs `install.bat` itself before starting. So editing
`requirements.txt` and double-clicking `start_app.bat` is enough.

After installing, `install.bat` compiles the sources and imports every
dependency. If a future release of a library breaks the app, it says so and
points at `install.bat --clean` rather than leaving you with a half-working
environment.

<details>
<summary>Prefer the command line, or not on Windows?</summary>

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install --upgrade -r requirements.txt   # Windows
# .venv/bin/python -m pip install --upgrade -r requirements.txt         # macOS / Linux

.venv/Scripts/python.exe -m streamlit run app.py
```

The batch files are Windows conveniences; the app itself is plain Python and
runs anywhere.
</details>

## What it shows

**Market overview** — typical home value, median sale price, rent, gross rent
yield, days to pending and share of listings with a price cut, each against the
containing metro, state and nation. Price history since 2000, year-over-year
change, and rebased growth so a ZIP can be compared like-for-like with its
metro. Affordability is computed at the live 30-year mortgage rate: monthly
payment, income needed, and cost as a share of the local median income.

**National scanner** — every published region ranked on price change and a
momentum score, filterable by geography level, market size and state. The
scatter puts price level against growth, so cheap-and-appreciating markets
separate visually from expensive-and-cooling ones.

**Livability** — ACS demographics for the place and each geography containing
it: income, education, poverty, tenure, commute, age. County unemployment from
BLS. Crime if you supply a key.

**Compare** — up to six markets side by side on any metric, absolute or indexed.

**Macro** — mortgage rates, Case-Shiller, median US sale price, housing starts,
months' supply, unemployment.

## Data sources

| Data | Source | Geography | Key |
|---|---|---|---|
| Home values (ZHVI), rents (ZORI), median sale price, inventory, new listings, days to pending, price cuts | [Zillow Research](https://www.zillow.com/research/data/) | ZIP, city, county, metro, state — monthly since 2000 | none |
| Income, education, poverty, tenure, commute, age | US Census ACS via [Census Reporter](https://censusreporter.org) | ZIP, city, county, metro, state | none |
| Mortgage rates, Case-Shiller, housing starts, months' supply | [FRED](https://fred.stlouisfed.org) | national | none |
| Unemployment | [BLS](https://www.bls.gov/developers/) Local Area Unemployment Statistics | county, monthly | none |
| Violent and property crime | [FBI Crime Data Explorer](https://cde.ucr.cjis.gov) | state, annual | free, optional |

For crime, get a free key at <https://api.data.gov/signup/> and paste it into
the sidebar, or add it to `.streamlit/secrets.toml`:

```toml
FBI_API_KEY = "your-key-here"
```

## How it is put together

```
install.bat               one-click setup and updater
start_app.bat             one-click launcher, self-healing
app.py                    Streamlit entrypoint: sidebar search, tabs
src/redash/
  config.py               source URLs, metric registry, constants
  cache.py                disk cache (Parquet/JSON) with retry and stale fallback
  geo.py                  free-text query -> Zillow region + Census GEOID + county FIPS
  analytics.py            growth, CAGR, affordability, rent yield, momentum score
  sources/
    zillow.py             market data; wide monthly CSVs -> tidy series
    census.py             ACS tables and derived socioeconomic profile
    fred.py               macro series, batched by frequency
    bls.py                county unemployment
    fbi.py                crime (optional key)
  ui/
    charts.py             Plotly builders, one shared palette and template
    format.py             number and date formatting
    pages.py              one render_* function per tab
tests/test_app.py         AppTest integration checks + data-layer unit tests
```

Source files are cached on disk under `data/cache/` as Parquet, refreshed daily.
Zillow publishes monthly, so this costs nothing in freshness and makes reloads
instant. "Refresh all data" in the sidebar clears it.

## Reading the numbers

- **ZHVI is not median sale price.** Zillow's index tracks the typical home in
  the 35th–65th percentile of a market, smoothed and seasonally adjusted, so it
  is not moved by whatever mix of homes happened to sell in a given month.
  Median sale price is, which is why the two can diverge.
- **Momentum is relative.** It blends 1-year and 3-month price change,
  acceleration against the 3-year pace, price cuts and days to pending, then
  ranks the result against the other regions on screen. It is a percentile, not
  an absolute scale.
- **ACS lags.** Census estimates are multi-year surveys, so a small ZIP carries
  a wide margin of error and the release trails the market data by a year or
  more. Large geographies get 1-year releases, small ones 5-year; the app shows
  which it used.
- **Supply metrics stop at metro.** Zillow does not publish inventory, days to
  pending or price cuts for ZIP codes. Where a ZIP is selected the app falls
  back to its metro and says so.
- **Affordability is indicative.** It assumes a 30-year fixed at the current
  Freddie Mac average plus roughly 1.5% of value a year for tax and insurance.
  It is not a quote, and property tax varies widely by state.

## Tests

```bash
install.bat --dev
.venv/Scripts/python.exe -m pytest
```

The suite runs the real Streamlit script through `AppTest` across several
geographies — including sparse ones — and asserts no panel raises.

## Notes on the environment

Two quirks are handled in `cache.py` and worth knowing if you fork this:

- **TLS.** Machines behind a TLS-inspecting proxy have that proxy's root CA in
  the OS trust store but not in certifi's bundle. `truststore` makes Python use
  the OS store, matching curl and browsers.
- **User agent.** FRED's CDN tarpits both unrecognised and browser-like user
  agents, and Census Reporter rejects the bare `python-requests` default. The
  one form every source accepts is a curl-style token that still names the app.

## Disclaimer

These are indicative market statistics built from public data, not an appraisal,
a valuation, or investment advice.
