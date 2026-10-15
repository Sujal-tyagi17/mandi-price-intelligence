-- =====================================================================
-- 00_staging.sql
-- Clean the standardised raw prices and build the analysis star schema.
-- {interim} is replaced with the data/interim path by src/build_warehouse.py
--
-- Every row keeps a record of what happened to it (fix_* / flag_* columns),
-- and data_quality_log summarises the counts. Nothing is silently dropped.
-- =====================================================================

-- ---------- 1. landing ------------------------------------------------
CREATE OR REPLACE TABLE raw_prices AS
SELECT row_number() OVER () AS raw_id, * REPLACE (CAST(price_date AS DATE) AS price_date)
FROM read_parquet('{interim}/raw_prices.parquet');

-- ---------- 2. name standardisation -------------------------------------
-- Proper-case helper: "LASALGAON" / "lasalgaon" -> "Lasalgaon"
CREATE OR REPLACE MACRO proper(s) AS
    array_to_string(list_transform(string_split(lower(trim(regexp_replace(s, '\s+', ' ', 'g'))), ' '),
                                   w -> upper(w[1]) || w[2:]), ' ');

CREATE OR REPLACE TABLE stg_named AS
SELECT
    r.*,
    -- commodity: keep only the project crops, whatever the spelling
    CASE WHEN lower(commodity) LIKE '%onion%' AND NOT regexp_matches(lower(commodity), 'seed|green|spring') THEN 'Onion'
         WHEN lower(commodity) LIKE '%tomato%' THEN 'Tomato'
         WHEN lower(commodity) LIKE '%potato%' AND lower(commodity) NOT LIKE '%sweet%' THEN 'Potato'
    END                                                                     AS commodity_std,
    -- state: proper case + historic spellings
    CASE proper(state)
        WHEN 'Orissa' THEN 'Odisha' WHEN 'Chattisgarh' THEN 'Chhattisgarh'
        WHEN 'Pondicherry' THEN 'Puducherry' WHEN 'Nct Of Delhi' THEN 'Delhi'
        ELSE proper(state) END                                              AS state_std,
    proper(district)                                                        AS district_std,
    -- market: strip yard/committee suffixes so "LASALGAON APMC", "Lasalgaon(Vinchur)" variants
    -- that refer to the main yard collapse to one name; sub-yards in brackets are kept apart
    proper(trim(regexp_replace(regexp_replace(market,
        '\s*(\(f\s*&\s*v\)|\(f&v\)|apmc|a\.p\.m\.c\.?|mandi samiti|krishi upaj mandi|market yard|mandi)\s*$', '', 'i'),
        '\s+', ' ', 'g')))                                                  AS market_std,
    coalesce(nullif(proper(variety), ''), 'Other')                          AS variety_std,
    coalesce(nullif(proper(grade), ''), 'FAQ')                              AS grade_std
FROM raw_prices r;

-- ---------- 3. price validity, units and outliers -------------------------
CREATE OR REPLACE TABLE stg_valid AS
WITH base AS (
    SELECT *,
           -- 3a. min > max reported the wrong way round -> swap
           CASE WHEN min_price > max_price THEN max_price ELSE min_price END AS min_p,
           CASE WHEN min_price > max_price THEN min_price ELSE max_price END AS max_p,
           min_price > max_price                                             AS fix_swapped_min_max
    FROM stg_named
    WHERE commodity_std IS NOT NULL
),
reference AS (
    -- typical modal price for the crop in that market and month, used to spot unit errors
    SELECT commodity_std, market_std, date_trunc('month', price_date) AS m,
           median(modal_price) AS ref_price
    FROM base WHERE modal_price > 0
    GROUP BY ALL
),
unit AS (
    SELECT b.*, rf.ref_price,
           -- 3b. a price ~100x off the month's typical level is a ₹/kg vs ₹/quintal slip
           CASE WHEN b.modal_price > 0 AND rf.ref_price > 0 AND b.modal_price * 100 BETWEEN rf.ref_price / 3 AND rf.ref_price * 3
                     AND b.modal_price < rf.ref_price / 30 THEN 100.0
                WHEN b.modal_price > 0 AND rf.ref_price > 0 AND b.modal_price / 100 BETWEEN rf.ref_price / 3 AND rf.ref_price * 3
                     AND b.modal_price > rf.ref_price * 30 THEN 0.01
                ELSE 1.0 END AS unit_factor
    FROM base b
    LEFT JOIN reference rf ON rf.commodity_std = b.commodity_std AND rf.market_std = b.market_std
                          AND rf.m = date_trunc('month', b.price_date)
)
SELECT *,
       modal_price * unit_factor                                    AS modal_p,
       min_p * unit_factor                                          AS min_p2,
       max_p * unit_factor                                          AS max_p2,
       unit_factor <> 1.0                                           AS fix_unit,
       -- 3c. unusable rows
       price_date IS NULL                                           AS flag_bad_date,
       price_date < DATE '2000-01-01' OR price_date > current_date  AS flag_date_out_of_range,
       coalesce(modal_price, 0) <= 0                                AS flag_no_price,
       market_std IS NULL OR market_std = ''                        AS flag_no_market
