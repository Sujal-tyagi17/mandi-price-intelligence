"""Project scope and shared paths for MandiPulse."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SQL_DIR = ROOT / "sql"
# MANDIPULSE_WORKDIR lets the tests (and a dry run on sample data) use another folder for data/ and reports/
WORK = Path(os.environ.get("MANDIPULSE_WORKDIR", ROOT))
RAW = WORK / "data" / "raw"
INTERIM = WORK / "data" / "interim"
PROCESSED = WORK / "data" / "processed"
REPORTS = WORK / "reports"
DB_PATH = WORK / "data" / "mandi.duckdb"

# ---- scope -------------------------------------------------------------------
COMMODITIES = ["Onion", "Tomato", "Potato"]
STATES = ["Maharashtra", "Karnataka", "Madhya Pradesh", "Uttar Pradesh", "Gujarat", "Rajasthan"]
START_DATE = "2019-01-01"

# Anchor markets used throughout the analysis (name as it appears after cleaning)
ANCHOR_MARKETS = {
    "Onion": ["Lasalgaon", "Pimpalgaon", "Bangalore", "Indore", "Mahuva"],
    "Tomato": ["Kolar", "Narayangaon", "Bangalore", "Nashik", "Indore"],
    "Potato": ["Agra", "Farrukhabad", "Indore", "Bangalore", "Ahmedabad"],
}
