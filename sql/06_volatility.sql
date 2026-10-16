-- How unstable are prices, month by month?
-- For each reliable market and month: the coefficient of variation of daily modal prices
-- (standard deviation / mean). The typical market's value (median) is reported per crop.
WITH m AS (
    SELECT f.commodity, f.market, f.state, date_trunc('month', f.price_date)::DATE AS month,
           stddev_samp(f.modal_price) / avg(f.modal_price) AS cv,
           count(*) AS days
    FROM fact_market_day f
    JOIN analysis_markets USING (state, market, commodity)
    GROUP BY ALL
    HAVING count(*) >= 8
)
SELECT commodity, month,
       round(100 * median(cv), 1)               AS median_cv_pct,
       round(100 * quantile_cont(cv, 0.9), 1)   AS p90_cv_pct,
       count(*)                                 AS markets
FROM m
GROUP BY ALL
ORDER BY commodity, month;
