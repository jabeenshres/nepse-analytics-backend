# Fix NEPSE weekend logic (Friday+Saturday -> Saturday+Sunday)

## Problem

`MerolaganiFloorsheetScraper._get_dates_in_range()` hardcoded **Friday and Saturday**
as the weekend:

```python
if weekday == 4:  # Friday   -> skipped
elif weekday == 5:  # Saturday -> skipped
```

That was correct until NEPSE changed its trading week.

## What changed at NEPSE

| Date | Event |
|------|-------|
| 2026-04-05 | Cabinet decided Sat + Sun are weekly public holidays; NEPSE board (Chait 22) resolved to align |
| 2026-04-05 (Sun) | **Traded** - last day of the old Sun-Thu week |
| 2026-04-06 (Mon) | First day of the new Mon-Fri schedule |
| 2026-04-10 (Fri) | **Traded** - transition week ran Mon-Fri (6 trading days that week incl. Sun Apr 5) |
| 2026-04-13 (Mon) | First full regular Mon-Fri week |

- Before: trading **Sun-Thu**, weekend = **Fri + Sat**
- From 2026-04-06: trading **Mon-Fri**, weekend = **Sat + Sun**

Cutoff is **2026-04-06**, not 2026-04-13. Both produce the same total count, so the
difference is invisible in the summary line, but with a 04-13 cutoff the scraper would
**drop Friday 2026-04-10** (which traded) and **scrape Sunday 2026-04-12** (which did not).

## Impact on the request range 07/01/2025 -> 11/06/2026

494 calendar days.

| Rule | Kept | Skipped |
|------|------|---------|
| Current (always Fri+Sat) | 353 | 141 (71 Fri + 70 Sat) |
| Fixed (cutoff 2026-04-06) | 354 | 140 (70 Sat + 29 Sun + 41 pre-cutoff Fri) |

Net **+1** date only: 30 post-cutoff Fridays are recovered and 29 post-cutoff Sundays are
dropped. The point of the fix is correctness, not volume.

## Changes

### 1. New `stock_data/nepse_calendar.py` (new file)

Single source of truth shared by the scraper and the recommendation logic so the two
cannot drift apart again.

```python
NEPSE_MON_FRI_START = date(2026, 4, 6)

def weekend_weekdays(d: date) -> tuple          # (4, 5) before cutoff, else (5, 6)
def is_trading_day(d: date) -> bool             # weekend check only, no holidays
def next_trading_day(d: date, n: int = 1) -> date
def today_or_clamp(d: date) -> date
```

Documented limitation: **Nepali public holidays (Bikram Sambat calendar) are not
modeled.** `is_trading_day()` over-reports on holidays; those dates yield empty pages,
exactly as they do today. Out of scope.

### 2. `stock_data/floorsheet_scraper.py`

- `_get_dates_in_range()` (line 1887) - replace the `weekday == 4 / == 5` branches with
  `is_trading_day(current)`. Update the docstring, which currently states
  "Skips weekends (Friday and Saturday)".
- Clamp `date_to` to today via `today_or_clamp()` and log a warning when clamped.
  `11/06/2026` is 31 days after today (2026-10-06), so ~24 trading days were being
  scraped for nothing.
- Log line 1731: `weekend_count` is computed as `total - len(dates_to_scrape)`, which
  silently absorbs the clamp. Recompute against the clamped range so the number is honest.

### 3. `stock_data/unusual_activity_views.py`

`_get_settlement_info()` (line 2168) hardcoded a `settlement_map` for the old Sun-Thu
week, including a `trading_days_wait: 3  # Friday gap` fudge. Replace with a
`next_trading_day(today, 2)` computation and derive `buy_day` / `available_day` from the
result. Fix the stale comment at line 2171.

### 4. Tests in `stock_data/tests.py`

- `is_trading_day` boundaries: 2026-04-03 (Fri, closed), 2026-04-05 (**Sun, open**),
  2026-04-06 (open), 2026-04-10 (**Fri, open**), 2026-04-12 (Sun, closed), 2026-04-13 (open).
- `_get_dates_in_range` over a small fixed range: exact list and count.
- Clamp: a future `date_to` returns a list ending today.
- `next_trading_day` skips Sat+Sun after the cutoff.

## Verification

- Run the new tests.
- Regression check against `db.sqlite3`: stored floorsheet data has **zero** Friday and
  Saturday rows and spans only 2025-10-30 .. 2026-02-05 (entirely pre-transition), so the
  fix is backward compatible with existing rows.
- Dry-run the real range and confirm 354 dates, with 04/10/2026 present and 04/12/2026 absent.

## Not addressed here

- **`curl: (52) Empty reply from server`** - caused by `^C` killing the Django dev server
  mid-request, not by a code defect. The underlying problem is real though: the scrape is
  a fully synchronous multi-hour HTTP request (`floorsheet_views.py:114`; there is no
  Celery in the project). Worth a follow-up to expose it as a management command or
  background job with pollable progress.
- **Nepali public holidays** - not modeled, out of scope.
- **Pagination warning** seen in the scrape log ("Page 4: Processing overlay did not
  disappear within 10 seconds", then "no new transactions (possible duplicate page)"):
  `floorsheet_scraper.py:1068` passes `timeout=10` against a class default of
  `PROCESSING_OVERLAY_WAIT_TIMEOUT = 15`. Separate issue, left alone.
- **Pre-2026 Fridays traded odd lots only.** The DB has 0 Friday rows, but that is
  inconclusive since the scraper skips Fridays regardless. If merolagani exposes odd-lot
  rows per symbol, there may be a gap between 2025-07 and 2026-04. Needs a one-off
  spot-check of a single symbol's Friday floorsheet.