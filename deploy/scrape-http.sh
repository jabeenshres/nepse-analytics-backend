#!/usr/bin/env bash
#
# OPTIONAL HTTP fallback for the daily scrape.
#
# Prefer `manage.py run_daily_scrape` (deploy/nepse-scrape.timer): it verifies the
# database, retries, and does not tie up a Gunicorn worker. Use this script only for
# manual runs or when the app server must be driven remotely.
#
# Requires a dedicated account with the `download` feature (manager or admin):
#
#   SCRAPE_USER=scraper SCRAPE_PASSWORD='...' API_BASE=https://api.nepse.raijintech.com \
#     ./scrape-http.sh 2026-11-05
#
# Exits non-zero on the first HTTP or JSON failure.

set -euo pipefail

API_BASE="${API_BASE:-https://api.nepse.raijintech.com}"
SCRAPE_USER="${SCRAPE_USER:?set SCRAPE_USER}"
SCRAPE_PASSWORD="${SCRAPE_PASSWORD:?set SCRAPE_PASSWORD}"
TARGET_DATE="${1:-$(date +%F)}"

json_get_access() {
  python3 -c 'import json,sys; print(json.load(sys.stdin)["access"])'
}

TOKEN=$(curl -fsS -X POST "$API_BASE/api/accounts/token/" \
  -H 'Content-Type: application/json' \
  -d "{\"username\":\"${SCRAPE_USER}\",\"password\":\"${SCRAPE_PASSWORD}\"}" \
  | json_get_access)

call() {
  local name="$1"
  local path="$2"
  local body="$3"
  local response

  echo "== ${name} (${TARGET_DATE}) =="
  if ! response=$(curl -fsS --max-time 7200 -X POST "${API_BASE}${path}" \
      -H 'Content-Type: application/json' \
      -H "Authorization: Bearer ${TOKEN}" \
      -d "${body}"); then
    echo "ERROR: ${name} request failed" >&2
    return 1
  fi

  echo "${response}"
}

call indices /api/stock-data/indices/scrape/ \
  "{\"target_date\":\"${TARGET_DATE}\"}" || exit 1

call today-price /api/stock-data/fetch/ \
  "{\"date_from\":\"${TARGET_DATE}\",\"date_to\":\"${TARGET_DATE}\",\"save_to_db\":true,\"headless\":true}" \
  || exit 1

call floorsheet /api/stock-data/floorsheet/nepalstock-scrape/ \
  '{"save_to_db":true,"headless":true}' || exit 1

echo "All requests completed. Check the backend response bodies above for zero-row results."
