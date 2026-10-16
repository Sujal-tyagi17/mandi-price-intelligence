"""
Phase 4: a 4-week-ahead price range for every reliable market, and an honest test of whether
it beats simple rules.

Model (one per crop, pooled across that crop's markets, one per horizon of 1-4 weeks):
    target   = change in log price from this week to h weeks ahead
    features = last week's and last month's change, distance from the 12-week and 52-week averages
               (prices tend to drift back), and the average change over the same weeks in the
               previous three years (the season)
    method   = ridge regression (plain numpy)
    range    = 10th-90th percentile of the model's errors on the most recent 20% of its training
               data (a split-conformal interval), so the stated 80% range is checked, not assumed

Backtest: for each of the last 104 weeks, forecast using only data available at the time
(refitting every 13 weeks), and compare with two baselines:
    naive          next weeks = this week's price
    seasonal naive this week's price moved by the average change over the same weeks in past years

Writes data/processed/forecast.csv, forecast_backtest.csv, forecast_backtest_detail.csv.

Run:  python src/forecast.py
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from config import PROCESSED

HORIZONS = (1, 2, 3, 4)
FEATURES = ["chg_1w", "chg_4w", "gap_12w", "gap_52w", "season"]
BACKTEST_WEEKS = 104
REFIT_EVERY = 13
RIDGE_LAMBDA = 1.0
LEVELS = (0.10, 0.90)


def prepare(weekly: pd.DataFrame) -> pd.DataFrame:
    """Regular weekly log-price series per market; gaps of up to 3 weeks are interpolated."""
    out = []
    for (crop, state, market), g in weekly.groupby(["commodity", "state", "market"]):
        s = np.log(g.set_index("week").modal_price.astype(float)).asfreq("W-MON")
        s = s.interpolate(limit=3, limit_area="inside")
        out.append(pd.DataFrame({"commodity": crop, "state": state, "market": market,
                                 "week": s.index, "y": s.to_numpy()}))
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame(columns=["commodity", "state", "market", "week", "y"])


def features(y: pd.Series, h: int) -> pd.DataFrame:
    """Features at each origin week t for a forecast h weeks ahead (only uses data up to t)."""
    f = pd.DataFrame(index=y.index)
    f["chg_1w"] = y - y.shift(1)
    f["chg_4w"] = y - y.shift(4)
    f["gap_12w"] = y - y.rolling(12, min_periods=8).mean()
    f["gap_52w"] = y - y.rolling(52, min_periods=40).mean()
    past = [(y.shift(52 * k - h) - y.shift(52 * k)) for k in (1, 2, 3)]     # same weeks, k years ago
    f["season"] = pd.concat(past, axis=1).mean(axis=1)
    f["target"] = y.shift(-h) - y
    return f


def build_samples(series: pd.DataFrame, h: int) -> pd.DataFrame:
    parts = []
    for (crop, state, market), g in series.groupby(["commodity", "state", "market"]):
        y = g.set_index("week").y
        f = features(y, h)
        f["commodity"], f["state"], f["market"], f["y"] = crop, state, market, y
        f["target_week"] = f.index + pd.Timedelta(weeks=h)
        f.index.name = "origin"
        parts.append(f.reset_index())
    df = pd.concat(parts, ignore_index=True)
    return df.dropna(subset=["y", "chg_1w", "chg_4w", "gap_12w", "gap_52w"])


class Ridge:
    def fit(self, X: np.ndarray, y: np.ndarray, lam: float = RIDGE_LAMBDA) -> "Ridge":
        self.mu, self.sd = X.mean(0), X.std(0) + 1e-9
        Z = (X - self.mu) / self.sd
        self.b0 = y.mean()
        self.b = np.linalg.solve(Z.T @ Z + lam * np.eye(Z.shape[1]), Z.T @ (y - self.b0))
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        return self.b0 + ((X - self.mu) / self.sd) @ self.b


def _X(df: pd.DataFrame) -> np.ndarray:
    return df[FEATURES].fillna({"season": 0.0}).to_numpy()


def fit_with_interval(train: pd.DataFrame) -> tuple[Ridge, float, float]:
    """Fit on all of train; the interval comes from errors on the latest 20% when fitted on the rest."""
    train = train.sort_values("origin")
    cut = train["origin"].quantile(0.8)
    early, late = train[train["origin"] <= cut], train[train["origin"] > cut]
    m = Ridge().fit(_X(early), early.target.to_numpy())
    resid = late.target.to_numpy() - m.predict(_X(late))
    lo, hi = np.quantile(resid, LEVELS) if len(resid) >= 20 else (-0.2, 0.2)
    return Ridge().fit(_X(train), train.target.to_numpy()), float(lo), float(hi)


def backtest(samples: pd.DataFrame, h: int, weeks: int = BACKTEST_WEEKS) -> pd.DataFrame:
    labelled = samples.dropna(subset=["target"])
    if labelled.empty:
        return pd.DataFrame()
    last_origin = labelled["origin"].max()
    origins = pd.date_range(last_origin - pd.Timedelta(weeks=weeks - 1), last_origin, freq="W-MON")
    out = []
    for block_start in origins[::REFIT_EVERY]:
        train = labelled[labelled.target_week <= block_start]         # targets known by then: no leakage
        if len(train) < 200:
            continue
        model, lo, hi = fit_with_interval(train)
        block = labelled[(labelled["origin"] >= block_start)
                         & (labelled["origin"] < block_start + pd.Timedelta(weeks=REFIT_EVERY))]
        if block.empty:
            continue
        pred = model.predict(_X(block))
        out.append(pd.DataFrame({
            "commodity": block.commodity.to_numpy(), "state": block.state.to_numpy(), "market": block.market.to_numpy(),
            "origin_week": block["origin"].to_numpy(), "horizon": h, "target_week": block.target_week.to_numpy(),
            "last_price": np.exp(block.y.to_numpy()),
            "actual": np.exp(block.y.to_numpy() + block.target.to_numpy()),
            "model": np.exp(block.y.to_numpy() + pred),
            "low": np.exp(block.y.to_numpy() + pred + lo), "high": np.exp(block.y.to_numpy() + pred + hi),
            "naive": np.exp(block.y.to_numpy()),
            "seasonal_naive": np.exp(block.y.to_numpy() + block.season.fillna(0).to_numpy()),
        }))
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def score(detail: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (crop, h), g in detail.groupby(["commodity", "horizon"]):
        for name in ("naive", "seasonal_naive", "model"):
            row = {"commodity": crop, "horizon": h, "method": name, "forecasts": len(g),
                   "mape_pct": round(100 * (abs(g[name] - g.actual) / g.actual).mean(), 1)}
            if name == "model":
                row["coverage_80_pct"] = round(100 * ((g.actual >= g.low) & (g.actual <= g.high)).mean(), 1)
                row["avg_range_width_pct"] = round(100 * ((g.high - g.low) / g.model).mean(), 1)
            rows.append(row)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    naive = df[df.method == "naive"].set_index(["commodity", "horizon"]).mape_pct
    df["improvement_vs_naive_pct"] = [round(100 * (1 - r.mape_pct / naive[(r.commodity, r.horizon)]), 1)
                                      for r in df.itertuples()]
    return df


def forecast_now(samples_by_h: dict[int, pd.DataFrame]) -> pd.DataFrame:
    out = []
    for h, samples in samples_by_h.items():
        for crop, s in samples.groupby("commodity"):
            labelled = s.dropna(subset=["target"])
            if len(labelled) < 200:
                continue
            model, lo, hi = fit_with_interval(labelled)
            latest = s.sort_values("origin").groupby(["state", "market"]).tail(1)
            # only markets that reported recently enough for a forecast to make sense
            latest = latest[latest["origin"] >= s["origin"].max() - pd.Timedelta(weeks=4)]
            pred = model.predict(_X(latest))
            y = latest.y.to_numpy()
            out.append(pd.DataFrame({
                "commodity": crop, "state": latest.state.to_numpy(), "market": latest.market.to_numpy(),
                "origin_week": latest["origin"].to_numpy(), "horizon": h,
                "target_week": latest["origin"].to_numpy() + np.timedelta64(7 * h, "D"),
                "last_price": np.exp(y).round(0),
                "p10": np.exp(y + pred + lo).round(0), "p50": np.exp(y + pred).round(0),
                "p90": np.exp(y + pred + hi).round(0)}))
    if not out:
        return pd.DataFrame()
    return pd.concat(out, ignore_index=True).sort_values(["commodity", "state", "market", "horizon"])


def run(weekly: pd.DataFrame):
    series = prepare(weekly)
    samples = {h: build_samples(series, h) for h in HORIZONS}
    details = []
    for h, s in samples.items():
        for _, g in s.groupby("commodity"):
            details.append(backtest(g, h))
    detail = pd.concat([d for d in details if not d.empty], ignore_index=True) if any(
        not d.empty for d in details) else pd.DataFrame()
    return forecast_now(samples), (score(detail) if not detail.empty else pd.DataFrame()), detail


def main() -> None:
    weekly = pd.read_csv(PROCESSED / "weekly_prices.csv", parse_dates=["week"])
    fc, scores, detail = run(weekly)
    if not detail.empty:
        detail = detail.round({c: 0 for c in ("last_price", "actual", "model", "low", "high", "naive", "seasonal_naive")})
    for name, df in {"forecast": fc, "forecast_backtest": scores, "forecast_backtest_detail": detail}.items():
        df.to_csv(PROCESSED / f"{name}.csv", index=False)
        print(f"  {name:<26} {len(df):>7,} rows -> data/processed/{name}.csv")
    if not scores.empty:
        print(scores.pivot_table(index=["commodity", "horizon"], columns="method", values="mape_pct").to_string())


if __name__ == "__main__":
    main()
