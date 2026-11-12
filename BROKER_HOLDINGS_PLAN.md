# Broker Holdings Feature — Implementation Plan

Feature: for a chosen stock and date range, show per-broker quantity bought, quantity
sold, net change, and (where data allows) an estimated carry-forward position.

---

## 1. Data reality (audited against `db.sqlite3`)

`FloorsheetData`: **368,626 rows**, 340 stocks, date range **2025-10-30 → 2026-02-05**,
**65 distinct trading days**.

Per-stock history depth is extremely skewed:

| Distinct floorsheet days | Stocks | Share |
|---|---|---|
| ≥ 1 | 340 | 100% |
| ≥ 3 | 309 | 91% |
| ≥ 5 | **7** | **2.1%** |
| ≥ 30 | 3 | 0.9% |
| ≥ 60 | 1 | 0.3% |

**Median stock has 3 days of data.** Only these have real depth:

| Symbol | Days | Range |
|---|---|---|
| SIFC | 65 | 2025-10-30 → 2026-02-05 |
| AKJCL | 44 | 2025-11-30 → 2026-02-05 |
| CREST | 36 | 2025-12-11 → 2026-02-05 |
| AHPC | 23 | 2026-01-01 → 2026-02-05 |
| ADBL | 23 | 2026-01-01 → 2026-02-05 |
| ACLBSL | 23 | 2026-01-01 → 2026-02-05 |
| AHL | 8 | 2026-01-01 → 2026-02-05 |

Consequences:

- **KKHC** (the reference stock) has exactly **3 days** — 2026-02-03/04/05, 1,794 rows.
  A 30-trading-day baseline before 2026-02-03 would require data from ~2025-12-20, which
  does not exist. True holdings are therefore **not computable** for KKHC.
- Floorsheet data **ends 2026-02-05**, ~8 months stale relative to the current date,
  even though merolagani still serves current data.

Other verified facts that shape the implementation:

- Broker IDs run **1–101** (92 distinct). `101` appears on **both** sides with real
  quantities, so it is a legitimate broker number, not a sentinel. The scrapers assume
  `1 <= n <= 100` (`nepalstock_floorsheet_scraper.py:756`), so this is flagged, not dropped.
- Self-trades (`buyer_broker == seller_broker`) are **2.0%** of KKHC quantity and
  **6.7%** for SIFC. They net to zero for a broker's own position but inflate activity
  counts and turnover, so they are excluded by default.
- `StockData` has **461** distinct trading days vs floorsheet's 65, so it is the better
  source for a trading calendar and for detecting *which* days are missing.

---

## 2. What is knowable vs. what is not

| Quantity | Reliability |
|---|---|
| `bought_qty`, `sold_qty`, `net_qty` for the selected range | **Exact**, always |
| turnover, trade counts, avg buy/sell rate | **Exact**, always |
| `estimated_holding_qty` (carry-forward position) | **Estimate**, depends on prior history |

The central design rule: **never return a confident-looking wrong holdings number.**
Where the baseline is insufficient, return `null` plus an explicit coverage warning.

---

## 3. Algorithm

```
baseline_net[b]       = Σ(qty where buyer  == b, date < start)
                       − Σ(qty where seller == b, date < start)

period_net[b]         = Σ(qty where buyer  == b, start ≤ date ≤ end)
                       − Σ(qty where seller == b, start ≤ date ≤ end)

estimated_holding[b]  = baseline_net[b] + period_net[b]
```

Two deliberate choices:

1. **Baseline uses *all* available prior data**, not a hard 30-day cap. More history is a
   strictly better estimate and costs nothing extra. `lookback_days` remains available as
   an optional cost cap and defaults to `0` (= unlimited).
2. **`estimated_holding_qty` is `null`** when the baseline cannot be trusted. The response
   carries a `holdings_reliability` tier of `none` / `partial` / `full` so the UI can
   degrade honestly.

Reliability rule:

- `none` — no prior floorsheet data at all before `start_date`.
- `partial` — some prior data exists, but the gap between the earliest prior date and
  `start_date` exceeds the requested lookback window (i.e. history is not continuous).
- `full` — prior data is continuous back to at least the lookback window, so the carry-forward
  position is a sound estimate.

---

## 4. Backend

### 4.1 New module `stock_data/broker_holdings.py`

