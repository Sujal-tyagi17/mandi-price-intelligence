"""Every cleaning rule in sql/00_staging.sql, checked against the messy fixture files."""


def one(con, sql):
    return con.execute(sql).fetchone()[0]


def log(con, step):
    return one(con, f"SELECT rows_affected FROM data_quality_log WHERE step = {step}")


def test_market_name_variants_collapse_to_one(warehouse):
    names = {r[0] for r in warehouse.execute(
        "SELECT DISTINCT market FROM fact_market_day WHERE commodity = 'Onion'").fetchall()}
    assert names == {"Lasalgaon"}


def test_out_of_scope_commodities_removed(warehouse):
    crops = {r[0] for r in warehouse.execute("SELECT DISTINCT commodity FROM fact_market_day").fetchall()}
    assert crops == {"Onion", "Tomato", "Potato"}
    assert log(warehouse, 2) == 2                         # Onion Green + Wheat


def test_zero_and_missing_prices_dropped(warehouse):
    assert log(warehouse, 4) == 2
    assert one(warehouse, "SELECT min(modal_price) FROM fact_price_report") > 0


def test_duplicates_merged(warehouse):
    assert log(warehouse, 8) == 2                         # one exact, one conflicting
    assert log(warehouse, 9) == 1
    dupes = one(warehouse, """SELECT count(*) FROM (SELECT market, commodity, variety, grade, price_date
                                FROM fact_price_report GROUP BY ALL HAVING count(*) > 1)""")
    assert dupes == 0


def test_min_max_swapped(warehouse):
    assert log(warehouse, 7) == 1
    assert one(warehouse, "SELECT count(*) FROM fact_price_report WHERE min_price > max_price") == 0


def test_rupee_per_kg_slip_fixed(warehouse):
    assert log(warehouse, 6) == 1
    p = one(warehouse, """SELECT modal_price FROM fact_market_day
                          WHERE market = 'Lasalgaon' AND price_date = DATE '2024-02-10'""")
    assert 1000 < p < 4000                                # back on the ₹/quintal scale


def test_outlier_flagged_and_excluded(warehouse):
    assert log(warehouse, 11) == 1
    spike_day = one(warehouse, """SELECT count(*) FROM fact_market_day
                                  WHERE market = 'Lasalgaon' AND price_date = DATE '2024-02-20'""")
    assert spike_day == 0
    kept = one(warehouse, "SELECT count(*) FROM fact_price_report WHERE flag_outlier")
    assert kept == 1                                      # flagged, not deleted


def test_analysis_table_has_one_row_per_market_crop_day(warehouse):
    dupes = one(warehouse, """SELECT count(*) FROM (SELECT market, commodity, price_date
                                FROM fact_market_day GROUP BY ALL HAVING count(*) > 1)""")
    assert dupes == 0


def test_dimensions_and_states(warehouse):
    states = {r[0] for r in warehouse.execute("SELECT DISTINCT state FROM dim_market").fetchall()}
    assert states == {"Maharashtra", "Karnataka", "Uttar Pradesh"}
    days = one(warehouse, "SELECT count(*) FROM dim_date")
    assert days == 120


def test_quality_log_accounts_for_every_raw_row(warehouse):
    raw = log(warehouse, 1)
    out_of_scope, no_date, no_price, no_market = log(warehouse, 2), log(warehouse, 3), log(warehouse, 4), log(warehouse, 5)
    merged = log(warehouse, 8)
    reports = one(warehouse, "SELECT count(*) FROM fact_price_report")
    assert raw == out_of_scope + no_date + no_price + no_market + merged + reports
