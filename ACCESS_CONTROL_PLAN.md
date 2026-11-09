# Access control: login + config-driven roles

## Goal

Require login for the app, let the backend enforce access, and drive the sidebar from
one editable configuration instead of hardcoded `role === "admin"` checks.

## Current state (why this is needed)

- `REST_FRAMEWORK` has authentication and default permissions **commented out**, so JWT
  Bearer tokens are never validated.
- ~30 endpoints are `permission_classes = [AllowAny]`, including scrape/ingest routes.
- `StockDataViewSet` / `StockViewSet` allow anonymous writes.
- No `/api/token/refresh/` route exists, although the frontend calls it.
- Sidebar rules are hardcoded in `navbar.jsx`; only Download and Users are gated, and
  every other page is reachable while logged out.
- Most server components call the API without an `Authorization` header.

## Decisions

- **Storage**: code config in `accounts/access_config.py`. Readable, reviewable, no
  migration. A DB override can be layered later without changing callers.
- **Granularity**: one key per sidebar destination. Actions inside a page share the key.
- **Overrides**: role-based only. Superusers bypass everything.
- **Public routes**: `/Login`, `/Signup`, `/About`.
- **Default role map**: `user` gets every read-only data page; `manager` adds Download;
  `admin` adds Users.

## Feature keys

```
dashboard, sharelist, top_stocks, indices, screener,
broker_holdings, download, users, about
```

`ROLE_ACCESS`:

```python
admin   -> all
manager -> all except users
user    -> all except download, users
```

## Backend

1. **`accounts/access_config.py`** (new)
   - `FEATURES` registry (key -> label/path).
   - `ROLE_ACCESS` role -> allowed keys.
   - `allowed_features(user)` and `has_feature(user, key)`; `is_superuser` always passes.

2. **`accounts/permissions.py`**
   - Add `HasFeatureAccess`: authenticated + any of `view.required_features`.
   - For unsafe methods, use `view.write_features` when present (keeps ModelViewSets
     readable by everyone logged in while restricting writes).
   - `IsAdmin` also accepts `is_superuser`.

3. **`accounts/views.py` / `urls.py`**
   - `GET /api/accounts/me/` -> `{id, username, email, role, is_superuser, features}`.
   - `UserListView` gated by the `users` feature.
   - Keep `register/` public (self-signup already exists in the UI).

4. **`accounts/serializers.py`**
   - Login response adds `access_expires_at` and `is_superuser`.

5. **`stock_BE/urls.py`**
   - Register `api/token/refresh/` with `TokenRefreshView`.

6. **`stock_BE/settings.py`**
   - `DEFAULT_AUTHENTICATION_CLASSES = JWTAuthentication`
   - `DEFAULT_PERMISSION_CLASSES = HasFeatureAccess`
   - Login/refresh views keep their own empty `permission_classes`, so they stay public.

7. **Endpoint mapping** — set `required_features` on the views:

   | Feature | Endpoints |
   |---|---|
   | (any authenticated) | stock list/latest/entries/detail, analysis indicators/signals, backtest results, portfolios/holdings/trades, structured |
   | `screener` | analysis/screener, analysis/backtest |
   | `top_stocks` | analysis/top-stocks, unusual-activity, accumulation-alerts, breakout-watchlist, volume-spikes, recommendations |
   | `broker_holdings` | floorsheet/data, floorsheet/analysis, floorsheet/broker, floorsheet/broker-holdings |
   | `indices` | indices/data, indices/analysis, indices/compare, indices/list |
   | `download` | fetch, floorsheet/upload, floorsheet/scrape, nepalstock-scrape, indices/scrape, predictions/generate, lstm, random-forest |
   | `users` | accounts/users |

   `StockDataViewSet` / `StockViewSet` use `write_features = ('download',)`.

## Frontend

1. **`src/app/config/features.js`** (new) — presentation registry keyed by the same
   feature keys (label, path, icon name, section). No JSX, so middleware can import it.

2. **`src/app/lib/auth.js`** (new, server-only)
   - `getToken()`, `getMe()` (cached per request via React `cache`).
   - `requireAuth()` / `requireFeature(key)` -> redirect to `/Login` or `/`.
   - `authHeaders()` for server-side axios calls.

3. **`middleware.js`** (new)
   - Public paths: `/Login`, `/Signup`, `/About`.
   - No token -> redirect `/Login?next=<path>`.
   - Expired access token -> attempt refresh against `/api/token/refresh/`, rewrite the
     cookie; on failure redirect to `/Login`.

4. **`src/app/api/auth/refresh/route.js`** (new) — Route Handler that refreshes and
   rewrites the httpOnly cookie (server components cannot set cookies).