Pure computation, no HTTP, no Selenium — unit-testable in isolation. This mirrors the
existing house split where scrapers live in their own modules
(`floorsheet_scraper.py`, `nepalstock_floorsheet_scraper.py`, `nepse_indices_scraper.py`)
and views stay thin. `floorsheet_views.py` is already 832 lines and is not grown further.

```python
compute_broker_holdings(
    stock, start_date, end_date, *,
    lookback_days=0,
    exclude_self_trades=True,
    min_net_qty=0,
    sort_by='net',
    limit=50,
) -> dict
```

### 4.2 Query plan

At most 8 queries, all served by existing indexes on `FloorsheetData`
(`[stock, -transaction_date]`, `[stock, buyer_broker]`, `[stock, seller_broker]`).

| # | Query | Purpose |
|---|---|---|
| 1 | `StockData` distinct dates in range | trading calendar |
| 2 | `FloorsheetData` distinct dates in range | which days actually have data |
| 3 | range buy: `.values('buyer_broker').annotate(Sum, Count, Avg)` | house style, `floorsheet_views.py:575-585` |
| 4 | range sell on `seller_broker` | same |
| 5 | daily buy: `.values('transaction_date','buyer_broker').annotate(Sum)` | per-day series |
| 6 | daily sell: `.values('transaction_date','seller_broker').annotate(Sum)` | per-day series |
| 7 | all rows `date < start`, grouped by buyer | baseline |
| 8 | all rows `date < start`, grouped by seller | baseline |

Queries 7–8 are skipped entirely when no prior data exists. The per-day series is built
from **two** grouped queries rather than one query per broker.

The buy/sell merge uses a Python dict keyed by `broker_id`, copying the pattern at
`floorsheet_views.py:769-812` transposed from symbol-keyed to broker-keyed. Existing
`ACCUMULATING` / `DISTRIBUTING` vocabulary (`:805`) and HHI thresholds (`:667-674`) are
reused rather than reinvented.

### 4.3 Endpoint

`BrokerHoldingsView` in `floorsheet_views.py` — `AllowAny`, GET only, thin wrapper over
`compute_broker_holdings`. Route added to the floorsheet block at `urls.py:91-97`.

```
GET /api/stock-data/floorsheet/broker-holdings/
    ?symbol=KKHC
    &start_date=2026-02-03
    &end_date=2026-02-05
    &lookback_days=0
    &exclude_self_trades=true
    &min_net_qty=0
    &sort_by=net
    &limit=50
```

Dates are `YYYY-MM-DD`, matching the existing `floorsheet/data/` convention and the value
that `<input type="date">` already produces on the frontend. No conversion needed.

**Default range:** when omitted, `end_date` resolves to **the symbol's latest date that
actually has floorsheet data** and `start_date` to 30 days earlier. A naive "last 30 days"
default would render an empty page for every stock, because data ends 2026-02-05 while the
current date is months later.

#### Response shape

```jsonc
{
  "symbol": "KKHC",
  "security_name": "Khanikhola Hydropower Co. Ltd.",
  "date_range": {
    "start": "2026-02-03",
    "end": "2026-02-05",
    "trading_days_expected": 3,
    "trading_days_with_data": 3
  },
  "baseline": {
    "requested_lookback_days": 0,
    "available_days": 0,
    "first_data_date": null,
    "is_continuous": false,
    "reliability": "none"
  },
  "coverage": {
    "trading_days_expected": 3,
    "trading_days_with_data": 3,
    "coverage_pct": 100.0,
    "missing_days": [],
    "warnings": []
  },
  "summary": {
    "total_bought_qty": 0,
    "total_sold_qty": 0,
    "total_bought_amount": 0.0,
    "total_sold_amount": 0.0,
    "net_qty": 0,
    "net_amount": 0.0,
    "unique_brokers": 0,
    "total_trades": 0,
    "self_trade_qty_pct": 0.0,
    "self_trades_excluded": true,
    "top_accumulator": { "broker": 46, "net_qty": 0 },
    "top_distributor": { "broker": 12, "net_qty": 0 },
    "concentration": { "hhi": 0.0, "interpretation": "Competitive/Distributed" }
  },
  "brokers": [
    {
      "broker": 46,
      "bought_qty": 0,
      "bought_amount": 0.0,
      "buy_count": 0,
      "avg_buy_rate": 0.0,
      "sold_qty": 0,
      "sold_amount": 0.0,
      "sell_count": 0,
      "avg_sell_rate": 0.0,
      "net_qty": 0,
      "net_amount": 0.0,
      "position": "ACCUMULATING",
      "share_pct": 0.0,
      "baseline_qty": null,
      "estimated_holding_qty": null,
      "holdings_reliability": "none",
      "daily_net": [{ "date": "2026-02-03", "net_qty": 0 }]
    }
  ],
  "notes": []
}
```

