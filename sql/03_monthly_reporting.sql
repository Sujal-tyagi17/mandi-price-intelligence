-- Reports per month by crop: shows gaps in the source data (strikes, portal outages, holidays)
SELECT commodity,
       date_trunc('month', price_date)                          AS month,
       count(DISTINCT market)                                   AS markets_reporting,
       count(*)                                                 AS market_days,
       round(median(modal_price), 0)                            AS median_modal_price
FROM fact_market_day
GROUP BY ALL
ORDER BY commodity, month;
