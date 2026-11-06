# `/api/stock-data/fetch/` — headless table scraping

## Goal

Make `POST /api/stock-data/fetch/` behave like the working `/nepalstock-scrape/`
endpoint: run Chrome headless, and for every date in the requested range press the
page's **Filter** button and scrape the rendered `today-price` table directly.

## Why it currently fails

1. `LoadStockDataView` (`stock_data/views.py:235`) calls `NepalStockScraper()` and never
   reads `"headless"` from the request body, so the flag is silently ignored.
2. `NepalStockScraper.__init__` (`stock_data/utils.py:29`) has no `headless` parameter
   and always launches a visible browser.
3. `loop_through_date_range` (`stock_data/utils.py:209`) does not scrape the table at
   all. It clicks `.table__file` to download a CSV, waits for a file in a temp dir, and
   parses that. Headless Chrome downloads are the fragile part.

## Page facts (verified against `today_price.html`)

| Item | Value |
|---|---|
| Date input | `input[bsdatepicker]` |
| Filter button | `button.box__filter--search` |
| Table | one `<table>`; **defaults to 20 rows across 18 pages** |
| Page size control | `<select>` in the filter bar: 10 / 20 / 50 / 200 / 300 / 500 |
| Pagination | `ul.ngx-pagination` with `li.pagination-next` |
| Quirk | LTP renders as `836.70 (-8.3)`; the change must be stripped |

The saved `today_price.html` showed 349 rows because it was captured with the
page-size select already at 500. A fresh load shows 20 rows over 18 pages, which is
why the first live run only parsed 40 rows for two dates. The scraper must raise the
page size (and still page through as a safety net).

Header mapping:

| HTML header | Field |
|---|---|
| Symbol | symbol (uppercase) |
| Close Price* | `close_price` |
| Open / High / Low Price | `open_price` / `high_price` / `low_price` |
| Total Traded Quantity | `total_traded_quantity` |
| Total Traded Value | `total_traded_value` |
| Total Trades | `total_trades` |
| LTP | `last_updated_price` |
| Previous Day Close Price | `previous_day_close_price` |
| Average Traded Price | `average_traded_price` |
| 52 Week High / Low | ignored (see note) |
| MarketCapitalization | `market_capitalization` |

52-week high/low are **not** written to `Stock`: the table shows them as of the
selected historical date, so writing them would overwrite the current values.

## Decisions

- Headless defaults to **true**; override with `"headless": false`.
- Table scraping only. The CSV download block is **commented out**, not deleted.
- Symbols absent from the `Stock` table are skipped and reported in the response.
- Non-trading days are skipped using `stock_data/nepse_calendar.py`.

## Changes

### 1. `stock_data/utils.py` — `NepalStockScraper`

- `__init__(self, headless: bool = True)` mirroring `NepalstockFloorsheetScraper`'s
  options: `--headless=new`, `--no-sandbox`, `--disable-dev-shm-usage`,
  `--disable-gpu`, `--window-size=1920,1080`, automation flags, user agent.
- `_table_signature()` / `_wait_for_table_refresh()` — poll until the table body
  actually changes after Filter instead of a fixed `sleep(3)`.
- `change_date()` — keep the working selectors, add a JS `value` + `change` fallback
  and a single retry when the table does not refresh.
- `parse_today_price_html(html, selected_date)` (classmethod, Selenium-free) and
  `parse_today_price_table(selected_date)` wrapper.
- `_set_items_per_page(500)` — raises the page size from 20 so one trading day fits
  on a single page.
- `scrape_all_today_price_pages()` — parses the current page, then follows
  `li.pagination-next` until exhausted, de-duplicating by symbol.
- `save_today_price_rows(rows, selected_date, Stock, StockData)` — resolve symbols,
  skip existing `(stock, date)`, `bulk_create(ignore_conflicts=True)`, report
  unresolved symbols.
- `trading_days_between(date_from, date_to)` helper.
- `loop_through_date_range` rewritten to: compute trading days, filter each one, parse
  the table, save. CSV block commented out with a note.
- Keep the `statistics` keys the frontend reads (`total_dates`, `dates_processed`,
  `dates_skipped`, `dates_failed`) and add `trading_days`, `rows_parsed`,
  `rows_created`, `rows_skipped`, `unresolved_symbols`.

### 2. `stock_data/views.py` — `LoadStockDataView`

- Read `headless` from the body (default `True`, accept `"true"/"false"` strings).
- Pass it to `NepalStockScraper(headless=...)`.
- Include `unresolved_symbols` in the response.

### 2b. Console progress (`print` alongside `logger`)

Django has no `LOGGING` config here, so `logger.info` never reaches the terminal and
runs looked silent. Progress is now printed directly:

- browser start/close and page load
- date filter result, table refresh, rows per page
- per-date save summary (`new` / `already existed` / `errors` / unknown symbols)
- a final block with dates processed/skipped/failed and row totals
- when `save_to_db` is false the summary says `Saving: disabled` instead of
  reporting a misleading zero

### 3. `stock_data/tests.py`

- Parser tests with an inline HTML fixture: row count, LTP paren-stripping, blank rows.
- Idempotency: saving the same day twice creates 0 the second time.
- Unresolved symbol is reported, not raised.
- `trading_days_between('2026-10-02', '2026-10-05')` returns only Oct 2 and Oct 5.

### 4. Verification

Run the real request headless:

```
POST /api/stock-data/fetch/
{"date_from":"2026-10-02","date_to":"2026-10-05","save_to_db":true,"headless":true}
```

Expect `total_dates: 4`, `trading_days: 2`, `dates_processed: 2`,
`dates_skipped: 2`, and spot-check ADBL against the saved HTML.

### Result

- `2026-10-02 -> 2026-10-05`: `rows_parsed: 715`, `rows_created: 0`,
  `rows_skipped: 709`, `unresolved_symbols: 4` (those dates already existed).
- `2026-10-06`: `rows_parsed: 359`, `rows_created: 355`, `rows_skipped: 0`,
  `unresolved_symbols: 4` — proves the insert path works.
- Full suite: **84 tests pass**.

## Known limitation

`Stock.security_id` is unique and non-null, and the today-price table has no security
id. Five symbols in the sample are not in the database and cannot be created safely:

```
BENH, EBLEB89, GBBD85, GBILD84/85, PBD93
```

They are listed in `unresolved_symbols` instead of being dropped silently.
