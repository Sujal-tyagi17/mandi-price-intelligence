# MandiPulse: when and where should a farmer sell?

**An analysis of real wholesale prices for onion, tomato and potato across Indian mandis (APMC markets), built to answer one practical question: how much money do farmers lose by selling at the wrong time or in the wrong market?**

`SQL (DuckDB)` · `Python (pandas, numpy)` · `Streamlit` · `Plotly` · `Agmarknet open data via the CEDA API` · `pytest`

> **Status: Phases 0–5 built and tested; real-data results and the live dashboard (Phase 6) come next.** All the code runs end to end and is covered by 39 tests on generated test data. The findings will be written up from the real download, so this README quotes no results yet. See the [roadmap](#roadmap).

---

## The question

Onion, tomato and potato prices in India swing wildly: in mid-2023 retail tomato prices jumped from around ₹20–40/kg to over ₹150/kg in many cities within weeks, and onion exports were banned from December 2023 to May 2024. For a farmer, the same harvest can earn very different amounts depending on **when** and **where** it is sold.

MandiPulse uses six years of daily mandi prices to answer:

1. **When** do prices bottom out after harvest, and when do they recover?
2. **Where:** how big are price gaps between nearby mandis on the same day, and how long do they last?
3. **Hold or sell:** does storing the crop for a few weeks pay, after storage losses?
4. **Policy:** what did the onion export ban do to prices at Lasalgaon, Asia's largest onion market?
5. **What next:** a realistic 4-week price range forecast for each crop and major market.

## Data

Real prices reported daily by APMC markets to **Agmarknet**, the Government of India's agricultural marketing network, downloaded through the [CEDA Agri Market API](DATA.md#option-a-recommended-the-ceda-agri-market-api-ashoka-university) (Ashoka University), with Agmarknet reports and the data.gov.in API as alternatives.

| | |
|---|---|
| Crops | Onion, Tomato, Potato |
| States | Maharashtra, Karnataka, Madhya Pradesh, Uttar Pradesh, Gujarat, Rajasthan |
| Period | January 2019 onwards |
| Fields | Date, state, district, market, variety, min / max / modal price (₹/quintal), arrivals (tonnes) |

How to download it: [DATA.md](DATA.md).

## Pipeline

```
CEDA API ─► data/raw/ ─► src/ingest.py ─► sql/00_staging.sql ─► DuckDB star schema ─► sql/01–07 ─► src/analysis.py ─► data/processed/*.csv ─► dashboard/
            CSV · Excel ·  one schema,      clean, flag, merge,    fact_market_day,     coverage,     src/decisions.py
            HTML · JSON    ₹/quintal        de-duplicate           dim_market, dim_date seasons, gaps src/forecast.py
```

**1. Ingestion (`src/ingest.py`).** Every source names its columns differently (`Arrival_Date`, `Price Date`, `Modal_x0020_Price`, `Modal Price (Rs./Quintal)`…). The loader recognises all of them, reads Agmarknet's `.xls` exports that are really HTML tables with title rows, converts ₹/kg to ₹/quintal and quintals to tonnes, parses day-first dates, and infers the state from the report title when there's no state column. Unknown layouts stop with a clear message listing the columns found.

**2. Cleaning (`sql/00_staging.sql`).** Every rule is in SQL, and nothing is dropped silently: each row carries `fix_*` and `flag_*` columns, and [`reports/data_quality.md`](reports/data_quality.md) counts every step.

| Problem in raw mandi data | How it's handled |
|---|---|
| Same market spelled several ways (`LASALGAON APMC`, `Lasalgaon`, `lasalgaon `) | Trim, proper-case, strip yard/committee suffixes |
| Out-of-scope crops (`Onion Green`, `Sweet Potato`, seeds) | Excluded and counted |
| Zero, missing or undated prices | Excluded and counted |
| Min and max price entered the wrong way round | Swapped |
| Price typed in ₹/kg instead of ₹/quintal (100× too low) | Detected against the market's typical price that month and rescaled |
| Duplicate reports, some with conflicting prices | Merged: median modal price, widest min–max range |
| One-day spikes far outside a market's normal range | Flagged with a robust (median/MAD) test against the surrounding 31 days and excluded from analysis, not deleted |
| Several varieties per market and day | Combined into one daily price, weighted by arrivals |

**3. Data model.** `fact_price_report` (one row per market, crop, variety, grade and day, with all flags), `fact_market_day` (the analysis grain: one price per market, crop and day), `dim_market`, and `dim_date` with Indian crop seasons (kharif / rabi / lean season).

**4. Coverage checks (`sql/01–03`).** How complete each market's history is. Everything after this uses only *reliable* markets (`analysis_markets`): at least a year of history and prices on at least 60% of days.

## Analysis

**When prices move (`sql/04`, `sql/06`, `src/analysis.py`)**
- *Seasonal index*: each month's price in a market divided by that market's average month **in the same year**, so a shock year or inflation doesn't distort the pattern; medians and inter-quartile range across years.
- *National price index*: every market relative to its own median, then the median across markets, so one big mandi doesn't dominate.
- *Shocks*: episodes when the index rose 40%+ (or fell by the same log amount) within four weeks; nearby weeks merge into one episode.
- *Volatility*: within-month coefficient of variation of daily prices, typical market per crop and month.
- *Supply and price*: log price on log arrivals with market × year and month fixed effects (alternating-projection demeaning, standard errors clustered by market). Reported as an association, not a demand curve.

**Where prices differ (`sql/07`)**: every pair of reliable mandis in a state, on the days both reported: typical gap, share of days one is 15%+ dearer, and how long those gaps last (gaps-and-islands runs in SQL).

## Decision tools (`src/decisions.py`)

| Tool | Question | Method |
|---|---|---|
| **Hold or sell** | If I store my crop *N* weeks instead of selling now, how often did that pay? | Every past week is a possible selling date; later price × (1 − weight loss) − storage cost vs today's price. Defaults per crop, all adjustable in the dashboard. |
| **Best market** | Which mandi in my state usually pays more than mine, by more than the transport cost? | Week-by-week premium over the last three years, net of a transport cost the user sets. |
| **Export ban study** | What did the Dec 2023 – May 2024 onion export ban do to mandi prices? | Event study: prices indexed to the two weeks before the ban, compared with the same weeks in normal years (2019–20 excluded: it had its own ban). With arrivals, the gap becomes an estimated ₹ crore revenue loss for farmers. |

## Forecast (`src/forecast.py`)

A 4-week-ahead **price range**, not just a number. One ridge regression per crop and horizon, pooled across that crop's mandis, on recent price changes, distance from the 12- and 52-week averages and the usual seasonal change. The 80% range comes from the model's errors on the latest 20% of its training data (split conformal), and the **backtest** checks it: for each of the last 104 weeks the model is refitted using only data available at the time and compared with two simple rules (*price stays the same* and *usual seasonal change*). If it doesn't beat them, the dashboard says so.

## Dashboard (`dashboard/`)

Seven Streamlit pages: **Prices now**, **When to sell** (price calendar + hold-or-sell simulator), **Where to sell** (best-market finder + same-day gaps), **Export ban**, **Next 4 weeks** (forecast + backtest), **Shocks & supply**, **About the data**. Light and dark themes, mobile-friendly. If the outputs were built from the synthetic sample, every page shows a warning banner.

## Roadmap

| Phase | What | Status |
|---|---|---|
| 0 | Repo, data sources, download guide, CEDA API and data.gov.in download scripts | ✅ Done |
| 1 | Ingestion, SQL cleaning, star schema, data quality report, tests | ✅ Done |
| 2 | Seasonality, supply vs price, volatility and price shocks, mandi-to-mandi price gaps | ✅ Built |
| 3 | Hold-or-sell simulator, best-market finder, onion export ban event study | ✅ Built |
| 4 | 4-week price range forecasts, backtested against naive baselines | ✅ Built |
| 5 | MandiPulse dashboard (Streamlit) | ✅ Built |
| 6 | Run on the real download, findings write-up, deployment | Waiting for the data download |

## How to run

```bash
git clone https://github.com/Sujal-tyagi17/mandi-price-intelligence.git
cd mandi-price-intelligence
python -m venv .venv
.venv\Scripts\activate          # Windows; on macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

python src/fetch_ceda.py        # download the data (needs a free CEDA API key, see DATA.md)
python run_all.py               # ingest -> clean -> warehouse -> coverage tables -> quality report
pytest -q                       # 28 tests: downloader, every source format and every cleaning rule
```

The tests run without any downloaded data: they generate small, deliberately messy files in each source format (renamed markets, duplicates, ₹/kg slips, spikes, HTML-as-Excel) and check that every cleaning rule handles them.

## Repository structure

```
├── data/
│   ├── raw/                 # downloaded source files (see DATA.md)
│   ├── interim/             # standardised raw table (generated)
│   └── processed/           # outputs of the SQL queries (generated)
├── sql/
│   ├── 00_staging.sql       # cleaning rules + star schema + data quality log
│   ├── 01–03_*.sql          # coverage checks
│   └── 04–07_*.sql          # seasons, weekly series, volatility, same-day price gaps
├── src/
│   ├── config.py            # scope: crops, states, dates, anchor markets
│   ├── fetch_ceda.py        # downloads daily market-level prices from the CEDA API
│   ├── fetch_datagov.py     # downloads recent days from the data.gov.in API
│   ├── ingest.py            # reads every source format into one schema
│   ├── build_warehouse.py   # runs the SQL in DuckDB, writes the quality report
│   ├── analysis.py          # price index, shocks, supply response
│   ├── decisions.py         # hold-or-sell, best market, export ban event study
│   └── forecast.py          # 4-week ranges + backtest
├── dashboard/               # Streamlit app (app.py, lib.py, views/)
├── tests/                   # pytest: downloader, ingestion, cleaning, analysis, forecast, dashboard
├── reports/                 # data_quality.md (generated)
├── DATA.md                  # how to get the data
└── run_all.py               # one-command pipeline
```

---

**Author:** Sujal Tyagi · [GitHub](https://github.com/Sujal-tyagi17) · also see [DarkStore Pulse](https://github.com/Sujal-tyagi17/darkstore-performance-analysis)
