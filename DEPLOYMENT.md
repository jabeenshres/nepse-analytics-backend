# Production deployment (VPS)

Target layout:

| Component | Domain | Process |
|---|---|---|
| Django API | `https://api.nepse.raijintech.com` | Gunicorn on `127.0.0.1:8000` |
| Next.js frontend | `https://nepse.raijintech.com` | `next start` on `127.0.0.1:3000` |
| Nginx | both domains | TLS termination, reverse proxy |
| Database | local | PostgreSQL (recommended) or SQLite |

Example paths used below:

```
/srv/nepse/stock_BE     # backend repo
/srv/nepse/Stock_FE     # frontend repo
/srv/nepse/venv         # python virtualenv
/srv/nepse/scripts      # cron helper scripts
```

Assumptions: Ubuntu 22.04/24.04, `nepse` system user, 2 GB RAM minimum
(headless Chrome is the heaviest part of the stack).

---

## 1. DNS

Create these `A` records pointing at the VPS public IP:

```
api.nepse.raijintech.com   A   <VPS_IP>
nepse.raijintech.com       A   <VPS_IP>
```

Wait for propagation (`dig +short api.nepse.raijintech.com`).

---

## 2. Server preparation

```bash
sudo adduser --system --group --home /srv/nepse nepse
sudo mkdir -p /srv/nepse /var/log/nepse
sudo chown -R nepse:nepse /srv/nepse /var/log/nepse

sudo apt update && sudo apt upgrade -y
sudo apt install -y \
  python3 python3-venv python3-pip python3-dev \
  build-essential libpq-dev \
  nginx certbot python3-certbot-nginx \
  git curl unzip sqlite3 \
  libnss3 libatk-bridge2.0-0 libgtk-3-0 libgbm1 libasound2

# Correct clock/timezone for the scraper and logs
sudo timedatectl set-timezone Asia/Kathmandu
```

Install Node.js 20 LTS (NodeSource):

```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
node -v && npm -v
```

---

## 3. Database

### Option A — PostgreSQL (recommended)

```bash
sudo apt install -y postgresql postgresql-contrib
sudo -u postgres psql <<'SQL'
CREATE USER nepse WITH PASSWORD 'CHANGE_ME';
CREATE DATABASE nepse OWNER nepse;
GRANT ALL PRIVILEGES ON DATABASE nepse TO nepse;
SQL
```

Then in `/srv/nepse/stock_BE/.env`:

```
DB_ENGINE=postgresql
DB_NAME=nepse
DB_USER=nepse
DB_PASSWORD=CHANGE_ME
DB_HOST=127.0.0.1
DB_PORT=5432
```

### Option B — keep SQLite

Works for a small single-instance deployment. Enable WAL once and reduce
Gunicorn workers to 2 (`GUNICORN_WORKERS=2`):

```bash
sqlite3 /srv/nepse/stock_BE/db.sqlite3 'PRAGMA journal_mode=WAL;'
```

Set `DB_ENGINE=sqlite3` and `SQLITE_TIMEOUT=30` in `.env`.

### Moving existing SQLite data to PostgreSQL

For the current ~1.1M-row database, `dumpdata` is large but works:

```bash
cd /srv/nepse/stock_BE
# before switching DB_ENGINE, dump from SQLite
/srv/nepse/venv/bin/python manage.py dumpdata \
  --natural-foreign --natural-primary \
  -e contenttypes -e auth.permission \
  -o /srv/nepse/nepse-dump.json

# after setting DB_ENGINE=postgresql and running migrate
/srv/nepse/venv/bin/python manage.py loaddata /srv/nepse/nepse-dump.json
```

Run this inside `tmux`/`screen`; it can take several minutes. `pgloader` is faster
but needs manual schema handling, so `dumpdata` is the safer path.

---

## 4. Backend deployment

```bash
sudo -u nepse -H bash
cd /srv/nepse
git clone <BACKEND_REPO_URL> stock_BE
python3 -m venv /srv/nepse/venv
/srv/nepse/venv/bin/pip install --upgrade pip wheel
/srv/nepse/venv/bin/pip install -r /srv/nepse/stock_BE/requirements.txt
exit
```

