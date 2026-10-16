-- When in the year is each crop cheap or dear?
-- Seasonal index: a market's median price in a month divided by its average monthly price
-- that year (100 = a normal month). Only market-years with at least 10 months of prices count,
-- and each year is compared with itself, so inflation and shock years don't distort the shape.
WITH monthly AS (
    SELECT f.commodity, f.state, f.market, year(f.price_date) AS yr, month(f.price_date) AS mon,
           median(f.modal_price) AS price
    FROM fact_market_day f
    JOIN analysis_markets USING (state, market, commodity)
    GROUP BY ALL
),
yearly AS (
    SELECT commodity, state, market, yr, avg(price) AS year_avg
    FROM monthly GROUP BY ALL HAVING count(*) >= 10
),
idx AS (
    SELECT m.*, 100 * m.price / y.year_avg AS season_index
    FROM monthly m JOIN yearly y USING (commodity, state, market, yr)
)
SELECT * FROM (
SELECT commodity, 'All' AS state, 'All markets' AS market, mon AS month,
       round(median(season_index), 1) AS season_index,
       round(quantile_cont(season_index, 0.25), 1) AS index_p25,
       round(quantile_cont(season_index, 0.75), 1) AS index_p75,
       count(*) AS market_years
FROM idx GROUP BY commodity, mon
UNION ALL
SELECT commodity, state, market, mon,
       round(median(season_index), 1), round(quantile_cont(season_index, 0.25), 1),
       round(quantile_cont(season_index, 0.75), 1), count(*)
FROM idx GROUP BY commodity, state, market, mon
)
ORDER BY commodity, state <> 'All', state, market, month;
