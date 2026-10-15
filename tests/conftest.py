"""
Test fixtures: small, deliberately messy files in each of the three source formats.

These are generated on the fly for the tests only (nothing here is real market data).
Each file contains specific problems the pipeline must handle, so every cleaning rule
in sql/00_staging.sql is exercised:

  * the same market spelled three ways ("LASALGAON APMC", "Lasalgaon", "lasalgaon ")
  * an exact duplicate row and a conflicting duplicate
  * a zero price and a missing price
  * min and max price reported the wrong way round
  * a price entered in ₹/kg instead of ₹/quintal
  * a one-day spike far outside the market's normal range (outlier)
  * an out-of-scope commodity ("Onion Green") and an unrelated one ("Wheat")
  * an Agmarknet .xls export that is really an HTML table with title rows and no state column
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

DAYS = pd.date_range("2024-01-01", periods=120, freq="D")


def _series(base: float, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return np.round(base * np.exp(np.cumsum(rng.normal(0, 0.02, len(DAYS)))), 0)


@pytest.fixture()
def raw_dir(tmp_path: Path) -> Path:
    raw = tmp_path / "raw"
    (raw / "ceda").mkdir(parents=True)
    (raw / "datagov").mkdir()
    (raw / "agmarknet").mkdir()

    # ---- CEDA-style CSV: Lasalgaon onion with arrivals -------------------------------
    p = _series(1800, 1)
    rows = []
    for i, d in enumerate(DAYS):
        name = ["LASALGAON APMC", "Lasalgaon", "lasalgaon "][i % 3]
        rows.append([d.strftime("%Y-%m-%d"), "Maharashtra", "Nashik", name, "Onion", "Red",
                     120 + i % 7, p[i] - 200, p[i] + 250, p[i]])
    rows.append(rows[10].copy())                                   # exact duplicate
    conflict = rows[20].copy(); conflict[9] = conflict[9] + 300     # conflicting duplicate
    rows.append(conflict)
    rows[30][7], rows[30][8] = rows[30][8], rows[30][7]             # min > max
    rows[40][7:10] = [p[40] / 100 - 2, p[40] / 100 + 2, p[40] / 100]  # ₹/kg slip
    rows[50][9] = p[50] * 6                                         # outlier spike
    rows[50][8] = p[50] * 6 + 100
    rows[60][9] = 0                                                 # zero price
    rows.append(["2024-02-01", "Maharashtra", "Nashik", "Lasalgaon", "Onion Green", "Other", 5, 900, 1200, 1000])
    rows.append(["2024-02-01", "Maharashtra", "Nashik", "Lasalgaon", "Wheat", "Lokwan", 50, 2400, 2600, 2500])
    pd.DataFrame(rows, columns=["Date", "State", "District", "Market", "Commodity", "Variety",
                                "Arrivals (Tonnes)", "Min Price", "Max Price", "Modal Price"]
                 ).to_csv(raw / "ceda" / "onion_maharashtra.csv", index=False)

    # ---- data.gov.in-style CSV: Kolar tomato, dd/mm/yyyy dates ------------------------
    t = _series(1500, 2)
    rows = [["Karnataka", "Kolar", "Kolar", "Tomato", "Hybrid", "FAQ", d.strftime("%d/%m/%Y"),
             t[i] - 150, t[i] + 150, t[i]] for i, d in enumerate(DAYS)]
    rows[5][9] = ""                                                  # missing price
    pd.DataFrame(rows, columns=["State", "District", "Market", "Commodity", "Variety", "Grade",
                                "Arrival_Date", "Min_x0020_Price", "Max_x0020_Price", "Modal_x0020_Price"]
                 ).to_csv(raw / "datagov" / "2024_tomato_karnataka.csv", index=False)

    # ---- Agmarknet export: HTML table saved as .xls, title rows, no state column ------
    q = _series(1200, 3)
    body = "".join(
        f"<tr><td>{i + 1}</td><td>Agra</td><td>Agra</td><td>Potato</td><td>Desi</td><td>FAQ</td>"
        f"<td>{q[i] - 100:.0f}</td><td>{q[i] + 100:.0f}</td><td>{q[i]:.0f}</td><td>{d:%d %b %Y}</td></tr>"
        for i, d in enumerate(DAYS))
    html = ("<html><body><table>"
            "<tr><td colspan='10'>Market-wise Daily Report for Potato, State: Uttar Pradesh</td></tr>"
            "<tr><td>Sl no.</td><td>District Name</td><td>Market Name</td><td>Commodity</td><td>Variety</td>"
            "<td>Grade</td><td>Min Price (Rs./Quintal)</td><td>Max Price (Rs./Quintal)</td>"
            "<td>Modal Price (Rs./Quintal)</td><td>Price Date</td></tr>"
            f"{body}</table></body></html>")
    (raw / "agmarknet" / "potato_report.xls").write_text(html, encoding="utf-8")
    return raw


@pytest.fixture()
def warehouse(raw_dir: Path, tmp_path: Path):
    import duckdb

    import build_warehouse
    import ingest

    interim = tmp_path / "interim"
    ingest.ingest(raw_dir, interim)
    db = tmp_path / "mandi.duckdb"
    build_warehouse.build(db, interim, tmp_path / "processed", tmp_path / "reports")
    con = duckdb.connect(str(db), read_only=True)
    yield con
    con.close()
