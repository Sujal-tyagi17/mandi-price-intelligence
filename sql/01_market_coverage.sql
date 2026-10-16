-- How complete is each market's price history? Used to choose markets reliable enough for
-- time-series analysis (the same rule builds analysis_markets in 00_staging.sql).
WITH span AS (
    SELECT state, market, commodity,
           min(price_date) AS first_report, max(price_date) AS last_report,
           count(*) AS days_reported,
           date_diff('day', min(price_date), max(price_date)) + 1 AS days_in_span,
           round(avg(modal_price), 0) AS avg_modal_price,
           round(sum(arrivals_tonnes), 0) AS total_arrivals_tonnes
    FROM fact_market_day
    GROUP BY ALL
)
SELECT *,
       round(100.0 * days_reported / days_in_span, 1) AS coverage_pct,
       days_reported >= 365 AND 100.0 * days_reported / days_in_span >= 60 AS reliable
FROM span
ORDER BY commodity, coverage_pct DESC, market;