Create the environment file:

```bash
sudo -u nepse cp /srv/nepse/stock_BE/.env.example /srv/nepse/stock_BE/.env
sudo -u nepse nano /srv/nepse/stock_BE/.env
```

Minimum production values:

```
DEBUG=False
SECRET_KEY=<64-char random string>
ALLOWED_HOSTS=api.nepse.raijintech.com
DJANGO_ADMIN_URL=manage-<random>/
CORS_ALLOWED_ORIGINS=https://nepse.raijintech.com
CSRF_TRUSTED_ORIGINS=https://api.nepse.raijintech.com
SECURE_SSL_REDIRECT=True
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
DB_ENGINE=postgresql
...
```

Generate the secret:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(64))"
```

Migrate, collect static, create the first admin:

```bash
cd /srv/nepse/stock_BE
sudo -u nepse /srv/nepse/venv/bin/python manage.py migrate
sudo -u nepse /srv/nepse/venv/bin/python manage.py collectstatic --noinput
sudo -u nepse /srv/nepse/venv/bin/python manage.py createsuperuser
sudo -u nepse /srv/nepse/venv/bin/python manage.py check --deploy
```

Smoke-test Gunicorn before wiring systemd:

```bash
sudo -u nepse bash -c 'cd /srv/nepse/stock_BE && /srv/nepse/venv/bin/gunicorn stock_BE.wsgi:application -c gunicorn.conf.py'
# in another shell
curl -I http://127.0.0.1:8000/api/accounts/token/
# Ctrl+C to stop
```

Install the service:

```bash
sudo cp /srv/nepse/stock_BE/deploy/nepse-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now nepse-api
sudo systemctl status nepse-api
sudo journalctl -u nepse-api -f
```

---

## 5. Nginx + TLS

```bash
sudo cp /srv/nepse/stock_BE/deploy/nginx-limits.conf /etc/nginx/conf.d/nepse-limits.conf
sudo cp /srv/nepse/stock_BE/deploy/nginx-api.conf /etc/nginx/sites-available/api.nepse.raijintech.com
sudo cp /srv/nepse/stock_BE/deploy/nginx-web.conf /etc/nginx/sites-available/nepse.raijintech.com
sudo ln -sf /etc/nginx/sites-available/api.nepse.raijintech.com /etc/nginx/sites-enabled/
sudo ln -sf /etc/nginx/sites-available/nepse.raijintech.com /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx
```

Issue certificates:

```bash
sudo certbot --nginx -d api.nepse.raijintech.com -d nepse.raijintech.com
```

Certbot rewrites the `listen 443` blocks it finds. Verify auto-renewal:

```bash
sudo certbot renew --dry-run
```

The API config already throttles `/api/accounts/token/` and `/admin/login/`
(5 requests/minute per IP). Adjust `deploy/nginx-limits.conf` if needed.

---

## 6. Frontend deployment

`.env.production` in the repo already contains:

```
NEXT_PUBLIC_BASE_URL=https://api.nepse.raijintech.com/
```

Keep the trailing slash — the code concatenates paths directly.

```bash
sudo -u nepse -H bash
cd /srv/nepse
git clone <FRONTEND_REPO_URL> Stock_FE
cd Stock_FE
npm ci
npm run build
exit
```

> `NEXT_PUBLIC_BASE_URL` is baked in at build time. If the API domain changes,
> rebuild the frontend.

Install the service:

```bash
sudo cp /srv/nepse/stock_BE/deploy/nepse-web.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now nepse-web
sudo systemctl status nepse-web
sudo journalctl -u nepse-web -f
```

If `npm` is not at `/usr/bin/npm`, update `ExecStart` in the unit file.

---

## 7. Chrome for scraping

The scrapers drive headless Chrome:

```bash
# Google Chrome (recommended)
wget -q -O /tmp/chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
sudo apt install -y /tmp/chrome.deb

