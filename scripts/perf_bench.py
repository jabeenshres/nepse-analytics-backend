"""
Quick API benchmark: latency, query count and response size per endpoint.

Run from the backend directory:

    python manage.py shell -c "exec(open('scripts/perf_bench.py').read())"

The first call to each endpoint is a warm-up (it may populate caches); the
reported numbers come from the second call. Uses the first superuser by default;
override with PERF_USER=<username>.
"""
import json
import os
import time

from django.contrib.auth import get_user_model
from django.db import connection, reset_queries
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

U = get_user_model()
username = os.environ.get('PERF_USER')
user = (
    U.objects.get(username=username) if username
    else U.objects.filter(is_superuser=True).first()
)
if user is None:
    raise SystemExit('No superuser found; set PERF_USER=<username>')

client = APIClient()
client.force_authenticate(user=user)
client.raise_request_exception = False

# Fetch one stock id that has history, for the detail endpoint.
from stock_data.models import StockData  # noqa: E402
from django.db.models import Count  # noqa: E402

richest = (
    StockData.objects.values('stock_id')
    .annotate(n=Count('id'))
    .order_by('-n')
    .first()
)
stock_id = richest['stock_id'] if richest else 1

PATHS = [
    ('latest', '/api/stock-data/latest/?page_size=20&stock_type=stock'),
    ('latest gainers', '/api/stock-data/latest/?gainer=1&page_size=5&stock_type=stock'),
    ('stock list', '/api/stock-data/?page=1&stock_type=stock'),
    ('stock detail', f'/api/stock-data/{stock_id}/'),
    ('indices list', '/api/stock-data/indices/list/'),
    ('indices data', '/api/stock-data/indices/data/?index_id=58&limit=1'),
    ('indices analysis', '/api/stock-data/indices/analysis/?index_id=58&days=30'),
    ('indices compare', '/api/stock-data/indices/compare/?index_ids=58,51,54,55,65,59&days=30'),
    ('top stocks', '/api/stock-data/analysis/top-stocks/?limit=6&min_score=40&stock_type=stock'),
    ('breakout', '/api/stock-data/analysis/breakout-watchlist/?stock_type=stock'),
    ('accumulation', '/api/stock-data/analysis/accumulation-alerts/?alert_level=high&stock_type=stock'),
    ('screener', '/api/stock-data/analysis/screener/?type=oversold&limit=5&stock_type=stock'),
    ('signals', '/api/stock-data/analysis/signals/?symbol=AKJCL'),
    ('indicators', '/api/stock-data/analysis/indicators/?symbol=AKJCL&days=30'),
    ('broker holdings', '/api/stock-data/floorsheet/broker-holdings/?symbol=KKHC&sort_by=net&limit=50'),
    ('floorsheet analysis', '/api/stock-data/floorsheet/analysis/?symbol=KKHC'),
    ('accounts me', '/api/accounts/me/'),
    ('users', '/api/accounts/users/'),
]


def call(path):
    reset_queries()
    started = time.perf_counter()
    with CaptureQueriesContext(connection) as ctx:
        response = client.get(path, HTTP_HOST='localhost')
    elapsed = (time.perf_counter() - started) * 1000
    return response, len(ctx), elapsed


print('%-20s %5s %8s %9s %10s %8s' % (
    'endpoint', 'code', 'queries', 'total_ms', 'bytes', 'note'))
print('-' * 70)

for label, path in PATHS:
    client.get(path, HTTP_HOST='localhost')  # warm-up
    response, queries, elapsed = call(path)
    size = len(response.content)
    note = ''
    if response.status_code >= 400:
        try:
            note = json.dumps(response.json())[:60]
        except Exception:
            note = 'error page'
    print('%-20s %5s %8d %9.1f %10d  %s' % (
        label, response.status_code, queries, elapsed, size, note))