5. **`Sidebar` / `Navbar`**
   - Sidebar fetches `/me/` and passes `role`, `username`, `features`.
   - Navbar renders only allowed features from the registry; no hardcoded role checks.
   - Show username instead of just the role; Sign In only when logged out.

6. **Pages**
   - Add `requireFeature(...)` to each page:
     `dashboard`, `sharelist`, `top_stocks`, `indices`, `screener`,
     `broker_holdings`, `download`, `users`.
   - Add `authHeaders()` to every server-side axios/fetch call.
   - Pass `token` to the client `detailsPage` so its analysis calls authenticate.
   - Keep `/About` and auth pages public.

7. **`src/app/lib/api.js`**
   - Point refresh at the new Route Handler instead of the dead URL.

## Tests

- Permission matrix per tier: anonymous 401; `user` 200 read / 403 ingest; `manager`
  200 ingest / 403 users; `admin` 200 users; superuser 200 all.
- `/me/` returns the configured feature list for each role.
- Refresh route returns a usable access token.
- Frontend: logged-out redirect, per-role sidebar, direct-URL denial.

## Verification

- `curl` without a token -> 401 on read and ingest.
- `curl` with a `user` token -> 200 on `/latest/`, 403 on `/fetch/` and `/accounts/users/`.
- `curl` with a `manager` token -> 200 on `/fetch/`, 403 on `/accounts/users/`.
- Log in through the UI as each role and confirm the sidebar matches `ROLE_ACCESS`.

---

## Implemented

### Configuration

| Concern | File / place |
|---|---|
| Live roles -> features matrix | **Django admin -> Role feature access** (`RoleFeatureAccess` table) |
| Fallback defaults + API view -> feature | `stock_BE/accounts/access_config.py` |
| Sidebar labels/paths/icons | `Stock_FE/src/app/config/features.js` |

Feature keys must match between the backend and the frontend. To add a destination:
add the key to both `FEATURES` maps, add it to the relevant `ROLE_ACCESS` entries, and
add a `VIEW_FEATURES` entry for its API view.

Day-to-day access changes are made in the admin: filter by role, tick/untick `allowed`,
Save. The `ROLE_ACCESS` map is only used when `RoleFeatureAccess` has no rows.

### Backend files

- `accounts/access_config.py` (new) — `FEATURES`, `ROLE_ACCESS`, `VIEW_FEATURES`,
  `VIEW_WRITE_FEATURES`, `allowed_features()`, `has_feature()`.
- `accounts/permissions.py` — `HasFeatureAccess` (now the API default), superuser bypass,
  per-view `required_features` / `write_features` overrides.
- `accounts/views.py`, `accounts/urls.py` — `GET /api/accounts/me/`.
- `accounts/serializers.py` — adds `access_expires_at` and `is_superuser` to login.
- `stock_BE/settings.py` — JWT authentication + `HasFeatureAccess` as defaults.
- `stock_BE/urls.py` — `POST /api/token/refresh/`.
- All `permission_classes = [AllowAny]` removed from data views (31 occurrences).
- `stock_data/admin.py` — dropped `date_hierarchy` from the floorsheet changelist.

### Frontend files

- `middleware.js` (new) — login gate, public paths, token refresh on expiry.
- `src/app/config/features.js` (new) — sidebar registry.
- `src/app/lib/auth.js` (new) — `getToken`, `getMe`, `requireAuth`,
  `requireFeature`, `authHeaders`.
- `src/app/api/auth/refresh/route.js` (new) — cookie rewrite for client recovery.
- `src/components/Navbar/sidebar.jsx`, `navbar.jsx` — render `/me/` features only.
- All data pages — `requireFeature(...)` + Bearer headers on server-side calls.
- `src/app/Sharelist/[slug]/detailsPage.jsx` — receives the access token.

### Verification

| Caller | `/api/stock-data/` | `/api/accounts/users/` | `/api/accounts/me/` | features |
|---|---|---|---|---|
| anonymous | 401 | 401 | 401 | 0 |
| `user` | 200 | 403 | 200 | 7 |
| `manager` | 200 | 403 | 200 | 8 |
| superuser | 200 | 200 | 200 | 9 |

`POST /api/stock-data/floorsheet/upload/`: `user` -> 403, `manager`/`admin` -> 400
(permission granted, empty payload). Frontend `next build` passes; backend `manage.py
check` passes; 99 backend tests pass.

### Known deviation

`/api/accounts/register/` is still public so the existing Signup page keeps working.
Registration grants the `user` role, which includes the read-only data features.
Restrict it to admins if the platform should be invite-only.
