"""
Download mandi prices from the data.gov.in Agmarknet API.

data.gov.in publishes the Agmarknet feed "Current Daily Price of Various Commodities
from Various Markets (Mandi)". The API only serves the latest day, so this script is
for topping up the history with recent days; the multi-year history comes from the
CEDA / Agmarknet downloads described in DATA.md.

Usage:
    set DATA_GOV_IN_API_KEY=your-key          (Windows; on macOS/Linux: export ...)
    python src/fetch_datagov.py                # onion, tomato, potato for the 6 project states
    python src/fetch_datagov.py --commodity Onion --state Maharashtra

Get a free API key by registering at https://data.gov.in (My Account -> API key).
Files are written to data/raw/datagov/<date>_<commodity>_<state>.csv and are picked up
automatically by src/ingest.py.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import time

import pandas as pd
import requests

from config import COMMODITIES, RAW, STATES

API = "https://api.data.gov.in/resource/{resource}"
DEFAULT_RESOURCE = "9ef84268-d588-465a-a308-a864a43d0070"  # Current daily price ... (Mandi)
PAGE = 1000


def fetch(api_key: str, resource: str, commodity: str, state: str) -> pd.DataFrame:
    rows, offset = [], 0
    while True:
        params = {
            "api-key": api_key, "format": "json", "limit": PAGE, "offset": offset,
            "filters[commodity]": commodity, "filters[state]": state,
        }
        for attempt in range(4):
            try:
                r = requests.get(API.format(resource=resource), params=params, timeout=60)
                r.raise_for_status()
                break
            except requests.RequestException as e:  # the portal is often slow; retry with back-off
                if attempt == 3:
                    raise SystemExit(f"data.gov.in request failed for {commodity}/{state}: {e}")
                time.sleep(2 ** attempt * 3)
        records = r.json().get("records", [])
        rows.extend(records)
        if len(records) < PAGE:
            break
        offset += PAGE
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--commodity", action="append", help="repeatable; default: project commodities")
    ap.add_argument("--state", action="append", help="repeatable; default: project states")
    ap.add_argument("--resource", default=DEFAULT_RESOURCE, help="data.gov.in resource id")
    args = ap.parse_args()

    key = os.environ.get("DATA_GOV_IN_API_KEY")
    if not key:
        sys.exit("Set DATA_GOV_IN_API_KEY first (free key from https://data.gov.in).")

    out = RAW / "datagov"
    out.mkdir(parents=True, exist_ok=True)
    today = dt.date.today().isoformat()
    total = 0
    for commodity in args.commodity or COMMODITIES:
        for state in args.state or STATES:
            df = fetch(key, args.resource, commodity, state)
            if df.empty:
                print(f"  {commodity:<8} {state:<16} no records")
                continue
            path = out / f"{today}_{commodity.lower()}_{state.lower().replace(' ', '-')}.csv"
            df.to_csv(path, index=False)
            total += len(df)
            print(f"  {commodity:<8} {state:<16} {len(df):>5} rows -> {path.relative_to(RAW.parent.parent)}")
    print(f"Done: {total:,} rows.")


if __name__ == "__main__":
    main()
