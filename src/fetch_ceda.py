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
state returns one state-average series, so the script asks for each district of the state,
which returns one row per mandi per day.

The free API has a tight request quota, so the script keeps requests to a minimum:
  * each district is first asked for the whole period in one request; only districts that
    are too slow are split into calendar years (and then halves of years);
  * every answer is cached in data/interim/ceda_cache/, so if CEDA pauses the run
    (HTTP 429) or you press Ctrl+C, running the same command again continues where it stopped
    without repeating any request.

Output: data/raw/ceda/<commodity>_<state>_<year>.csv, read automatically by src/ingest.py.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path

import pandas as pd
import requests

from config import COMMODITIES, INTERIM, RAW, ROOT, START_DATE, STATES

BASE_URL = "https://api.ceda.ashoka.edu.in/v1"
CACHE_DIR = INTERIM / "ceda_cache"
PRICE_PATH = "/agmarknet/prices"
# arrivals: probed once with a tiny request; if the endpoint isn't available, prices are saved without arrivals
QUANTITY_PATHS = ["/agmarknet/quantities", "/agmarknet/quantity"]
QUANTITY_FIELDS = ["quantity", "arrival", "arrivals", "arrival_quantity", "value"]
SLOW = "slow"  # cache marker: this request timed out before, go straight to smaller pieces


class Slow(Exception):
    """CEDA did not answer in time (or failed) for this request; a smaller request may work."""


def load_key() -> str | None:
    key = os.environ.get("CEDA_API_KEY")
    env = ROOT / ".env"
    if not key and env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("CEDA_API_KEY"):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
    return key


def split_range(start: str, end: str) -> list[tuple[str, str]]:
    """Calendar years for long ranges, halves for ranges of a year or less, [] if it can't be split further."""
    s, t = pd.Timestamp(start), pd.Timestamp(end)
    if s.year != t.year:
        return [(max(s, pd.Timestamp(f"{y}-01-01")).date().isoformat(),
                 min(t, pd.Timestamp(f"{y}-12-31")).date().isoformat()) for y in range(s.year, t.year + 1)]
    if (t - s).days <= 31:
        return []
    mid = s + (t - s) / 2
    return [(start, mid.date().isoformat()), ((mid + pd.Timedelta(days=1)).date().isoformat(), end)]


