# Getting the data

MandiPulse uses **real wholesale prices reported by Indian mandis (APMC markets) to Agmarknet**, the
Government of India's agricultural marketing network. The raw files are not redistributed here until
they are downloaded; put them in `data/raw/` and run `python run_all.py`.

## Scope

| | |
|---|---|
| Commodities | Onion, Tomato, Potato |
| States | Maharashtra, Karnataka, Madhya Pradesh, Uttar Pradesh, Gujarat, Rajasthan |
| Period | 1 January 2019 to the latest available date |
| Fields needed | date, state, district, market, commodity, variety, min / max / modal price, arrivals (if available) |

## Option A (recommended): the CEDA Agri Market API, Ashoka University

CEDA republishes Agmarknet's daily, market-level prices from 2000 onwards (the latest months lag by a
few months). The API is free and the download script does everything:

1. Open <https://api.ceda.ashoka.edu.in>, enter your email, type the 6-digit OTP and click
   **Verify & Generate Key**.
2. Create a file called `.env` in the project folder containing one line (it is git-ignored, so the
   key is never pushed):

   ```
   CEDA_API_KEY=your-key-here
   ```

3. Run:

   ```powershell
   python src/fetch_ceda.py                       # 3 crops x 6 states, 2019 -> today
   python src/fetch_ceda.py --commodity Onion --state Maharashtra   # or a smaller test first
   ```

   Files are saved one crop, state and year at a time in `data/raw/ceda/`.

   The free API allows **40 requests an hour**, so the full download takes about a day or two of running
   (onion first, then tomato, then potato). When the hour's quota is used up the script waits for the
   next hour by itself. Every answer is cached in `data/interim/ceda_cache/`, so you can press Ctrl+C at
   any time and run the same command later: it continues where it stopped without repeating a request.
   If CEDA times out on a piece, the script notes it, carries on, and retries it on the next run.
   `--skip-arrivals` saves about a third of the requests but leaves out arrival quantities.

You can also download CSVs by hand from the CEDA portal (agmarknet.ceda.ashoka.edu.in): choose
**Daily** frequency and a single state or district so the file has one row per mandi, and save it in
`data/raw/ceda/`.

## Option B: Agmarknet price and arrival reports

1. On the Agmarknet portal, open the **Price and Arrivals** report.
2. Pick the commodity, state, "all markets" and a date range (the portal works best one year at a time).
3. Export to Excel and save the files in `data/raw/agmarknet/`. Agmarknet's `.xls` exports are often HTML
   tables in disguise; the loader handles both.

## Option C: recent days from the data.gov.in API

The data.gov.in Agmarknet API only serves the **current day**, so it is useful for topping up recent days,
not for history.

```powershell
set DATA_GOV_IN_API_KEY=your-key        # free key from data.gov.in (macOS/Linux: export ...)
python src/fetch_datagov.py
```

Files land in `data/raw/datagov/`.

## What the loader accepts

`src/ingest.py` reads every `.csv`, `.xlsx`, `.xls` and `.json` file under `data/raw/` (any sub-folder)
and recognises the column names used by all three sources, for example `Arrival_Date`, `Price Date`,
`Modal_x0020_Price`, `Modal Price (Rs./Quintal)`, `Arrivals (Tonnes)`. Prices quoted per kg are converted
to ₹ per quintal. If a file has a column layout it doesn't recognise, it stops and lists the columns it
found, so the mapping can be added in one line.

## File size

A full download for this scope is a few million rows. CSVs over GitHub's 100 MB limit should be split
by year or compressed (`.csv.gz` is read directly). After `python run_all.py`, the cleaned data is also
saved as compact Parquet in `data/interim/`.
