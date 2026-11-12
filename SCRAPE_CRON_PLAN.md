# Daily scrape cron/timer

## Goal

Run the three daily datasets after the market closes, verify that data actually landed,
retry failures, and alert when something is still missing.

```
indices (NepseIndex)  ->  today's price (StockData)  ->  floorsheet (FloorsheetData)
```

## Why not the HTTP curl endpoints

- All three endpoints require JWT + the `download` feature; the plain curls return 401.
- `SECURE_SSL_REDIRECT=True` in production redirects `http://localhost:8000` to HTTPS,
  which fails on the loopback address.
- Selenium runs for minutes (indices) to tens of minutes (floorsheet) inside a Gunicorn
  worker, risking timeouts and memory pressure.
- An HTTP 200 does not prove that rows were saved.

Cron therefore calls management commands. `deploy/scrape-http.sh` is kept as an optional
manual/debug fallback.

## Commands

Extended `run_scrape` (one-off / backfill):

```bash
manage.py run_scrape indices     --date 2026-11-05
manage.py run_scrape today-price --date 2026-11-06
manage.py run_scrape floorsheet  --source nepalstock --date 2026-11-06
```

New orchestrator (what cron runs):

```bash
manage.py run_daily_scrape                 # today in Asia/Kathmandu
manage.py run_daily_scrape --date 2026-11-05
manage.py run_daily_scrape --only indices,today-price
manage.py run_daily_scrape --allow-empty   # known holiday: no data is not a failure
```

## Behaviour

1. Resolve the date (default `timezone.localdate()` in `TIME_ZONE=Asia/Kathmandu`).
2. Skip weekends via `nepse_calendar.is_trading_day()` and dates listed in the
   `NEPSE_HOLIDAYS` env var (comma-separated `YYYY-MM-DD`).
3. Take a file lock (`SCRAPE_LOCK_FILE`, default `/tmp/nepse-scrape.lock`) so the
   18:00/20:00/22:00 runs cannot overlap.
4. Run each task with up to `--attempts` (default 3) and backoff 30s / 2min / 5min.
5. Continue to the next task if one fails, so partial data is still saved.
6. **Verify against the database**, not the scraper's own return value:
   - `NepseIndex(date=D).exists()`
   - `StockData(date=D).count() >= MIN_STOCK_DATA_ROWS` (default 100)
   - `FloorsheetData(transaction_date=D).exists()`
   If the rows are already present (rerun / earlier run), the task counts as satisfied
   even if this attempt failed. This makes repeated runs cheap and safe.
7. Print a summary table and exit non-zero if any task is still unsatisfied.
8. On failure, POST the summary to `SCRAPE_ALERT_WEBHOOK` (Slack/Telegram/Discord
   compatible JSON). On success, optionally GET `SCRAPE_HEALTHCHECK_URL`.

## Fallbacks

| Task | Primary | Fallback |
|---|---|---|
| Indices | nepalstock | retry in the 20:00/22:00 slot |
| Today's Price | nepalstock | retry; later run picks up data published late |
| Floorsheet | nepalstock bulk | retry; manual per-symbol backfill via `run_scrape floorsheet --source merolagani` |

A merolagani fallback for the whole market would mean one browser run per symbol and is
not practical in a daily job; it stays a manual backfill.

## Schedule

| Time (Asia/Kathmandu) | Purpose |
|---|---|
| 18:00 Mon-Fri | main run |
| 20:00 Mon-Fri | retry anything still missing |
| 22:00 Mon-Fri | final safety net |

Preferred scheduler: systemd timer (`deploy/nepse-scrape.timer`) with `Persistent=true`
and journald logs. A crontab equivalent is documented for simple setups.

## Files

- `stock_data/scraping_jobs.py` — reusable job functions + DB verification.
- `stock_data/management/commands/run_scrape.py` — extended with `indices`, `--date`.
- `stock_data/management/commands/run_daily_scrape.py` — orchestrator.
- `deploy/nepse-scrape.service`, `deploy/nepse-scrape.timer` — systemd.
- `deploy/scrape-http.sh` — optional HTTP fallback.
- `DEPLOYMENT.md` — install/run section.

## Decisions taken (defaults)

- Scheduler: systemd timer; cron example included.
- Alerting: webhook, env-configured; no mail dependency.
- Empty result on a weekday: **failure** unless `--allow-empty` or the date is in
  `NEPSE_HOLIDAYS`.
- Floorsheet fallback: retry only; manual merolagani backfill documented.
- Primary execution path: `manage.py`; HTTP script only as a fallback.