FROM unit;

-- ---------- 4. duplicates ---------------------------------------------------
-- Exact repeats (same market, crop, variety, grade, day and prices) are export noise.
-- Conflicting repeats (same key, different prices) are combined: median modal, widest range.
CREATE OR REPLACE TABLE stg_dedup AS
WITH usable AS (
    SELECT * FROM stg_valid
    WHERE NOT (flag_bad_date OR flag_date_out_of_range OR flag_no_price OR flag_no_market)
)
SELECT
    state_std AS state, district_std AS district, market_std AS market, commodity_std AS commodity,
    variety_std AS variety, grade_std AS grade, price_date,
    min(min_p2)                                         AS min_price,
    max(max_p2)                                         AS max_price,
    median(modal_p)                                     AS modal_price,
    max(arrivals_tonnes)                                AS arrivals_tonnes,
    count(*)                                            AS n_reports,
    count(DISTINCT modal_p)                             AS n_distinct_prices,
    bool_or(fix_unit)                                   AS fix_unit,
    bool_or(fix_swapped_min_max)                        AS fix_swapped_min_max,
    string_agg(DISTINCT source, ',')                    AS sources
FROM usable
GROUP BY ALL;

-- ---------- 5. outliers -------------------------------------------------------
-- Robust check against the market's own recent history: a modal price more than
-- 5 robust standard deviations (MAD-based, on the log scale) from the surrounding
-- 31-day median is flagged and excluded from analysis, not deleted.
CREATE OR REPLACE TABLE fact_price_report AS
WITH s AS (
    SELECT *, ln(modal_price) AS lp FROM stg_dedup
),
w AS (
    SELECT *,
           median(lp) OVER win                                        AS lp_med,
           count(*) OVER win                                          AS win_n
    FROM s
    WINDOW win AS (PARTITION BY market, commodity, variety ORDER BY price_date
                   RANGE BETWEEN INTERVAL 15 DAYS PRECEDING AND INTERVAL 15 DAYS FOLLOWING)
),
d AS (
    SELECT *, median(abs(lp - lp_med)) OVER win2 AS mad
    FROM w
    WINDOW win2 AS (PARTITION BY market, commodity, variety ORDER BY price_date
                    RANGE BETWEEN INTERVAL 15 DAYS PRECEDING AND INTERVAL 15 DAYS FOLLOWING)
)
SELECT
    md5(concat_ws('|', state, market, commodity, variety, grade, price_date)) AS report_id,
    state, district, market, commodity, variety, grade, price_date,
    round(min_price, 2) AS min_price, round(max_price, 2) AS max_price, round(modal_price, 2) AS modal_price,
    arrivals_tonnes, n_reports, n_distinct_prices, fix_unit, fix_swapped_min_max, sources,
    modal_price < min_price OR modal_price > max_price                        AS flag_modal_outside_range,
    win_n >= 7 AND abs(lp - lp_med) / greatest(1.4826 * coalesce(mad, 0), 0.05) > 5 AS flag_outlier
FROM d;

