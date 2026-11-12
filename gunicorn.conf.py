"""
Gunicorn configuration for the NEPSE API.

Start with:
    gunicorn stock_BE.wsgi:application -c gunicorn.conf.py

Scrapes run from systemd (`manage.py run_daily_scrape`), not inside HTTP
requests, so a worker should never be held for more than a couple of minutes.
See DEPLOYMENT.md.
"""
import os

bind = os.environ.get("GUNICORN_BIND", "127.0.0.1:8000")

# 3 workers x 4 threads is a reasonable default for a small VPS. Lower it if the
# box is short on RAM, especially while Chrome is running for scraping.
workers = int(os.environ.get("GUNICORN_WORKERS", "3"))
threads = int(os.environ.get("GUNICORN_THREADS", "4"))
worker_class = "gthread"

timeout = int(os.environ.get("GUNICORN_TIMEOUT", "120"))
graceful_timeout = int(os.environ.get("GUNICORN_GRACEFUL_TIMEOUT", "30"))
keepalive = 5

max_requests = int(os.environ.get("GUNICORN_MAX_REQUESTS", "1000"))
max_requests_jitter = 100

# Nginx is on the same host.
forwarded_allow_ips = "127.0.0.1"

accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info").lower()
