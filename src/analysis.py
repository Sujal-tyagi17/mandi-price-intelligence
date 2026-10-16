"""
Phase 2 analysis in Python (the SQL parts are sql/04-07): national price index, price shocks,
and how strongly prices react to supply.

Reads data/processed/weekly_prices.csv (written by build_warehouse.py) and writes:
    data/processed/price_index_weekly.csv   one national index per crop and week (100 = typical price)
    data/processed/price_shocks.csv         episodes where the index rose 40%+ (or fell ~29%+) within 4 weeks
    data/processed/supply_price.csv         price response to arrivals (elasticity) per crop

Run:  python src/analysis.py
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from config import PROCESSED

SHOCK_CHANGE = 0.40      # index up 40%+ (or down by the same log amount, about 29%) within 4 weeks = shock
SHOCK_WINDOW = 4         # weeks


def load_weekly(processed=PROCESSED) -> pd.DataFrame:
    w = pd.read_csv(processed / "weekly_prices.csv", parse_dates=["week"])
    return w[w.modal_price > 0]


# ---------------------------------------------------------------------------------------
def price_index(weekly: pd.DataFrame) -> pd.DataFrame:
    """National weekly index per crop: each market's price relative to its own median, then the
    median across markets (so big and small, cheap and dear markets count equally)."""
    w = weekly.copy()
    w["rel"] = w.modal_price / w.groupby(["commodity", "state", "market"]).modal_price.transform("median")
    out = (w.groupby(["commodity", "week"])
             .agg(index=("rel", "median"), median_price=("modal_price", "median"), markets=("market", "nunique"))
             .reset_index())
    out["index"] = (100 * out["index"]).round(1)
    out["median_price"] = out.median_price.round(0)
    # year-on-year change, matched on the same ISO week a year earlier
    prev = out.assign(week=out.week + pd.Timedelta(weeks=52))[["commodity", "week", "median_price"]]
    out = out.merge(prev.rename(columns={"median_price": "price_year_ago"}), on=["commodity", "week"], how="left")
    out["yoy_pct"] = (100 * (out.median_price / out.price_year_ago - 1)).round(1)
    return out


def price_shocks(index: pd.DataFrame, change: float = SHOCK_CHANGE, window: int = SHOCK_WINDOW) -> pd.DataFrame:
    """Episodes where the national index rose or fell by `change` or more within `window` weeks.
    Consecutive flagged weeks in the same direction form one episode."""
    rows = []
    for crop, g in index.sort_values("week").groupby("commodity"):
        g = g.set_index("week")["index"].asfreq("W-MON").interpolate(limit=3)
        move = np.log(g / g.shift(window))
        up, down = move > np.log(1 + change), move < np.log(1 / (1 + change))
        for direction, flag in (("Spike", up), ("Crash", down)):
            weeks = g.index[flag.to_numpy()]
            if len(weeks) == 0:
                continue
            # flagged weeks less than `window` weeks apart belong to the same episode
            episode = np.cumsum(np.r_[True, np.diff(weeks.to_numpy()) > np.timedelta64(7 * window, "D")])
            for _, seg_weeks in pd.Series(weeks, index=weeks).groupby(episode):
                seg = g.loc[seg_weeks.index.min():seg_weeks.index.max()]
                start = seg.index.min() - pd.Timedelta(weeks=window)
                base = g.loc[start] if start in g.index else g.loc[:seg.index.min()].iloc[0]
                extreme_week = seg.idxmax() if direction == "Spike" else seg.idxmin()
                rows.append({
                    "commodity": crop, "direction": direction,
                    "start_week": start.date(), "extreme_week": extreme_week.date(),
                    "end_week": seg.index.max().date(),
                    "index_before": round(float(base), 1), "index_extreme": round(float(g.loc[extreme_week]), 1),
                    "change_pct": round(100 * (g.loc[extreme_week] / base - 1), 1),
                })
    cols = ["commodity", "direction", "start_week", "extreme_week", "end_week", "index_before",
            "index_extreme", "change_pct"]
    return pd.DataFrame(rows, columns=cols).sort_values(["commodity", "start_week"]).reset_index(drop=True)


# ---------------------------------------------------------------------------------------
def _demean(df: pd.DataFrame, cols: list[str], groups: list[list[str]], iters: int = 20) -> pd.DataFrame:
    """Remove several sets of fixed effects at once by alternating projections."""
    out = df[cols].copy()
    for _ in range(iters):
        for g in groups:
            out -= out.groupby([df[c] for c in g]).transform("mean")
    return out


def supply_price(weekly: pd.DataFrame) -> pd.DataFrame:
    """How much does the price move when a market receives more produce than usual?

    log(price) on log(arrivals) for each crop, comparing each market only with itself in the same
    year (market x year fixed effects) and removing the normal seasonal pattern (month fixed effects).
    The slope is the elasticity: -0.3 means 10% more arrivals goes with a ~3% lower price.
    It is an association, not a demand curve: supply and price affect each other.
    """
    cols = ["commodity", "elasticity", "ci_low", "ci_high", "price_change_for_10pct_more_arrivals",
            "weeks", "markets", "r2_within"]
    w = weekly[(weekly.arrivals_tonnes > 0) & (weekly.modal_price > 0)].copy()
    if w.empty:
        return pd.DataFrame(columns=cols)
    w["lp"], w["la"] = np.log(w.modal_price), np.log(w.arrivals_tonnes)
    w["year"], w["month"] = w.week.dt.year, w.week.dt.month
    rows = []
    for crop, g in w.groupby("commodity"):
        if len(g) < 200 or g.market.nunique() < 2:
            continue
        r = _demean(g, ["lp", "la"], [["state", "market", "year"], ["month"]])
        x, y = r.la.to_numpy(), r.lp.to_numpy()
        b = float(x @ y / (x @ x))
        e = y - b * x
        # standard error clustered by market (weeks of one market are not independent)
        scores = pd.Series(x * e).groupby(g.market.to_numpy()).sum().to_numpy()
        se = float(np.sqrt((scores ** 2).sum()) / (x @ x))
        rows.append({
            "commodity": crop, "elasticity": round(b, 3),
            "ci_low": round(b - 1.96 * se, 3), "ci_high": round(b + 1.96 * se, 3),
            "price_change_for_10pct_more_arrivals": round(100 * (1.1 ** b - 1), 1),
            "weeks": len(g), "markets": g.market.nunique(),
            "r2_within": round(1 - (e @ e) / (y @ y), 3),
        })
    return pd.DataFrame(rows, columns=cols)


def main() -> None:
    weekly = load_weekly()
    idx = price_index(weekly)
    outputs = {
        "price_index_weekly": idx,
        "price_shocks": price_shocks(idx),
        "supply_price": supply_price(weekly),
    }
    for name, df in outputs.items():
        df.to_csv(PROCESSED / f"{name}.csv", index=False)
        print(f"  {name:<22} {len(df):>7,} rows -> data/processed/{name}.csv")


if __name__ == "__main__":
    main()