class Ceda:
    def __init__(self, key: str, session: requests.Session | None = None, pause: float = 1.0,
                 verbose: bool = False, cache_dir: Path | None = None):
        self.http = session or requests.Session()
        self.verbose = verbose
        self.http.headers.update({"Authorization": f"Bearer {key}"})
        self.pause = pause
        self.cache_dir = cache_dir
        self.requests_made = 0
        self._geo = None
        self._commodities = None
        self.quantity_path: str | None = "unknown"

    # -- cache ------------------------------------------------------------------------
    def _cache_get(self, key: str):
        if self.cache_dir is None:
            return None
        f = self.cache_dir / f"{key}.json"
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None

    def _cache_put(self, key: str, value) -> None:
        if self.cache_dir is None:
            return
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.cache_dir / f"{key}.tmp"
        tmp.write_text(json.dumps(value), encoding="utf-8")
        tmp.replace(self.cache_dir / f"{key}.json")

    def cached(self, key: str, fetch):
        hit = self._cache_get(key)
        if hit is not None:
            return hit
        value = fetch()
        self._cache_put(key, value)
        return value

    # -- transport --------------------------------------------------------------------
    def call(self, method: str, path: str, body: dict | None = None, retries: int = 3) -> list:
        """One API request. Waits out rate limits; raises Slow on timeouts/server errors after `retries`."""
        attempt = 0
        while True:
            t0 = time.time()
            if self.verbose:
                print(f"    -> {method} {path} ...", end="", flush=True)
            self.requests_made += 1
            try:
                r = self.http.request(method, BASE_URL + path, json=body, timeout=(15, 90))
            except requests.RequestException as e:
                if self.verbose:
                    print(f" no answer after {time.time() - t0:.0f}s ({type(e).__name__})", flush=True)
                if attempt >= retries:
                    raise Slow(f"{type(e).__name__}") from e
                attempt += 1
                time.sleep(5 * attempt)
                continue
            if self.verbose:
                try:
                    n = len(r.json().get("output", {}).get("data") or []) if r.status_code == 200 else 0
                except ValueError:
                    n = 0
                print(f" HTTP {r.status_code} in {time.time() - t0:.1f}s" + (f", {n:,} rows" if n else ""), flush=True)
            if r.status_code == 429:                       # quota used up: wait, then carry on
                wait = float(r.headers.get("Retry-After") or 60)
                limits = {k: v for k, v in r.headers.items() if "limit" in k.lower() or "remaining" in k.lower()}
                resume = (dt.datetime.now() + dt.timedelta(seconds=wait)).strftime("%H:%M")
                print(f"    CEDA request limit reached after {self.requests_made} requests"
                      + (f" {limits}" if limits else "") + f". Waiting until about {resume}.\n"
                      "    (Everything so far is saved: you can also press Ctrl+C and run the same command later.)",
                      flush=True)
                time.sleep(wait + 1)
                continue
            if r.status_code in (401, 403):
                raise SystemExit("CEDA rejected the API key (HTTP %d). Check CEDA_API_KEY; keys expire after "
                                 "a week, so you may need a new one." % r.status_code)
            if r.status_code >= 500:
                if attempt >= retries:
                    raise Slow(f"HTTP {r.status_code}")
                attempt += 1
                time.sleep(5 * attempt)
                continue
            r.raise_for_status()
            out = r.json().get("output", {})
            if out.get("type") != "success":
                raise RuntimeError(f"CEDA {path}: {out.get('message', 'unknown error')}")
            time.sleep(self.pause)  # be polite to a free, shared API
            return out.get("data", []) or []

    # -- reference data -----------------------------------------------------------------
    def commodities(self) -> pd.DataFrame:
        if self._commodities is None:
            self._commodities = pd.DataFrame(self.cached("commodities", lambda: self.call("GET", "/agmarknet/commodities")))
        return self._commodities

    def geographies(self) -> pd.DataFrame:
        if self._geo is None:
            self._geo = pd.DataFrame(self.cached("geographies", lambda: self.call("GET", "/agmarknet/geographies")))
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
        body = {"commodity_id": commodity_id, "state_id": state_id, "district_id": district_id, "indicator": "price"}
        data = self.cached(f"markets_{commodity_id}_{state_id}_{district_id}",
                           lambda: self.call("POST", "/agmarknet/markets", body))
        return {int(m["market_id"]): m["market_name"] for m in data}

    # -- data -----------------------------------------------------------------------------
    def ranged(self, path: str, commodity_id: int, state_id: int, district_id: int, start: str, end: str) -> list:
        """Rows for one district and date range; ranges CEDA is too slow for are split and retried."""
        key = f"{path.rsplit('/', 1)[-1]}_{commodity_id}_{state_id}_{district_id}_{start}_{end}"
        hit = self._cache_get(key)
        if hit is not None and hit != SLOW:
            return hit
        pieces = split_range(start, end)
        if hit != SLOW:
            body = {"commodity_id": commodity_id, "state_id": state_id, "district_id": [district_id],
                    "from_date": start, "to_date": end}
            try:
                rows = self.call("POST", path, body, retries=0 if pieces else 2)
                self._cache_put(key, rows)
                return rows
            except Slow as e:
                if not pieces:
                    raise RuntimeError(f"CEDA could not return {path} for district {district_id} "
                                       f"{start}..{end} ({e}). Try again later.") from e
                self._cache_put(key, SLOW)
        if self.verbose:
            print(f"    too slow for {start}..{end}, asking in {len(pieces)} smaller pieces", flush=True)
        return [row for a, b in pieces for row in self.ranged(path, commodity_id, state_id, district_id, a, b)]

    def prices(self, commodity_id: int, state_id: int, district_id: int, start: str, end: str) -> list:
        return self.ranged(PRICE_PATH, commodity_id, state_id, district_id, start, end)

    def find_quantity_path(self, commodity_id: int, state_id: int, district_id: int, day: str) -> str | None:
        """Probe the arrivals endpoint once with a one-day request."""
        if self.quantity_path == "unknown":
            found = self._cache_get("quantity_path")
            if found is None:
                found = ""
                body = {"commodity_id": commodity_id, "state_id": state_id, "district_id": [district_id],
                        "from_date": day, "to_date": day}
                for p in QUANTITY_PATHS:
                    try:
                        self.call("POST", p, body, retries=0)
                        found = p
                        break
                    except (requests.HTTPError, RuntimeError, Slow):
                        continue
                self._cache_put("quantity_path", found)
                if not found:
                    print("  note: CEDA arrivals (quantity) endpoint not available; saving prices only", flush=True)
            self.quantity_path = found or None
        return self.quantity_path

    def quantities(self, commodity_id: int, state_id: int, district_id: int, start: str, end: str) -> list:
        path = self.find_quantity_path(commodity_id, state_id, district_id, start)
        if not path:
            return []
        try:
            return self.ranged(path, commodity_id, state_id, district_id, start, end)
        except RuntimeError as e:
            print(f"    arrivals skipped for district {district_id}: {e}", flush=True)
            return []


