-- Same day, same state, different mandi: how far apart are prices, and for how long?
-- Every pair of reliable markets in a state is compared on the days both reported.
-- A "big gap" is one market at least 15% above the other. Runs count consecutive shared
-- reporting days on which the same market stayed at least 15% higher.
WITH d AS (
    SELECT f.commodity, f.state, f.market, f.price_date, f.modal_price
    FROM fact_market_day f
    JOIN analysis_markets USING (state, market, commodity)
),
pairs AS (
    SELECT a.commodity, a.state, a.market AS market_a, b.market AS market_b, a.price_date,
           ln(b.modal_price / a.modal_price) AS log_gap
    FROM d a
    JOIN d b ON a.commodity = b.commodity AND a.state = b.state AND a.price_date = b.price_date
            AND a.market < b.market
),
signed AS (
    SELECT *,
           CASE WHEN log_gap > ln(1.15) THEN 1 WHEN log_gap < -ln(1.15) THEN -1 ELSE 0 END AS side,
           row_number() OVER (PARTITION BY commodity, state, market_a, market_b ORDER BY price_date) AS rn
    FROM pairs
),
runs AS (
    SELECT commodity, state, market_a, market_b, side, count(*) AS run_days
    FROM (SELECT *, rn - row_number() OVER (PARTITION BY commodity, state, market_a, market_b, side
                                            ORDER BY price_date) AS grp
          FROM signed)
    WHERE side <> 0
    GROUP BY commodity, state, market_a, market_b, side, grp
),
run_stats AS (
    SELECT commodity, state, market_a, market_b,
           round(avg(run_days), 1) AS avg_big_gap_run_days, max(run_days) AS longest_big_gap_run_days
    FROM runs GROUP BY ALL
)
SELECT s.commodity, s.state, s.market_a, s.market_b,
       count(*)                                                       AS shared_days,
       round(100 * (exp(median(s.log_gap)) - 1), 1)                   AS median_gap_b_vs_a_pct,
       round(100 * (exp(median(abs(s.log_gap))) - 1), 1)              AS median_abs_gap_pct,
       round(100.0 * avg((s.side <> 0)::INT), 1)                      AS pct_days_big_gap,
       round(100.0 * avg((s.log_gap > 0)::INT), 1)                    AS pct_days_b_higher,
       coalesce(r.avg_big_gap_run_days, 0)                            AS avg_big_gap_run_days,
       coalesce(r.longest_big_gap_run_days, 0)                        AS longest_big_gap_run_days
FROM signed s
LEFT JOIN run_stats r USING (commodity, state, market_a, market_b)
GROUP BY s.commodity, s.state, s.market_a, s.market_b, r.avg_big_gap_run_days, r.longest_big_gap_run_days
HAVING count(*) >= 100
ORDER BY s.commodity, s.state, median_abs_gap_pct DESC, s.market_a, s.market_b;