Negative `net_qty` is a real distributing / short signal and is **never** clamped to zero.

### 4.4 Tests

`stock_data/tests.py` is currently empty, so this is greenfield. Covering:

- net quantity math across a range
- self-trade exclusion (and that it does not change net position)
- negative net retained, not clamped
- insufficient history → `estimated_holding_qty is None`, reliability `none`
- sufficient continuous history → reliability `full`
- coverage percentage and `missing_days`
- `sort_by` and `limit` behaviour
- broker with only buys, only sells, and both

No browser required, since the computation is pure.

---

## 5. Frontend

There is currently **no floorsheet UI at all** — the `floorsheet_*` constants in
`src/app/config/endpoint.js` are imported by zero components. This is greenfield.

| File | Role |
|---|---|
| `src/app/BrokerHoldings/page.js` | server component, reads `searchParams` |
| `src/app/BrokerHoldings/BrokerHoldingsClient.jsx` | `"use client"`, all interactivity |
| `src/app/BrokerHoldings/loading.js` | skeleton, following `Sharelist/loading.js` |
| `src/components/BrokerBarChart/brokerBarChart.jsx` | ApexCharts horizontal grouped bar |
| `src/app/config/endpoint.js` | `broker_holdings_endpoint` |
| `src/components/Navbar/navbar.jsx` | nav entry |

### Layout, in priority order

1. **Coverage banner** — `.alert-watch` when coverage is below 100%, naming the missing
   days. This is the most important element on the page; it is the honesty guarantee.
2. **Controls** — symbol picker plus start/end `input-field`s with `FiCalendar` icons and
   a 500ms debounce, copied from `TopStocksClient.jsx:74-102`.
3. **Summary `.stat-card` row** — bought / sold / net / unique brokers / top accumulator /
   top distributor.
4. **Grouped horizontal bar chart**, top 15 brokers, bought `#10b981` vs sold `#ef4444`,
   mirroring `candlestick.jsx` (the `dynamic(() => import(...), { ssr: false })` wrapper,
   `background: 'transparent'`). Light/dark theming comes free from the ApexCharts
   overrides in `globals.css:203-209`, which is why ApexCharts is preferred over chart.js
   here.
5. **Sortable `.table-modern`** — broker id, bought qty/amount, sold qty/amount, net qty,
   `share_pct` rendered with `progress-bar` / `progress-fill`, position via
   `badge-gain` / `badge-loss`. Numeric cells use `number-mono`. This will be the first
   sortable table in the app, so it sets the precedent.
6. **Row click → drill-down** with that broker's `daily_net` series.

Conventions followed: colours only via `var(--color-success)` / `var(--color-danger)`
(`globals.css`); `<input type="date">` already emits `YYYY-MM-DD`, matching this
endpoint, so no date-format shim is required.

### Interpretive caveat

NEPSE floorsheet discloses **broker agency flow, not beneficial ownership** — brokers
trade on behalf of clients. "Broker holdings" is industry shorthand for net broker
position. The UI must not overclaim; the coverage banner and reliability tier exist to
keep that honest.

---

## 6. Sequenced tasks

1. `stock_data/broker_holdings.py` + tests
2. `BrokerHoldingsView` + route in `urls.py`
3. Verify against **KKHC** (3 days → exact range analytics, `null` holdings, coverage
   warning) and **SIFC** (65 days → full carry-forward holdings). Testing both proves the
   confidence tiers actually work.
4. Document as section 6 of `API_DOCUMENTATION.md` (house convention: every endpoint is
   documented there).
5. Frontend `/BrokerHoldings` page, chart component, endpoint constant, navbar entry.

## 7. Explicitly out of scope

- **Backfilling historical floorsheet data.** Not part of this work; per decision the
  feature reports analytics for the selected range and flags gaps via coverage.
- **Broker names.** No `Broker` model or name mapping exists in the project. Brokers are
  displayed by numeric id only.
- Touching `floorsheet/analysis/` or `floorsheet/broker/`. Those stay as they are.