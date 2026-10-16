"""
Phase 3: decision tools a farmer or trader could act on.

  * hold_or_sell   If I store my crop for N weeks instead of selling now, how often did that pay,
                   after storage losses and costs?
  * best_markets   Which other mandis in my state usually pay more than mine, by more than it
                   costs to take the crop there?
  * ban_event      What did the December 2023 onion export ban do to mandi prices, compared with
                   what normally happens over the same weeks of the year?

The functions are used by the dashboard with the user's own assumptions; main() writes the
default-assumption tables to data/processed/.

Run:  python src/decisions.py
"""

from __future__ import annotations

from dataclasses import dataclass

import duckdb
import numpy as np
import pandas as pd

from config import DB_PATH, PROCESSED


@dataclass(frozen=True)
class Storage:
    loss_pct_per_month: float      # weight lost to drying, sprouting and rot
    cost_per_quintal_month: float  # ₹ per quintal per month (cold-store rent, or upkeep of an on-farm store)
    hold_weeks: tuple[int, ...]    # holding periods worth testing
    note: str


# Default assumptions, deliberately simple and adjustable in the dashboard.
STORAGE = {
    "Onion": Storage(4.0, 30, (2, 4, 8, 12, 16, 24),
                     "Rabi onion kept in a ventilated on-farm store (kanda chawl); losses of a few % a month"),
    "Potato": Storage(1.5, 60, (2, 4, 8, 12, 16, 24),
                      "Cold storage rent spread over the season; low weight loss"),
    "Tomato": Storage(25.0, 0, (1, 2, 3),
                      "Tomato is perishable: realistically it can only be held for days, not months"),
}
WEEKS_PER_MONTH = 52 / 12

# Onion export ban: notified late on 7 December 2023, lifted on 4 May 2024 (with a minimum
# export price and an export duty, removed in September 2024).
BAN_START, BAN_END = pd.Timestamp("2023-12-08"), pd.Timestamp("2024-05-04")
# Comparison years for "what normally happens from early December": not 2019, which had its own
# export ban from September 2019 to March 2020, and not 2023 itself.
BAN_COMPARISON_YEARS = (2020, 2021, 2022, 2024)


# ---------------------------------------------------------------------------------------
def hold_or_sell(series: pd.DataFrame, loss_pct_per_month: float, cost_per_quintal_month: float,
                 hold_weeks: tuple[int, ...]) -> pd.DataFrame:
    """Every historical week is a possible selling date. Compare selling that week with storing
    and selling `h` weeks later, net of weight loss and storage cost.

    series: one market's weekly prices (columns week, modal_price), ₹/quintal.
    Returns one row per starting month and holding period.
    """
    s = series.set_index("week").modal_price.asfreq("W-MON")
    rows = []
    for h in hold_weeks:
        later = s.shift(-h)
        months = h / WEEKS_PER_MONTH
        kept = max(0.0, 1 - loss_pct_per_month / 100 * months)       # share of the crop still sellable
        net = later * kept - cost_per_quintal_month * months          # ₹ per quintal stored today
        gain = (net - s).dropna()
        pct = (100 * gain / s.loc[gain.index]).rename("gain_pct")
        df = pd.DataFrame({"gain_rs": gain, "gain_pct": pct, "month": gain.index.month})
        for m, g in df.groupby("month"):
            rows.append({"start_month": m, "hold_weeks": h, "cases": len(g),
                         "pct_cases_hold_paid": round(100 * (g.gain_rs > 0).mean(), 1),
                         "median_gain_pct": round(g.gain_pct.median(), 1),
                         "p10_gain_pct": round(g.gain_pct.quantile(0.1), 1),
                         "p90_gain_pct": round(g.gain_pct.quantile(0.9), 1),
                         "median_gain_rs_per_quintal": round(g.gain_rs.median(), 0)})
    return pd.DataFrame(rows)


