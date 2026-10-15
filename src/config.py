"""Project scope and shared paths for MandiPulse."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
INTERIM = ROOT / "data" / "interim"
PROCESSED = ROOT / "data" / "processed"
REPORTS = ROOT / "reports"
SQL_DIR = ROOT / "sql"
DB_PATH = ROOT / "data" / "mandi.duckdb"

# ---- scope -------------------------------------------------------------------
COMMODITIES = ["Onion", "Tomato", "Potato"]
STATES = ["Maharashtra", "Karnataka", "Madhya Pradesh", "Uttar Pradesh", "Gujarat", "Rajasthan"]
START_DATE = "2019-01-01"

# Anchor markets used throughout the analysis (name as it appears after cleaning)
ANCHOR_MARKETS = {
    "Onion": ["Lasalgaon", "Pimpalgaon", "Bangalore", "Indore", "Mahuva"],
    "Tomato": ["Kolar", "Narayangaon", "Madanapalli", "Bangalore", "Nashik"],
    "Potato": ["Agra", "Farrukhabad", "Indore", "Bangalore", "Ahmedabad"],
}
