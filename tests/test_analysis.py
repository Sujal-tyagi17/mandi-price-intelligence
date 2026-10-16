"""Phases 2-4 on the synthetic sample (tests/sample_data.py), whose true patterns are known."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def built(tmp_path_factory):
    """Run the whole pipeline on the sample in a temporary folder."""
    import sample_data

    work = tmp_path_factory.mktemp("work")
    sample_data.write(work)
    env = {**os.environ, "MANDIPULSE_WORKDIR": str(work)}
    subprocess.run([sys.executable, str(ROOT / "run_all.py")], env=env, check=True, capture_output=True)
    return work / "data" / "processed"


def read(built, name, **kw):
    return pd.read_csv(built / f"{name}.csv", **kw)


# ---------- Phase 2 -------------------------------------------------------------------
def test_onion_seasonality_cheap_after_rabi_harvest_dear_before_kharif(built):
    s = read(built, "seasonality")
    onion = s[(s.commodity == "Onion") & (s.market == "All markets")].set_index("month").season_index
    assert onion.idxmin() in (3, 4, 5)
    assert onion.idxmax() in (9, 10, 11)
    assert onion.max() / onion.min() > 1.5


def test_more_arrivals_go_with_lower_prices(built):
    sp = read(built, "supply_price").set_index("commodity")
    assert (sp.elasticity < 0).all()
    assert (sp.ci_high < 0).all()


def test_tomato_2023_spike_detected(built):
    sh = read(built, "price_shocks", parse_dates=["extreme_week"])
    t = sh[(sh.commodity == "Tomato") & (sh.direction == "Spike") & (sh.extreme_week.dt.year == 2023)]
    assert len(t) == 1 and t.change_pct.iloc[0] > 100
    assert t.extreme_week.iloc[0].month in (7, 8)


def test_price_gaps_find_the_dearer_market(built):
    g = read(built, "price_gaps")
    pair = g[(g.commodity == "Onion") & (g.market_a == "Pune") & (g.market_b == "Solapur")].iloc[0]
    assert pair.median_gap_b_vs_a_pct < -5          # Solapur usually cheaper than Pune
    assert pair.pct_days_b_higher < 50
    assert pair.longest_big_gap_run_days >= pair.avg_big_gap_run_days > 0


def test_patchy_markets_left_out_of_analysis(built):
    weekly = read(built, "weekly_prices")
    assert "Hassan" not in set(weekly.market)        # reports on under 60% of days


# ---------- Phase 3 -------------------------------------------------------------------
def _series(prices):
    return pd.DataFrame({"week": pd.date_range("2022-01-03", periods=len(prices), freq="W-MON"),
                         "modal_price": prices})


def test_hold_pays_when_prices_rise_faster_than_losses():
    import decisions
    rising = _series(1000 * 1.02 ** np.arange(120))               # +2% a week
    t = decisions.hold_or_sell(rising, loss_pct_per_month=4, cost_per_quintal_month=0, hold_weeks=(4,))
    assert (t.pct_cases_hold_paid == 100).all()
    flat = _series(np.full(120, 1000.0))
    t = decisions.hold_or_sell(flat, loss_pct_per_month=4, cost_per_quintal_month=30, hold_weeks=(4,))
    assert (t.pct_cases_hold_paid == 0).all()
    # 4 weeks = 0.92 months: 3.7% weight loss + ₹27.7 storage on ₹1,000
    assert t.median_gain_rs_per_quintal.iloc[0] == pytest.approx(-(1000 * 4 / 100 + 30) * 4 / (52 / 12), abs=1)


def test_best_market_accounts_for_transport():
    import decisions
    weeks = pd.date_range("2024-01-01", periods=30, freq="W-MON")
    w = pd.concat([pd.DataFrame({"commodity": "Onion", "state": "S", "market": m, "week": weeks, "modal_price": p})
                   for m, p in [("Home", 1000.0), ("Near", 1080.0), ("Far", 1150.0)]])
    b = decisions.best_markets(w, "Onion", "S", "Home", transport_rs_per_quintal=100, last_years=None)
    assert list(b.market) == ["Far", "Near"]
    assert b.set_index("market").pct_weeks_move_pays.to_dict() == {"Far": 100.0, "Near": 0.0}


def test_export_ban_lowered_onion_prices(built):
    s = read(built, "ban_event_summary").set_index("market")
    assert s.loc["Lasalgaon", "effect_pct"] < -5
    assert s.loc["Lasalgaon", "revenue_gap_crore"] > 0
    path = read(built, "ban_event_daily")
    las = path[path.market == "Lasalgaon"]
    assert las[las.day.between(-14, -1)].actual_index.mean() == pytest.approx(100, abs=3)


# ---------- Phase 4 -------------------------------------------------------------------
def test_features_use_only_the_past():
    import forecast
    y = pd.Series(np.log(np.linspace(1000, 2000, 300)), index=pd.date_range("2020-01-06", periods=300, freq="W-MON"))
    f1 = forecast.features(y, 4)
    y2 = y.copy()
    y2.iloc[200:] += 1.0                                  # change the future only
    f2 = forecast.features(y2, 4)
    cols = forecast.FEATURES
    pd.testing.assert_frame_equal(f1.iloc[:200][cols], f2.iloc[:200][cols])


def test_forecast_ranges_are_ordered_and_calibrated(built):
    fc = read(built, "forecast")
    assert set(fc.horizon) == {1, 2, 3, 4}
    assert (fc.p10 <= fc.p50).all() and (fc.p50 <= fc.p90).all()
    bt = read(built, "forecast_backtest")
    model = bt[bt.method == "model"]
    assert model.coverage_80_pct.between(65, 92).all()     # an 80% range should hold ~80% of the time
    naive = bt[bt.method == "naive"].set_index(["commodity", "horizon"]).mape_pct
    assert (model.set_index(["commodity", "horizon"]).mape_pct <= naive * 1.05).all()