def hold_or_sell_table(weekly: pd.DataFrame) -> pd.DataFrame:
    out = []
    for (crop, state, market), g in weekly.groupby(["commodity", "state", "market"]):
        st = STORAGE[crop]
        t = hold_or_sell(g, st.loss_pct_per_month, st.cost_per_quintal_month, st.hold_weeks)
        out.append(t.assign(commodity=crop, state=state, market=market))
    if not out:
        return pd.DataFrame()
    df = pd.concat(out, ignore_index=True)
    return df[["commodity", "state", "market"] + [c for c in df.columns if c not in ("commodity", "state", "market")]]


# ---------------------------------------------------------------------------------------
def best_markets(weekly: pd.DataFrame, commodity: str, state: str, home: str,
                 transport_rs_per_quintal: float, last_years: int | None = 3) -> pd.DataFrame:
    """Compare a home market with every other reliable market of the same crop in the state,
    week by week. A move 'pays' in a week when the other market's price minus the transport
    cost is higher than the home price."""
    w = weekly[(weekly.commodity == commodity) & (weekly.state == state)]
    if last_years:
        w = w[w.week > w.week.max() - pd.DateOffset(years=last_years)]
    wide = w.pivot_table(index="week", columns="market", values="modal_price")
    if home not in wide:
        return pd.DataFrame()
    rows = []
    for other in wide.columns.drop(home):
        pair = wide[[home, other]].dropna()
        if len(pair) < 12:
            continue
        premium = pair[other] - pair[home]
        net = premium - transport_rs_per_quintal
        rows.append({"market": other, "weeks_compared": len(pair),
                     "median_premium_rs": round(premium.median(), 0),
                     "median_premium_pct": round(100 * (premium / pair[home]).median(), 1),
                     "pct_weeks_move_pays": round(100 * (net > 0).mean(), 1),
                     "avg_gain_when_it_pays_rs": round(net[net > 0].mean(), 0) if (net > 0).any() else 0.0})
    cols = ["market", "weeks_compared", "median_premium_rs", "median_premium_pct", "pct_weeks_move_pays",
            "avg_gain_when_it_pays_rs"]
    return pd.DataFrame(rows, columns=cols).sort_values("pct_weeks_move_pays", ascending=False).reset_index(drop=True)


def best_market_table(weekly: pd.DataFrame, transport_rs_per_quintal: float = 100) -> pd.DataFrame:
    out = []
    for (crop, state), g in weekly.groupby(["commodity", "state"]):
        for home in sorted(g.market.unique()):
            b = best_markets(g, crop, state, home, transport_rs_per_quintal)
            if not b.empty:
                out.append(b.head(1).assign(commodity=crop, state=state, home_market=home))
    if not out:
        return pd.DataFrame()
    df = pd.concat(out, ignore_index=True).rename(columns={"market": "best_other_market"})
    lead = ["commodity", "state", "home_market", "best_other_market"]
    return df[lead + [c for c in df.columns if c not in lead]]


# ---------------------------------------------------------------------------------------
def _smooth_daily(prices: pd.Series) -> pd.Series:
    """Calendar-daily series with a centred 7-day mean (markets close on some days)."""
    s = prices.groupby(level=0).mean().asfreq("D")
    return s.rolling(7, center=True, min_periods=3).mean()


