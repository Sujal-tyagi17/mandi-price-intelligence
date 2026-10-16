"""
Synthetic mandi prices in the CEDA download format, for tests and dry runs only.

NOTHING HERE IS REAL MARKET DATA. The generator imitates the shape of the real data
(seasonal harvest cycles, supply-driven price swings, market premiums, missing days,
a few big shocks) so that every analysis step and the dashboard can be exercised
before the real download is available. Files are written with a SAMPLE_ prefix and
should never be copied into data/raw/.

    python tests/sample_data.py /some/folder      # writes /some/folder/data/raw/ceda/SAMPLE_*.csv
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

# (market, district, state, price premium vs the crop average, size of market)
MARKETS = {
    "Onion": [
        ("Lasalgaon", "Nashik", "Maharashtra", 0.00, 3.0), ("Pimpalgaon", "Nashik", "Maharashtra", 0.02, 2.0),
        ("Nashik", "Nashik", "Maharashtra", -0.01, 1.2), ("Pune", "Pune", "Maharashtra", 0.08, 1.5),
        ("Solapur", "Solapur", "Maharashtra", -0.06, 1.8), ("Ahmednagar", "Ahmednagar", "Maharashtra", -0.03, 1.0),
        ("Bangalore", "Bangalore", "Karnataka", 0.10, 2.0), ("Hubli", "Dharwad", "Karnataka", -0.04, 1.0),
        ("Indore", "Indore", "Madhya Pradesh", -0.05, 1.5), ("Mandsaur", "Mandsaur", "Madhya Pradesh", -0.12, 0.8),
        ("Mahuva", "Bhavnagar", "Gujarat", -0.10, 1.4), ("Gondal", "Rajkot", "Gujarat", -0.07, 1.0),
        ("Agra", "Agra", "Uttar Pradesh", 0.06, 0.8), ("Jaipur", "Jaipur", "Rajasthan", 0.05, 0.9),
    ],
    "Tomato": [
        ("Kolar", "Kolar", "Karnataka", 0.00, 3.0), ("Chintamani", "Chikkaballapur", "Karnataka", -0.03, 1.5),
        ("Bangalore", "Bangalore", "Karnataka", 0.12, 1.5), ("Narayangaon", "Pune", "Maharashtra", -0.02, 2.0),
        ("Nashik", "Nashik", "Maharashtra", 0.01, 1.4), ("Pune", "Pune", "Maharashtra", 0.10, 1.2),
        ("Indore", "Indore", "Madhya Pradesh", 0.04, 1.0), ("Ahmedabad", "Ahmedabad", "Gujarat", 0.08, 1.2),
        ("Lucknow", "Lucknow", "Uttar Pradesh", 0.15, 0.8), ("Jaipur", "Jaipur", "Rajasthan", 0.09, 0.8),
    ],
    "Potato": [
        ("Agra", "Agra", "Uttar Pradesh", 0.00, 3.0), ("Farrukhabad", "Farrukhabad", "Uttar Pradesh", -0.05, 2.0),
        ("Kanpur", "Kanpur Nagar", "Uttar Pradesh", 0.06, 1.0), ("Indore", "Indore", "Madhya Pradesh", 0.03, 1.5),
        ("Ujjain", "Ujjain", "Madhya Pradesh", -0.02, 0.8), ("Deesa", "Banaskantha", "Gujarat", -0.04, 1.6),
        ("Ahmedabad", "Ahmedabad", "Gujarat", 0.07, 1.2), ("Bangalore", "Bangalore", "Karnataka", 0.14, 1.2),
        ("Hassan", "Hassan", "Karnataka", 0.02, 0.7), ("Pune", "Pune", "Maharashtra", 0.11, 1.0),
        ("Jaipur", "Jaipur", "Rajasthan", 0.08, 0.7),
    ],
}
BASE_PRICE = {"Onion": 1800, "Tomato": 1500, "Potato": 1200}      # ₹/quintal
BASE_ARRIVALS = {"Onion": 300, "Tomato": 120, "Potato": 250}      # tonnes/day for a size-1 market
# log-price deviation by month (Jan..Dec): harvest gluts are cheap, lean seasons dear
SEASON = {
    "Onion": [-0.05, -0.12, -0.22, -0.28, -0.22, -0.08, 0.05, 0.15, 0.25, 0.32, 0.25, 0.08],
    "Tomato": [-0.35, -0.42, -0.30, -0.10, 0.05, 0.30, 0.45, 0.30, 0.10, 0.18, 0.10, -0.20],
    "Potato": [-0.10, -0.22, -0.28, -0.20, -0.10, 0.00, 0.06, 0.12, 0.18, 0.22, 0.15, 0.04],
}
# (crop, start, peak, end, log-size): big real-world-like episodes
SHOCKS = [
    ("Onion", "2019-09-01", "2019-11-25", "2020-02-15", 0.95),
    ("Onion", "2023-08-10", "2023-10-30", "2023-12-07", 0.45),
    ("Tomato", "2023-06-01", "2023-07-25", "2023-09-01", 1.25),
    ("Tomato", "2024-09-15", "2024-10-15", "2024-11-25", 0.55),
    ("Potato", "2020-08-01", "2020-11-01", "2021-01-20", 0.50),
]
BAN = ("2023-12-08", "2024-05-04")   # onion export ban: prices fall while it lasts


def _bump(days: pd.DatetimeIndex, start: str, peak: str, end: str) -> np.ndarray:
    """0 outside [start, end], rising linearly to 1 at peak, then falling back to 0."""
    t = ((days - pd.Timestamp(start)).days).to_numpy(float)
    p = (pd.Timestamp(peak) - pd.Timestamp(start)).days
    e = (pd.Timestamp(end) - pd.Timestamp(start)).days
    shape = np.where(t <= p, t / max(p, 1), (e - t) / max(e - p, 1))
    return np.clip(shape, 0, 1) * ((t >= 0) & (t <= e))


def _season(days: pd.DatetimeIndex, crop: str) -> np.ndarray:
    m = np.array(SEASON[crop] + SEASON[crop][:1])
    pos = days.month - 1 + (days.day - 1) / days.days_in_month
    return np.interp(pos, np.arange(13), m)


def generate(start: str = "2019-01-01", end: str = "2026-06-30", seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    days = pd.date_range(start, end, freq="D")
    n = len(days)
    frames = []
    for crop, markets in MARKETS.items():
        # common national price factor: slow mean-reverting wander + seasons + shocks
        common = np.zeros(n)
        for i in range(1, n):
            common[i] = 0.993 * common[i - 1] + rng.normal(0, 0.018)
        for c, a, p, e, size in SHOCKS:
            if c == crop:
                common += size * _bump(days, a, p, e)
        if crop == "Onion":
            ban = _bump(days, BAN[0], "2024-01-10", BAN[1])
            common -= 0.40 * np.clip(ban * 3, 0, 1) * (days < pd.Timestamp(BAN[1]))
        season = _season(days, crop)
        for mid, (market, district, state, premium, size) in enumerate(markets):
            local = np.zeros(n)
            for i in range(1, n):
                local[i] = 0.9 * local[i - 1] + rng.normal(0, 0.035)
            lp = np.log(BASE_PRICE[crop]) + premium + season + common + local
            supply = -1.4 * (season + 0.6 * common) + rng.normal(0, 0.25, n)       # gluts when cheap
            arrivals = BASE_ARRIVALS[crop] * size * np.exp(supply)
            modal = np.round(np.exp(lp + rng.normal(0, 0.02, n)), -1)
            spread = np.exp(rng.normal(-1.9, 0.3, n))
            df = pd.DataFrame({
                "date": days.strftime("%Y-%m-%d"), "state": state, "district": district, "market": market,
                "market_id": 1000 * (list(MARKETS).index(crop) + 1) + mid, "commodity": crop,
                "min_price": np.round(modal * (1 - spread), -1), "max_price": np.round(modal * (1 + spread), -1),
                "modal_price": modal, "arrivals_tonnes": np.round(arrivals, 1),
            })
            keep = (days.dayofweek != 6) & (rng.random(n) > 0.08)               # closed Sundays, gaps
            if market in ("Hassan", "Ujjain", "Mandsaur"):                     # patchy reporters
                keep &= rng.random(n) > 0.55
            frames.append(df[keep])
    return pd.concat(frames, ignore_index=True)


def write(root: Path, **kw) -> Path:
    out = root / "data" / "raw" / "ceda"
    out.mkdir(parents=True, exist_ok=True)
    df = generate(**kw)
    for (crop, state), part in df.groupby(["commodity", "state"]):
        part.to_csv(out / f"SAMPLE_{crop.lower()}_{state.lower().replace(' ', '-')}.csv", index=False)
    return out


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    print("Sample written to", write(Path(sys.argv[1])))
