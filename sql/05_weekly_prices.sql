-- Weekly price and arrivals for every reliable market: the series used by the volatility,
-- supply, hold-or-sell, best-market and forecasting steps and by the dashboard.
SELECT f.commodity, f.state, f.district, f.market,
       date_trunc('week', f.price_date)::DATE  AS week,
       round(median(f.modal_price), 0)         AS modal_price,
       round(sum(f.arrivals_tonnes), 1)        AS arrivals_tonnes,
       count(*)                                AS days_reported
FROM fact_market_day f
JOIN analysis_markets USING (state, market, commodity)
GROUP BY ALL
ORDER BY commodity, state, market, week;
