"""
Read every raw mandi price file under data/raw/ and write one standardised table.

Sources look different:
  * CEDA Agri-Market CSVs
  * Agmarknet "Price and Arrivals" exports (.xls that are often HTML tables, or .xlsx)
  * data.gov.in API CSV / JSON (headers like Modal_x0020_Price)

This module maps all of them onto one schema:

  source, source_file, state, district, market, commodity, variety, grade,
  price_date, min_price, max_price, modal_price   (₹ per quintal),
  arrivals_tonnes

No cleaning decisions are made here beyond units and types: duplicates, bad prices,
name variants and outliers are handled transparently in sql/00_staging.sql.

Run:  python src/ingest.py
Output: data/interim/raw_prices.parquet
"""

from __future__ import annotations

import io
import json
import re
from pathlib import Path

import pandas as pd

from config import INTERIM, RAW

STANDARD = ["state", "district", "market", "commodity", "variety", "grade", "price_date",
            "min_price", "max_price", "modal_price", "arrivals"]
REQUIRED = ["market", "commodity", "price_date", "modal_price"]

# normalised header -> standard column. Headers are normalised by lower-casing and turning
# any run of non-alphanumeric characters into "_", e.g. "Modal Price (Rs./Quintal)" ->
# "modal_price_rs_quintal" and "Modal_x0020_Price" -> "modal_x0020_price".
ALIASES = {
    "state": ["state", "state_name", "statename"],
    "district": ["district", "district_name", "districtname"],
    "market": ["market", "market_name", "marketname", "apmc", "apmc_name", "mandi", "mandi_name",
               "market_center", "centre_name"],
    "commodity": ["commodity", "commodity_name", "commodityname", "crop"],
    "variety": ["variety", "variety_name", "commodity_variety"],
    "grade": ["grade"],
    "price_date": ["arrival_date", "price_date", "reported_date", "date", "trade_date", "t"],
    "min_price": ["min_price", "min_x0020_price", "minimum_price", "min_price_rs_quintal",
                  "min_price_rs_qtl", "min_price_rs_kg", "minprice"],
    "max_price": ["max_price", "max_x0020_price", "maximum_price", "max_price_rs_quintal",
                  "max_price_rs_qtl", "max_price_rs_kg", "maxprice"],
    "modal_price": ["modal_price", "modal_x0020_price", "modal_price_rs_quintal", "modal_price_rs_qtl",
                    "modal_price_rs_kg", "modalprice", "price"],
    "arrivals": ["arrivals", "arrival", "arrivals_tonnes", "arrival_quantity", "arrivals_quantity",
                 "arrival_qty", "quantity", "arrivals_in_tonnes", "arrivals_qtl", "arrivals_quintal",
                 "arrival_quantity_tonnes", "arrival_quantity_quintal"],
}
LOOKUP = {alias: std for std, aliases in ALIASES.items() for alias in aliases}


def norm(header: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(header).strip().lower()).strip("_")


class UnknownLayout(ValueError):
    pass


# ---------------------------------------------------------------------------
# Readers
# ---------------------------------------------------------------------------
def _read_excel_like(path: Path) -> pd.DataFrame:
    raw = path.read_bytes()
    head = raw[:600].lower()
    if b"<html" in head or b"<table" in head or b"<!doctype" in head:
        tables = pd.read_html(io.BytesIO(raw))
        return max(tables, key=len)
    return pd.read_excel(path, sheet_name=0)


def _promote_header(df: pd.DataFrame) -> pd.DataFrame:
    """Agmarknet exports often have title rows above the real header; find it."""
    if sum(norm(c) in LOOKUP for c in df.columns) >= 3:
        return df
    for i in range(min(len(df), 15)):
        row = [norm(v) for v in df.iloc[i].tolist()]
        if sum(v in LOOKUP for v in row) >= 3:
            out = df.iloc[i + 1:].copy()
            out.columns = df.iloc[i].tolist()
            return out.reset_index(drop=True)
    return df


def read_any(path: Path) -> tuple[pd.DataFrame, str]:
    """Return the table and any title text found above the header (used to infer the state)."""
    suffixes = "".join(path.suffixes).lower()
    if suffixes.endswith((".csv", ".csv.gz", ".txt")):
        df = pd.read_csv(path, dtype=str, encoding_errors="replace")
    elif suffixes.endswith((".xls", ".xlsx")):
        df = _read_excel_like(path).astype(str)
    elif suffixes.endswith(".json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        records = payload.get("records", payload) if isinstance(payload, dict) else payload
        df = pd.DataFrame(records).astype(str)
    else:
        raise UnknownLayout(f"unsupported file type: {path.name}")
    promoted = _promote_header(df)
    title = " ".join(str(c) for c in df.columns) + " " + " ".join(
        str(v) for v in df.head(len(df) - len(promoted)).to_numpy().ravel()) if len(promoted) < len(df) else ""
    return promoted, title


# ---------------------------------------------------------------------------
# Standardise one file
# ---------------------------------------------------------------------------
def to_number(s: pd.Series) -> pd.Series:
    cleaned = s.astype(str).str.replace(r"[,₹\s]", "", regex=True).replace({"": None, "nan": None, "NA": None,
                                                                             "-": None, "None": None})
    return pd.to_numeric(cleaned, errors="coerce")


def parse_dates(s: pd.Series) -> pd.Series:
    s = s.astype(str).str.strip()
    iso = s.str.match(r"^\d{4}-\d{2}-\d{2}")
    out = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns]")
    out[iso] = pd.to_datetime(s[iso].str[:10], format="%Y-%m-%d", errors="coerce")
    out[~iso] = pd.to_datetime(s[~iso], dayfirst=True, errors="coerce", format="mixed")
    return out.dt.normalize()


