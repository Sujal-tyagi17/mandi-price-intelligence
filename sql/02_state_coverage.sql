-- Coverage summary by state and crop
SELECT f.state, f.commodity,
       count(DISTINCT f.market)                                 AS markets,
       min(f.price_date)                                        AS first_report,
       max(f.price_date)                                        AS last_report,
       count(*)                                                 AS market_days,
       round(sum(f.arrivals_tonnes), 0)                         AS total_arrivals_tonnes,
       round(median(f.modal_price), 0)                          AS median_modal_price
FROM fact_market_day f
GROUP BY ALL
ORDER BY f.commodity, market_days DESC;