# sanity check
google-chrome --version
```

`stock_data/floorsheet_scraper.py` auto-downloads a matching ChromeDriver into
`~/.cache/selenium/chromedriver`, so no manual driver install is required. The
scraper already passes `--no-sandbox`; do not run Chrome as root.

Give the `nepse` user a writable cache (`/srv/nepse/.cache`) — the system user
created above has one.

---

## 8. Scheduled scrapes

Long Selenium runs must not go through the web worker. `run_daily_scrape` runs the
three datasets in order, retries, verifies the database, and exits non-zero on failure.

Order: `indices` → `today-price` → `floorsheet`.

### systemd timer (recommended)

```bash
sudo cp /srv/nepse/stock_BE/deploy/nepse-scrape.service /etc/systemd/system/
sudo cp /srv/nepse/stock_BE/deploy/nepse-scrape.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now nepse-scrape.timer
systemctl list-timers nepse-scrape.timer
journalctl -u nepse-scrape.service -f
```

Runs Mon-Fri at 18:00, 20:00 and 22:00 Asia/Kathmandu. Later runs are cheap: the
command only fills dates that are still missing.

Useful environment variables in `.env`:

```
NEPSE_HOLIDAYS=2026-10-20,2026-10-21   # dates to skip (market holidays)
MIN_STOCK_DATA_ROWS=100                 # rows needed to consider today-price complete
SCRAPE_ALERT_WEBHOOK=https://hooks.slack.com/...   # optional failure alert
SCRAPE_HEALTHCHECK_URL=https://hc-ping.com/...     # optional success ping
SCRAPE_LOCK_FILE=/tmp/nepse-scrape.lock

# File-based response cache (no Redis required)
CACHE_DIR=/srv/nepse/stock_BE/var/cache
CACHE_TIMEOUT=300
```

Create the cache directory once, owned by the service user:

```bash
sudo install -d -o nepse -g nepse -m 750 /srv/nepse/stock_BE/var/cache
```

`run_daily_scrape` clears this cache and precomputes analytics when it finishes.
To warm it manually (for example after deploying):

```bash
sudo -u nepse -H bash -lc 'cd /srv/nepse/stock_BE && set -a; . ./.env; set +a; \
  /srv/nepse/venv/bin/python manage.py warm_analytics'
```

Manual runs:

```bash
cd /srv/nepse/stock_BE
/srv/nepse/venv/bin/python manage.py run_daily_scrape --dry-run
/srv/nepse/venv/bin/python manage.py run_daily_scrape --date 2026-11-05
/srv/nepse/venv/bin/python manage.py run_daily_scrape --only indices,today-price
```

### cron alternative

```cron
30 18 * * 1-5 cd /srv/nepse/stock_BE && /srv/nepse/venv/bin/python manage.py run_daily_scrape >> /var/log/nepse/scrape.log 2>&1
30 20 * * 1-5 cd /srv/nepse/stock_BE && /srv/nepse/venv/bin/python manage.py run_daily_scrape >> /var/log/nepse/scrape.log 2>&1
30 22 * * 1-5 cd /srv/nepse/stock_BE && /srv/nepse/venv/bin/python manage.py run_daily_scrape >> /var/log/nepse/scrape.log 2>&1
```

### One-off / backfill

```bash
manage.py run_scrape indices     --date 2026-11-05
manage.py run_scrape today-price --date 2026-11-06
manage.py run_scrape floorsheet  --source nepalstock --date 2026-11-06
manage.py run_scrape floorsheet  --source merolagani --symbol AKJCL --from 2026-11-01 --to 2026-11-09
manage.py run_scrape floorsheet  --source merolagani --symbols AKJCL,NABIL --from 2026-11-01 --to 2026-11-09
```

### HTTP fallback

`deploy/scrape-http.sh` logs in and calls the endpoints directly. It exists only for
manual use — it still occupies a Gunicorn worker and needs a service account with the
`download` feature:

```bash
SCRAPE_USER=scraper SCRAPE_PASSWORD='...' API_BASE=https://api.nepse.raijintech.com \
  /srv/nepse/stock_BE/deploy/scrape-http.sh 2026-11-05