def fetch(api: Ceda, commodity: str, state: str, start: str, end: str) -> pd.DataFrame:
    """All mandi-level rows for one crop and state between start and end (inclusive)."""
    cid, cname = api.commodity_id(commodity)
    sid, geo = api.state(state)
    dname = dict(zip(geo.census_district_id.astype(int), geo.census_district_name))
    district_ids = sorted(dname)
    rows, qty, names = [], [], {}
    for i, d in enumerate(district_ids, 1):
        if api.verbose:
            print(f"  [{i}/{len(district_ids)}] {dname[d]}", flush=True)
        got = [r for r in api.prices(cid, sid, d, start, end) if r.get("market_id") is not None]
        if not got:            # district has no mandi reporting this crop: nothing more to ask
            continue
        rows += got
        names.update(api.market_names(cid, sid, d))
        qty += api.quantities(cid, sid, d, start, end)
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows).drop_duplicates()       # state-average rows (no market_id) were dropped above
    out = pd.DataFrame({
        "date": df["date"].astype(str).str[:10],
        "state": state,
        "district": df.census_district_id.astype("Int64").map(dname),
        "market": df.market_id.astype(int).map(names).fillna("Market #" + df.market_id.astype(int).astype(str)),
        "market_id": df.market_id.astype(int),
        "commodity": cname,
        "min_price": df.min_price, "max_price": df.max_price, "modal_price": df.modal_price,
    })
    if qty:
        q = pd.DataFrame(qty)
        field = next((f for f in QUANTITY_FIELDS if f in q.columns), None)
        if field and "market_id" in q:
            q = q[q.market_id.notna()].drop_duplicates()
            q = q.assign(date=q["date"].astype(str).str[:10], market_id=q.market_id.astype(int))
            q = q.groupby(["date", "market_id"], as_index=False)[field].sum().rename(columns={field: "arrivals_tonnes"})
            out = out.merge(q, on=["date", "market_id"], how="left")
    return out.sort_values(["date", "district", "market"]).reset_index(drop=True)


def file_for(out_dir: Path, commodity: str, state: str, year: int) -> Path:
    return out_dir / f"{commodity.lower()}_{state.lower().replace(' ', '-')}_{year}.csv"


def download(api: Ceda, commodities, states, start: pd.Timestamp, end: pd.Timestamp, out_dir: Path,
             overwrite: bool = False) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    total = 0
    for commodity in commodities:
        for state in states:
            years = [y for y in range(start.year, end.year + 1)
                     if overwrite or not file_for(out_dir, commodity, state, y).exists()]
            if not years:
                print(f"  {commodity} / {state}: already downloaded")
                continue
            a = max(start, pd.Timestamp(f"{years[0]}-01-01")).date().isoformat()
            b = min(end, pd.Timestamp(f"{years[-1]}-12-31")).date().isoformat()
            print(f"\n{commodity} / {state}  {a} to {b}", flush=True)
            df = fetch(api, commodity, state, a, b)
            for y in years:
                part = df[df.date.str[:4] == str(y)] if not df.empty else df
                path = file_for(out_dir, commodity, state, y)
                if part.empty:
                    print(f"  {path.name:<40} no data")
                    continue
                part.to_csv(path, index=False)
                total += len(part)
                print(f"  {path.name:<40} {len(part):>7,} rows, {part.market.nunique():>3} markets")
    return total


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--commodity", action="append", help="repeatable; default: Onion, Tomato, Potato")
    ap.add_argument("--state", action="append", help="repeatable; default: the 6 project states")
    ap.add_argument("--from", dest="start", default=START_DATE, help="YYYY-MM-DD (default %(default)s)")
    ap.add_argument("--to", dest="end", default=dt.date.today().isoformat(), help="YYYY-MM-DD (default today)")
    ap.add_argument("--list-commodities", action="store_true")
    ap.add_argument("--overwrite", action="store_true", help="re-write files that already exist")
    ap.add_argument("--quiet", action="store_true", help="don't print every API request")
    args = ap.parse_args()

    key = load_key()
    if not key:
        sys.exit("No CEDA API key found. Get one free at https://api.ceda.ashoka.edu.in, then set CEDA_API_KEY "
                 "or put CEDA_API_KEY=... in a .env file in the project folder.")
    api = Ceda(key, verbose=not args.quiet, cache_dir=CACHE_DIR)
    print("Connecting to the CEDA API ...", flush=True)
    if args.list_commodities:
        print(api.commodities().sort_values("commodity_name").to_string(index=False))
        return

    out_dir = RAW / "ceda"
    try:
        total = download(api, args.commodity or COMMODITIES, args.state or STATES,
                         pd.Timestamp(args.start), pd.Timestamp(args.end), out_dir, args.overwrite)
    except KeyboardInterrupt:
        sys.exit("\nStopped. Everything downloaded so far is saved; run the same command again to continue.")
    print(f"\nDone: {total:,} new rows in {out_dir} ({api.requests_made} API requests). "
          "Next: python run_all.py")


if __name__ == "__main__":
    main()
