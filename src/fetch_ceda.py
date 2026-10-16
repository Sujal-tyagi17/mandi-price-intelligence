"""
Download daily, market-level mandi prices from the CEDA Agri Market API (Ashoka University).

CEDA republishes Agmarknet's daily wholesale prices from 2000 onwards (the latest months
lag by a few months). The API is free; you need a key:

  1. Open https://api.ceda.ashoka.edu.in, enter your email, type the 6-digit OTP,
     and click "Verify & Generate Key".
  2. Make the key available to this script, either:
        set CEDA_API_KEY=your-key            (Windows PowerShell: $env:CEDA_API_KEY="your-key")
     or put a line  CEDA_API_KEY=your-key  in a file called .env in the project folder
     (.env is git-ignored, so the key never gets pushed).

Usage:
    python src/fetch_ceda.py                         # project scope: 3 crops x 6 states, 2019 -> today
    python src/fetch_ceda.py --commodity Onion --state Maharashtra --from 2023-01-01
    python src/fetch_ceda.py --list-commodities      # check exact commodity names

How it works: the API is id-based (commodity_id, state_id, district_id). Asking for a whole
state returns one state-average series, so the script asks for every district of the state,
which returns one row per mandi per day. It downloads one calendar year at a time and skips
files that already exist, so an interrupted run can simply be restarted.

Output: data/raw/ceda/<commodity>_<state>_<year>.csv, read automatically by src/ingest.py.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import time
from pathlib import Path

import pandas as pd
import requests

from config import COMMODITIES, RAW, ROOT, START_DATE, STATES

BASE_URL = "https://api.ceda.ashoka.edu.in/v1"
# arrivals: tried once; if the endpoint isn't available, prices are saved without arrivals
QUANTITY_PATHS = ["/agmarknet/quantities", "/agmarknet/quantity"]
QUANTITY_FIELDS = ["quantity", "arrival", "arrivals", "arrival_quantity", "value"]
CHUNK = 1  # districts per request (one district per call keeps CEDA responses fast)


def load_key() -> str | None:
    key = os.environ.get("CEDA_API_KEY")
    env = ROOT / ".env"
    if not key and env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("CEDA_API_KEY"):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
    return key


class Ceda:
    def __init__(self, key: str, session: requests.Session | None = None, pause: float = 0.4, verbose: bool = False):
        self.http = session or requests.Session()
        self.verbose = verbose
        self.http.headers.update({"Authorization": f"Bearer {key}"})
        self.pause = pause
        self._geo = None
        self._commodities = None
        self._markets: dict[tuple, dict[int, str]] = {}
        self.quantity_path: str | None = "unknown"

    # -- transport --------------------------------------------------------------
    def call(self, method: str, path: str, body: dict | None = None, retries: int = 5) -> list:
        attempt, rate_waits = 0, 0
        while attempt <= retries:
            t0 = time.time()
            if self.verbose:
                print(f"    -> {method} {path} ...", end="", flush=True)
            try:
                r = self.http.request(method, BASE_URL + path, json=body, timeout=(15, 60))
            except requests.RequestException as e:
                if self.verbose:
                    print(f" failed after {time.time() - t0:.0f}s ({type(e).__name__})", flush=True)
                if attempt == retries:
                    raise RuntimeError(f"Network error calling CEDA {path}: {e}") from e
                time.sleep(2 * (attempt + 1))
                attempt += 1
                continue
            if self.verbose:
                try:
                    n = len(r.json().get("output", {}).get("data") or []) if r.status_code == 200 else 0
                except ValueError:
                    n = 0
                print(f" HTTP {r.status_code} in {time.time() - t0:.1f}s" + (f", {n:,} rows" if n else ""), flush=True)
            if r.status_code == 429 and rate_waits < 8:      # rate limit: always wait and retry
                rate_waits += 1
                wait = float(r.headers.get("Retry-After", 5 * rate_waits))
                print(f"    rate limited by CEDA, waiting {wait:.0f}s", flush=True)
                time.sleep(wait)
                continue
            if r.status_code in (401, 403):
                raise SystemExit("CEDA rejected the API key (HTTP %d). Check CEDA_API_KEY." % r.status_code)
            if r.status_code >= 500 and attempt < retries:
                time.sleep(3 * (attempt + 1))
                attempt += 1
                continue
            r.raise_for_status()
            out = r.json().get("output", {})
            if out.get("type") != "success":
                raise RuntimeError(f"CEDA {path}: {out.get('message', 'unknown error')}")
            time.sleep(self.pause)  # be polite to a free, shared API
            return out.get("data", []) or []
        raise RuntimeError(f"CEDA {path}: gave up after {retries} retries")

    # -- reference data -----------------------------------------------------------
    def commodities(self) -> pd.DataFrame:
        if self._commodities is None:
            self._commodities = pd.DataFrame(self.call("GET", "/agmarknet/commodities"))
        return self._commodities

    def geographies(self) -> pd.DataFrame:
        if self._geo is None:
            self._geo = pd.DataFrame(self.call("GET", "/agmarknet/geographies"))
        return self._geo

    def commodity_id(self, name: str) -> tuple[int, str]:
        c = self.commodities()
        exact = c[c.commodity_name.str.lower() == name.lower()]
        if exact.empty:
            exact = c[c.commodity_name.str.lower().str.startswith(name.lower())]
        if exact.empty:
            raise SystemExit(f"Unknown commodity '{name}'. Run with --list-commodities to see the names.")
        row = exact.iloc[0]
        return int(row.commodity_id), row.commodity_name

    def state(self, name: str) -> tuple[int, pd.DataFrame]:
        g = self.geographies()
        rows = g[g.census_state_name.str.lower() == name.lower()]
        if rows.empty:
            raise SystemExit(f"Unknown state '{name}'.")
        return int(rows.census_state_id.iloc[0]), rows

    def market_names(self, commodity_id: int, state_id: int, district_id: int) -> dict[int, str]:
        key = (commodity_id, state_id, district_id)
        if key not in self._markets:
            data = self.call("POST", "/agmarknet/markets", {"commodity_id": commodity_id, "state_id": state_id,
                                                            "district_id": district_id, "indicator": "price"})
            self._markets[key] = {int(m["market_id"]): m["market_name"] for m in data}
        return self._markets[key]

    # -- data -----------------------------------------------------------------------
    def prices(self, commodity_id: int, state_id: int, district_ids: list[int], start: str, end: str) -> list:
        """Fetch prices; if CEDA is too slow for the request, split it (fewer districts, then shorter dates)."""
        body = {"commodity_id": commodity_id, "state_id": state_id, "district_id": district_ids,
                "from_date": start, "to_date": end}
        try:
            return self.call("POST", "/agmarknet/prices", body, retries=0)
        except (RuntimeError, requests.HTTPError) as e:
            s, t = pd.Timestamp(start), pd.Timestamp(end)
            if len(district_ids) > 1:
                half = len(district_ids) // 2
                print(f"    too slow, splitting {len(district_ids)} districts into two requests", flush=True)
                return (self.prices(commodity_id, state_id, district_ids[:half], start, end)
                        + self.prices(commodity_id, state_id, district_ids[half:], start, end))
            if (t - s).days > 31:
                mid = s + (t - s) / 2
                print(f"    too slow, splitting {start}..{end} into two date ranges", flush=True)
                return (self.prices(commodity_id, state_id, district_ids, start, mid.date().isoformat())
                        + self.prices(commodity_id, state_id, district_ids,
                                      (mid + pd.Timedelta(days=1)).date().isoformat(), end))
            raise RuntimeError(f"CEDA could not return prices for district {district_ids} {start}..{end}: {e}") from e

    def quantities(self, commodity_id: int, state_id: int, district_ids: list[int], start: str, end: str) -> list:
        paths = QUANTITY_PATHS if self.quantity_path == "unknown" else ([self.quantity_path] if self.quantity_path else [])
        body = {"commodity_id": commodity_id, "state_id": state_id, "district_id": district_ids,
                "from_date": start, "to_date": end}
        for p in paths:
            try:
                data = self.call("POST", p, body, retries=1)
                self.quantity_path = p
                return data
            except (requests.HTTPError, RuntimeError):
                continue
        if self.quantity_path == "unknown":
            print("  note: CEDA quantity (arrivals) endpoint not available; saving prices only")
        self.quantity_path = None
        return []


def fetch_year(api: Ceda, commodity: str, state: str, year: int, start: str, end: str) -> pd.DataFrame:
    cid, cname = api.commodity_id(commodity)
    sid, geo = api.state(state)
    district_ids = sorted(int(d) for d in geo.census_district_id.unique())
    rows = []
    for i in range(0, len(district_ids), CHUNK):     # a few districts per request keeps responses small
        rows += api.prices(cid, sid, district_ids[i:i + CHUNK], start, end)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df = df[df.get("market_id").notna()] if "market_id" in df else df.iloc[0:0]
    if df.empty:
        return df
    dname = dict(zip(geo.census_district_id.astype(int), geo.census_district_name))
    names: dict[int, str] = {}
    for d in sorted(df.census_district_id.dropna().astype(int).unique()):
        names.update(api.market_names(cid, sid, d))
    out = pd.DataFrame({
        "date": df["date"].astype(str).str[:10],
        "state": state,
        "district": df.census_district_id.astype("Int64").map(dname),
        "market": df.market_id.astype(int).map(names).fillna("Market #" + df.market_id.astype(int).astype(str)),
        "market_id": df.market_id.astype(int),
        "commodity": cname,
        "min_price": df.min_price, "max_price": df.max_price, "modal_price": df.modal_price,
    })

    qty = []
    for i in range(0, len(district_ids), CHUNK):
        qty += api.quantities(cid, sid, district_ids[i:i + CHUNK], start, end)
    if qty:
        q = pd.DataFrame(qty)
        field = next((f for f in QUANTITY_FIELDS if f in q.columns), None)
        if field and "market_id" in q:
            q = q[q.market_id.notna()]
            q = q.assign(date=q["date"].astype(str).str[:10], market_id=q.market_id.astype(int))
            q = q.groupby(["date", "market_id"], as_index=False)[field].sum().rename(columns={field: "arrivals_tonnes"})
            out = out.merge(q, on=["date", "market_id"], how="left")
    return out.sort_values(["date", "district", "market"]).reset_index(drop=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--commodity", action="append", help="repeatable; default: Onion, Tomato, Potato")
    ap.add_argument("--state", action="append", help="repeatable; default: the 6 project states")
    ap.add_argument("--from", dest="start", default=START_DATE, help="YYYY-MM-DD (default %(default)s)")
    ap.add_argument("--to", dest="end", default=dt.date.today().isoformat(), help="YYYY-MM-DD (default today)")
    ap.add_argument("--list-commodities", action="store_true")
    ap.add_argument("--overwrite", action="store_true", help="re-download files that already exist")
    ap.add_argument("--quiet", action="store_true", help="don't print every API request")
    args = ap.parse_args()

    key = load_key()
    if not key:
        sys.exit("No CEDA API key found. Get one free at https://api.ceda.ashoka.edu.in, then set CEDA_API_KEY "
                 "or put CEDA_API_KEY=... in a .env file in the project folder.")
    api = Ceda(key, verbose=not args.quiet)
    print("Connecting to the CEDA API ...", flush=True)
    if args.list_commodities:
        print(api.commodities().sort_values("commodity_name").to_string(index=False))
        return

    out_dir = RAW / "ceda"
    out_dir.mkdir(parents=True, exist_ok=True)
    start, end = pd.Timestamp(args.start), pd.Timestamp(args.end)
    total = 0
    for commodity in args.commodity or COMMODITIES:
        for state in args.state or STATES:
            for year in range(start.year, end.year + 1):
                path = out_dir / f"{commodity.lower()}_{state.lower().replace(' ', '-')}_{year}.csv"
                if path.exists() and not args.overwrite:
                    print(f"  {path.name:<40} already downloaded")
                    continue
                print(f"  {commodity} / {state} / {year}", flush=True)
                y0 = max(start, pd.Timestamp(f"{year}-01-01")).date().isoformat()
                y1 = min(end, pd.Timestamp(f"{year}-12-31")).date().isoformat()
                df = fetch_year(api, commodity, state, year, y0, y1)
                if df.empty:
                    print(f"  {path.name:<40} no data")
                    continue
                df.to_csv(path, index=False)
                total += len(df)
                print(f"  {path.name:<40} {len(df):>7,} rows, {df.market.nunique():>3} markets")
    print(f"Done: {total:,} new rows in {out_dir.relative_to(ROOT)}. Next: python run_all.py")


if __name__ == "__main__":
    main()