def ban_event(daily: pd.DataFrame, start: pd.Timestamp = BAN_START, end: pd.Timestamp = BAN_END,
              comparison_years=BAN_COMPARISON_YEARS, pre_days: int = 60, post_days: int = 240):
    """Event study for one or more onion markets.

    For each market the price is indexed to its average over the 14 days before the ban (=100).
    The same calendar window in normal years, indexed the same way, gives the expected path: how
    prices usually move from early December onwards as the late-kharif crop arrives. The gap between
    the actual and the expected index during the ban is the ban's estimated effect.

    daily: columns market, price_date, modal_price (+ arrivals_tonnes, optional).
    Returns (path, summary).
    """
    paths, summary = [], []
    offsets = np.arange(-pre_days, post_days + 1)
    for market, g in daily.groupby("market"):
        s = _smooth_daily(g.set_index("price_date").modal_price)

        def window(anchor: pd.Timestamp) -> pd.Series | None:
            base = s.loc[anchor - pd.Timedelta(days=14): anchor - pd.Timedelta(days=1)].mean()
            idx = pd.date_range(anchor - pd.Timedelta(days=pre_days), periods=len(offsets), freq="D")
            vals = s.reindex(idx)
            if not np.isfinite(base) or vals.notna().mean() < 0.7:
                return None
            return pd.Series(100 * vals.to_numpy() / base, index=offsets), base

        actual = window(start)
        normal = [w for y in comparison_years
                  if (w := window(pd.Timestamp(year=y, month=start.month, day=start.day))) is not None]
        if actual is None or len(normal) < 2:
            continue
        act, base = actual
        exp = pd.concat([n for n, _ in normal], axis=1)
        p = pd.DataFrame({"market": market, "day": offsets, "date": start + pd.to_timedelta(offsets, "D"),
                          "actual_index": act.round(1).to_numpy(),
                          "expected_index": exp.median(axis=1).round(1).to_numpy(),
                          "expected_low": exp.min(axis=1).round(1).to_numpy(),
                          "expected_high": exp.max(axis=1).round(1).to_numpy()})
        paths.append(p)

        during = p[(p.date >= start) & (p.date < end)].dropna(subset=["actual_index", "expected_index"])
        gap_rs = (during.expected_index - during.actual_index) / 100 * base      # ₹/quintal below normal
        row = {"market": market, "pre_ban_price": round(base, 0),
               "avg_actual_index": round(during.actual_index.mean(), 1),
               "avg_expected_index": round(during.expected_index.mean(), 1),
               "effect_pct": round(100 * (during.actual_index.mean() / during.expected_index.mean() - 1), 1),
               "effect_rs_per_quintal": round(-gap_rs.mean(), 0),
               "comparison_years": len(normal)}
        if "arrivals_tonnes" in g and g.arrivals_tonnes.notna().any():
            arr = g.set_index("price_date").arrivals_tonnes.groupby(level=0).sum()
            arr = arr[(arr.index >= start) & (arr.index < end)]
            qtl = arr.reindex(during.date).fillna(0).to_numpy() * 10          # tonnes -> quintals
            row["arrivals_during_ban_tonnes"] = round(float(arr.sum()), 0)
            row["revenue_gap_crore"] = round(float((gap_rs.to_numpy() * qtl).sum()) / 1e7, 1)
        summary.append(row)
    path = pd.concat(paths, ignore_index=True) if paths else pd.DataFrame()
    return path, pd.DataFrame(summary)


def load_onion_daily(db_path=DB_PATH) -> pd.DataFrame:
    con = duckdb.connect(str(db_path), read_only=True)
    df = con.execute("""
        SELECT f.state, f.market, f.price_date, f.modal_price, f.arrivals_tonnes
        FROM fact_market_day f JOIN analysis_markets USING (state, market, commodity)
        WHERE f.commodity = 'Onion' AND f.price_date BETWEEN DATE '2020-09-01' AND DATE '2025-12-31'
        ORDER BY f.market, f.price_date""").df()
    con.close()
    df["market"] = df.market + " (" + df.state + ")" if df.groupby("market").state.nunique().max() > 1 else df.market
    return df


def main() -> None:
    weekly = pd.read_csv(PROCESSED / "weekly_prices.csv", parse_dates=["week"])
    path, summary = ban_event(load_onion_daily())
    outputs = {
        "hold_or_sell": hold_or_sell_table(weekly),
        "best_market": best_market_table(weekly),
        "ban_event_daily": path,
        "ban_event_summary": summary,
    }
    for name, df in outputs.items():
        df.to_csv(PROCESSED / f"{name}.csv", index=False)
        print(f"  {name:<22} {len(df):>7,} rows -> data/processed/{name}.csv")


if __name__ == "__main__":
    main()