```

---

## 9. Firewall

```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable
sudo ufw status
```

Ports 8000 and 3000 stay bound to `127.0.0.1`; never expose them publicly.

Optional brute-force protection:

```bash
sudo apt install -y fail2ban
sudo systemctl enable --now fail2ban
```

---

## 10. Backups

PostgreSQL:

```bash
sudo -u postgres pg_dump nepse | gzip > /var/backups/nepse-$(date +%F).sql.gz
```

SQLite:

```bash
sqlite3 /srv/nepse/stock_BE/db.sqlite3 ".backup '/var/backups/nepse-$(date +%F).sqlite3'"
```

Cron it daily and copy off-site (rclone/S3). Keep at least 7 days. Test a restore
once before going live.

Also back up `/srv/nepse/stock_BE/.env` (it contains the secret key and DB password).

---

## 11. Security checklist

- [ ] `DEBUG=False`
- [ ] strong random `SECRET_KEY` (the server refuses to boot otherwise)
- [ ] `ALLOWED_HOSTS` contains only the API hostname
- [ ] `CORS_ALLOWED_ORIGINS=https://nepse.raijintech.com` (no wildcard)
- [ ] `CSRF_TRUSTED_ORIGINS=https://api.nepse.raijintech.com`
- [ ] `SECURE_SSL_REDIRECT`, secure cookies, HSTS enabled (defaults when `DEBUG=False`)
- [ ] `DJANGO_ADMIN_URL` changed from `admin/` to a random path
- [ ] HTTPS via Certbot; `certbot renew --dry-run` passes
- [ ] login endpoint rate-limited in Nginx
- [ ] `ufw` enabled; 8000/3000 not public
- [ ] PostgreSQL only listens on localhost (`listen_addresses = 'localhost'`)
- [ ] DB and `.env` are not in git (`git rm --cached db.sqlite3` if it was committed)
- [ ] daily backups configured and restore tested
- [ ] `python manage.py check --deploy` reports no issues
- [ ] `/api/accounts/register/` is still public — gate it to admins if the platform
      should be invite-only (`accounts/views.py`, `RegisterUserView.permission_classes`)

---

## 12. Updating the app

```bash
# backend
cd /srv/nepse/stock_BE
sudo -u nepse git pull
sudo -u nepse /srv/nepse/venv/bin/pip install -r requirements.txt
sudo -u nepse /srv/nepse/venv/bin/python manage.py migrate
sudo -u nepse /srv/nepse/venv/bin/python manage.py collectstatic --noinput
sudo systemctl restart nepse-api

# frontend
cd /srv/nepse/Stock_FE
sudo -u nepse git pull
sudo -u nepse npm ci
sudo -u nepse npm run build
sudo systemctl restart nepse-web
```

---

## 13. Verification

```bash
# API reachable and redirecting correctly
curl -I https://api.nepse.raijintech.com/api/accounts/token/
# expect 405/400 (GET on a POST endpoint), NOT 502/504

# Frontend
curl -I https://nepse.raijintech.com/Login
# expect 200

# Protected route without a token
curl -I https://api.nepse.raijintech.com/api/stock-data/
# expect 401

# Login
curl -X POST https://api.nepse.raijintech.com/api/accounts/token/ \
  -H 'Content-Type: application/json' \
  -d '{"username":"<admin>","password":"<password>"}'
# expect access/refresh/role/features

# Admin page
open https://api.nepse.raijintech.com/manage-<random>/
```

In the browser, log in at `https://nepse.raijintech.com/Login`, confirm the sidebar
matches the role matrix, and check the browser console/network for CORS errors.

---

## 14. Known production limitations

- **Token exposure in client components.** `DownloadForm`, `RoleCheckBox` and
  `Sharelist/[slug]/detailsPage.jsx` receive the access token in the browser. It is
  the same user's token, but it would be safer to proxy those calls through Next route
  handlers so the token never leaves the server.
- **Synchronous scrape endpoints.** `POST /fetch` and the floorsheet scrape endpoints
  run Selenium inside the request. They work because Nginx/Gunicorn timeouts are
  raised, but a background queue (Celery/RQ) is the correct long-term shape. The
  `run_scrape` command already covers the scheduled case.
- **SQLite** is fine for one small instance with WAL, but PostgreSQL is recommended
  once more than a couple of users write concurrently.