def standardise(df: pd.DataFrame, source: str, source_file: str) -> pd.DataFrame:
    df = df.dropna(how="all")
    mapping, units = {}, {}
    for col in df.columns:
        n = norm(col)
        if n in LOOKUP and LOOKUP[n] not in mapping.values():
            mapping[col] = LOOKUP[n]
            units[LOOKUP[n]] = n
    missing = [c for c in REQUIRED if c not in mapping.values()]
    if missing:
        raise UnknownLayout(
            f"{source_file}: could not find {missing}. Columns found: {list(df.columns)}. "
            "Add the header to ALIASES in src/ingest.py.")
    out = df.rename(columns=mapping)[list(mapping.values())].copy()
    for col in STANDARD:
        if col not in out:
            out[col] = None

    for col in ["min_price", "max_price", "modal_price", "arrivals"]:
        out[col] = to_number(out[col])
    # Prices are normally ₹/quintal; a few exports quote ₹/kg.
    for col in ["min_price", "max_price", "modal_price"]:
        if units.get(col, "").endswith("_kg"):
            out[col] = out[col] * 100
    # Arrivals are normally tonnes; convert quintals (1 tonne = 10 quintals).
    arr_unit = units.get("arrivals", "")
    out["arrivals_tonnes"] = out["arrivals"] / 10 if ("qtl" in arr_unit or "quintal" in arr_unit) else out["arrivals"]

    out["price_date"] = parse_dates(out["price_date"])
    for col in ["state", "district", "market", "commodity", "variety", "grade"]:
        out[col] = out[col].astype("string").str.strip().replace({"": None, "nan": None, "None": None})
    out.insert(0, "source", source)
    out.insert(1, "source_file", source_file)
    return out[["source", "source_file", "state", "district", "market", "commodity", "variety", "grade",
                "price_date", "min_price", "max_price", "modal_price", "arrivals_tonnes"]]


INDIAN_STATES = [
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Goa", "Gujarat", "Haryana",
    "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur",
    "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana",
    "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal", "Delhi", "Jammu And Kashmir",
]


def infer_state(path: Path, title_text: str) -> str | None:
    """Agmarknet report exports name the state in the title or file name, not in a column."""
    haystack = f"{path.as_posix()} {title_text}".lower().replace("_", " ").replace("-", " ")
    hits = [st for st in INDIAN_STATES if st.lower() in haystack]
    return max(hits, key=len) if hits else None


def source_of(path: Path, raw_dir: Path) -> str:
    rel = path.relative_to(raw_dir).parts
    return rel[0] if len(rel) > 1 else "other"


def discover(raw_dir: Path) -> list[Path]:
    exts = (".csv", ".csv.gz", ".txt", ".xls", ".xlsx", ".json")
    return sorted(p for p in raw_dir.rglob("*") if p.is_file() and "".join(p.suffixes).lower().endswith(exts)
                  and not p.name.startswith((".", "~")) and p.name.lower() != "readme.md")


def ingest(raw_dir: Path = RAW, out_dir: Path = INTERIM) -> pd.DataFrame:
    files = discover(raw_dir)
    if not files:
        raise SystemExit(f"No data files found under {raw_dir}. See DATA.md for how to download them.")
    frames, log = [], []
    for path in files:
        rel = path.relative_to(raw_dir).as_posix()
        table, title = read_any(path)
        df = standardise(table, source_of(path, raw_dir), rel)
        if df["state"].isna().any():
            st = infer_state(path.relative_to(raw_dir), title)
            if st:
                df["state"] = df["state"].fillna(st)
        frames.append(df)
        log.append((rel, len(df)))
    allrows = pd.concat(frames, ignore_index=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    allrows.to_parquet(out_dir / "raw_prices.parquet", index=False)
    pd.DataFrame(log, columns=["file", "rows"]).to_csv(out_dir / "ingest_log.csv", index=False)
    return allrows


def main() -> None:
    df = ingest()
    print(f"Ingested {len(df):,} rows from {df.source_file.nunique()} files "
          f"({', '.join(f'{k}: {v:,}' for k, v in df.source.value_counts().items())})")
    print(f"Dates {df.price_date.min():%Y-%m-%d} to {df.price_date.max():%Y-%m-%d} -> data/interim/raw_prices.parquet")


if __name__ == "__main__":
    main()