-- ---------- 6. analysis grain: one price per market, crop and day -------------
-- Varieties are combined using arrivals as weights where reported (otherwise a plain median),
-- excluding outliers.
CREATE OR REPLACE TABLE fact_market_day AS
SELECT
    state, district, market, commodity, price_date,
    round(CASE WHEN sum(arrivals_tonnes) > 0
               THEN sum(modal_price * arrivals_tonnes) / sum(arrivals_tonnes)
               ELSE median(modal_price) END, 2)          AS modal_price,
    round(min(min_price), 2)                              AS min_price,
    round(max(max_price), 2)                              AS max_price,
    sum(arrivals_tonnes)                                  AS arrivals_tonnes,
    count(*)                                              AS n_varieties
FROM fact_price_report
WHERE NOT flag_outlier
GROUP BY ALL;

-- ---------- 7. dimensions ------------------------------------------------------
CREATE OR REPLACE TABLE dim_market AS
SELECT md5(concat_ws('|', state, market)) AS market_id,
       state, any_value(district) AS district, market,
       min(price_date) AS first_report, max(price_date) AS last_report,
       count(DISTINCT price_date) AS days_reported,
       list_sort(list(DISTINCT commodity)) AS commodities
FROM fact_market_day
GROUP BY state, market;

CREATE OR REPLACE TABLE dim_date AS
SELECT d::DATE AS date, year(d) AS year, month(d) AS month, strftime(d, '%b') AS month_name,
       week(d) AS iso_week, dayofweek(d) AS dow,
       -- Indian crop seasons: kharif harvest arrives Oct–Jan, rabi Mar–Jun, late-kharif Jan–Mar
       CASE WHEN month(d) IN (10, 11, 12) THEN 'Kharif harvest'
            WHEN month(d) IN (1, 2) THEN 'Late kharif'
            WHEN month(d) IN (3, 4, 5, 6) THEN 'Rabi harvest'
            ELSE 'Lean season (Jul–Sep)' END AS crop_season
FROM range((SELECT min(price_date) FROM fact_market_day),
           (SELECT max(price_date) FROM fact_market_day) + INTERVAL 1 DAY, INTERVAL 1 DAY) t(d);

-- ---------- 8. data quality log ----------------------------------------------
CREATE OR REPLACE TABLE data_quality_log AS
SELECT * FROM (VALUES
    (1, 'Raw rows read', (SELECT count(*) FROM raw_prices)),
    (2, 'Rows for other commodities (out of scope)', (SELECT count(*) FROM stg_named WHERE commodity_std IS NULL)),
    (3, 'Rows with no usable date', (SELECT count(*) FROM stg_valid WHERE flag_bad_date OR flag_date_out_of_range)),
    (4, 'Rows with zero or missing price', (SELECT count(*) FROM stg_valid WHERE flag_no_price)),
    (5, 'Rows with no market name', (SELECT count(*) FROM stg_valid WHERE flag_no_market AND NOT flag_no_price)),
    (6, 'Prices fixed for a ₹/kg vs ₹/quintal slip', (SELECT count(*) FROM stg_valid WHERE fix_unit)),
    (7, 'Min and max price swapped', (SELECT count(*) FROM stg_valid WHERE fix_swapped_min_max)),
    (8, 'Duplicate reports merged', (SELECT coalesce(sum(n_reports - 1), 0) FROM stg_dedup)),
    (9, '…of which conflicting (different prices)', (SELECT count(*) FROM stg_dedup WHERE n_distinct_prices > 1)),
    (10, 'Modal price outside min–max range (kept, flagged)', (SELECT count(*) FROM fact_price_report WHERE flag_modal_outside_range)),
    (11, 'Outlier prices excluded from analysis', (SELECT count(*) FROM fact_price_report WHERE flag_outlier)),
    (12, 'Market names before standardisation', (SELECT count(DISTINCT market) FROM stg_named WHERE commodity_std IS NOT NULL)),
    (13, 'Market names after standardisation', (SELECT count(DISTINCT market_std) FROM stg_named WHERE commodity_std IS NOT NULL)),
    (14, 'Clean price reports', (SELECT count(*) FROM fact_price_report WHERE NOT flag_outlier)),
    (15, 'Market-crop-days in the analysis table', (SELECT count(*) FROM fact_market_day))
) t(step, check_name, rows_affected);
