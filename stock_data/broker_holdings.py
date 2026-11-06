"""
Broker holdings computation for floorsheet data.

Given a stock and a date range, produce per-broker aggregates:

    bought_qty / bought_amount / buy_count / avg_buy_rate
    sold_qty   / sold_amount   / sell_count / avg_sell_rate
    net_qty    / net_amount
    baseline_qty / estimated_holding_qty   (best effort)

Why the holdings number is optional
------------------------------------
Floorsheet history is incomplete. In the current database the median stock has only
3 days of floorsheet rows and 90%+ of stocks have fewer than 5, so a "current holding"
cannot be derived for most symbols. Reporting a confident number anyway would be
misleading, so this module separates two very different quantities:

* Range analytics (bought / sold / net) are **exact** - they only need rows inside
  the requested range.
* Carry-forward holdings are an **estimate** that needs rows *before* the range.
  When those rows are missing or discontinuous the estimate is reported as ``None``
  and ``holdings_reliability`` is downgraded to ``none`` or ``partial``.

The estimate is computed as:

    estimated_holding[b] = baseline_net[b] + period_net[b]

where ``baseline_net`` sums every row for that broker strictly before ``start_date``
(using *all* available history, since more history is strictly better) and
``period_net`` sums rows inside the range.

Interpretive caveat: NEPSE floorsheet discloses broker *agency flow*, not beneficial
ownership - brokers trade on behalf of clients. "Broker holdings" is industry
shorthand for net broker position, and should not be presented as client ownership.

Pure computation only: no HTTP, no Selenium, so it is directly unit-testable.
"""
import logging
from datetime import timedelta
from decimal import Decimal

from django.db.models import Sum, Count, Avg, F, Q, Max

from .models import FloorsheetData, StockData
from .nepse_calendar import is_trading_day

logger = logging.getLogger(__name__)

# Mirrors the interpretation bands already used by FloorsheetAnalysisView.
HHI_HIGHLY_CONCENTRATED = 2500
HHI_MODERATELY_CONCENTRATED = 1500

SORT_OPTIONS = ('net', 'bought', 'sold', 'broker')

# Brokers in the source data should be 1-100; anything outside is surfaced as a
# note rather than silently dropped.
EXPECTED_BROKER_MIN = 1
EXPECTED_BROKER_MAX = 100


def _trading_days_in_range(start_date, end_date):
    """
    Return the set of dates the market traded within [start_date, end_date].

    StockData is preferred while it has coverage because it is a real exchange
    calendar and therefore knows about public holidays. It lags well behind the
    floorsheet scraper though: in the current database it stops at 2026-02-05 while
    floorsheet rows run through 2026-11-05. Using it alone made every recent range
    report "0 trading days / 0% coverage" even when thousands of rows existed.

    So: use StockData where it reaches, and fall back to the NEPSE weekday calendar
    (see nepse_calendar) past its last known date. The fallback cannot know about
    holidays, so those show up as missing days instead of being silently ignored.
    """
    trading_days = set(
        StockData.objects.filter(
            date__gte=start_date,
            date__lte=end_date,
        ).order_by().values_list('date', flat=True).distinct()
    )

    latest_calendar_day = StockData.objects.aggregate(latest=Max('date'))['latest']
    if latest_calendar_day is None:
        fallback_start = start_date
    else:
        fallback_start = max(start_date, latest_calendar_day + timedelta(days=1))

    current = fallback_start
    while current <= end_date:
        if is_trading_day(current):
            trading_days.add(current)
        current += timedelta(days=1)

    return trading_days


def _apply_self_trade_filter(queryset, exclude_self_trades):
    """Drop self-trades (same broker on both sides) when requested."""
    if exclude_self_trades:
        return queryset.exclude(buyer_broker=F('seller_broker'))
    return queryset


def _side_aggregates(queryset, side):
    """
    Aggregate a queryset grouped by broker for one side of the trade.

    Args:
        queryset: already filtered to the stock / date window.
        side: either ``'buyer'`` or ``'seller'``.

    Returns:
        Dict mapping broker id -> aggregate dict.
    """
    rows = queryset.values(side).annotate(
        qty=Sum('quantity'),
        amount=Sum('amount'),
        trades=Count('id'),
        avg_rate=Avg('rate'),
    )
    return {row[side]: row for row in rows}


def _side_daily(queryset, side):
    """
    Aggregate a queryset grouped by (date, broker) for one side of the trade.

    Returned as a flat list so the caller can merge both sides into a per-broker
    daily series without issuing one query per broker.
    """
    return list(
        queryset.values('transaction_date', side).annotate(qty=Sum('quantity'))
    )


def _position_label(net_qty):
    """Classify a broker's net position within the range."""
    if net_qty > 0:
        return 'ACCUMULATING'
    if net_qty < 0:
        return 'DISTRIBUTING'
    return 'NEUTRAL'


def _hhi(shares):
    """
    Herfindahl-Hirschman Index over a list of per-broker quantity shares.

    Reuses the thresholds already applied by FloorsheetAnalysisView so both
    endpoints report concentration on the same scale.
    """
    total = sum(shares)
    if not total:
        return 0.0, 'Competitive/Distributed'
    score = sum((share / total * 100) ** 2 for share in shares)
    if score > HHI_HIGHLY_CONCENTRATED:
        label = 'Highly concentrated'
    elif score > HHI_MODERATELY_CONCENTRATED:
        label = 'Moderately concentrated'
    else:
        label = 'Competitive/Distributed'
    return round(score, 2), label


def compute_baseline(stock, start_date, lookback_days=0, exclude_self_trades=True):
    """
    Compute each broker's net position strictly before ``start_date``.

    Args:
        stock: Stock instance.
        start_date: exclusive upper bound for the baseline.
        lookback_days: if > 0, only consider the most recent N calendar days before
            ``start_date``. ``0`` means use all available history.
        exclude_self_trades: drop self-trades from both sides.

    Returns:
        Dict with:
            baseline:   {broker_id: net_qty}
            meta:       {available_days, first_data_date, is_continuous, reliability}
    """
    prior = FloorsheetData.objects.filter(
        stock=stock,
        transaction_date__lt=start_date,
    )
    if lookback_days and lookback_days > 0:
        prior = prior.filter(
            transaction_date__gte=start_date - timedelta(days=lookback_days)
        )

    # `.order_by()` is required: FloorsheetData.Meta.ordering contains
    # transaction_no, and without clearing it Django folds the ordering columns
    # into the SELECT list, so `.distinct()` stops de-duplicating dates and
    # `available_days` would report a row count instead of a day count.
    prior_dates = sorted(
        prior.order_by().values_list('transaction_date', flat=True).distinct()
    )

    if not prior_dates:
        return {
            'baseline': {},
            'meta': {
                'requested_lookback_days': lookback_days,
                'available_days': 0,
                'first_data_date': None,
                'is_continuous': False,
                'reliability': 'none',
            },
        }

    filtered = _apply_self_trade_filter(prior, exclude_self_trades)
    buyers = _side_aggregates(filtered, 'buyer_broker')
    sellers = _side_aggregates(filtered, 'seller_broker')

    broker_ids = set(buyers) | set(sellers)
    baseline = {
        broker: (
            (buyers.get(broker, {}).get('qty') or 0)
            - (sellers.get(broker, {}).get('qty') or 0)
        )
        for broker in broker_ids
    }
    # Drop brokers whose baseline nets to exactly zero - they carry no signal.
    baseline = {b: q for b, q in baseline.items() if q != 0}

    # "Continuous" means prior history reaches back at least as far as the
    # requested lookback window. When no window was requested we can only report
    # that *some* history exists, so treat it as continuous.
    if lookback_days and lookback_days > 0:
        is_continuous = prior_dates[0] <= (
            start_date - timedelta(days=lookback_days)
        )
    else:
        is_continuous = True

    return {
        'baseline': baseline,
        'meta': {
            'requested_lookback_days': lookback_days,
            'available_days': len(prior_dates),
            'first_data_date': prior_dates[0],
            'is_continuous': is_continuous,
            'reliability': 'full' if is_continuous else 'partial',
        },
    }


def compute_broker_holdings(
    stock,
    start_date,
    end_date,
    lookback_days=0,
    exclude_self_trades=True,
    min_net_qty=0,
    sort_by='net',
    limit=50,
):
    """
    Compute per-broker bought / sold / net figures for a stock over a date range.

    Args:
        stock: Stock instance to analyse.
        start_date: inclusive range start (date object).
        end_date: inclusive range end (date object).
        lookback_days: optional cap on how far back the baseline reaches. ``0``
            (default) uses all available history before ``start_date``.
        exclude_self_trades: exclude trades where buyer == seller. These net to zero
            for the broker's position but inflate activity and turnover.
        min_net_qty: drop brokers whose absolute net is below this threshold.
        sort_by: one of ``net``, ``bought``, ``sold``, ``broker``.
        limit: cap the number of brokers returned.

    Returns:
        A JSON-ready dict. See module docstring for the shape and the reasoning
        behind the optional holdings estimate.
    """
    if sort_by not in SORT_OPTIONS:
        sort_by = 'net'

    # --- Range window -------------------------------------------------------
    in_range = FloorsheetData.objects.filter(
        stock=stock,
        transaction_date__gte=start_date,
        transaction_date__lte=end_date,
    )
    filtered = _apply_self_trade_filter(in_range, exclude_self_trades)

    buyers = _side_aggregates(filtered, 'buyer_broker')
    sellers = _side_aggregates(filtered, 'seller_broker')

    # Per-broker daily series, built from two grouped queries.
    daily_buy = _side_daily(filtered, 'buyer_broker')
    daily_sell = _side_daily(filtered, 'seller_broker')

    daily_net = {}
    for row in daily_buy:
        broker = daily_net.setdefault(row['buyer_broker'], {})
        date = row['transaction_date']
        broker[date] = broker.get(date, 0) + (row['qty'] or 0)
    for row in daily_sell:
        broker = daily_net.setdefault(row['seller_broker'], {})
        date = row['transaction_date']
        broker[date] = broker.get(date, 0) - (row['qty'] or 0)

    # --- Coverage -----------------------------------------------------------
    expected_days = _trading_days_in_range(start_date, end_date)
    days_with_data = set(
        in_range.order_by().values_list('transaction_date', flat=True).distinct()
    )
    missing_days = sorted(expected_days - days_with_data)

    if expected_days:
        coverage_pct = round(100.0 * len(expected_days & days_with_data) / len(expected_days), 2)
    else:
        coverage_pct = 0.0

    # --- Baseline (best effort) --------------------------------------------
    baseline_result = compute_baseline(
        stock, start_date, lookback_days, exclude_self_trades
    )
    baseline = baseline_result['baseline']
    baseline_meta = baseline_result['meta']
    # Make the semantics explicit in the payload. `estimated_holding_qty` is a
    # cumulative position, not range activity: it includes every day before
    # start_date (including the immediately preceding trading day).
    baseline_meta['as_of'] = end_date.isoformat()
    baseline_meta['description'] = (
        'Cumulative net position as of the range end date. Equals prior history '
        'before the range start plus net activity inside the range, so on a '
        'single-day range it still includes earlier days.'
    )

    # --- Merge sides per broker --------------------------------------------
    broker_ids = set(buyers) | set(sellers) | set(baseline)

    records = []
    for broker in broker_ids:
        buy = buyers.get(broker, {})
        sell = sellers.get(broker, {})

        bought_qty = buy.get('qty') or 0
        sold_qty = sell.get('qty') or 0
        bought_amount = buy.get('amount') or Decimal('0')
        sold_amount = sell.get('amount') or Decimal('0')

        net_qty = bought_qty - sold_qty
        net_amount = bought_amount - sold_amount

        if abs(net_qty) < min_net_qty:
            continue

        # Only derive a carry-forward position when prior history exists. With no
        # prior rows the "estimate" would silently equal the range net, which reads
        # like a real position but is not one.
        if baseline_meta['reliability'] == 'none':
            baseline_qty = None
            estimated_holding = None
        else:
            baseline_qty = baseline.get(broker, 0)
            estimated_holding = baseline_qty + net_qty

        series = [
            {'date': date, 'net_qty': qty}
            for date, qty in sorted(daily_net.get(broker, {}).items())
        ]

        records.append({
            'broker': broker,
            'bought_qty': bought_qty,
            'bought_amount': float(bought_amount),
            'buy_count': buy.get('trades') or 0,
            'avg_buy_rate': round(float(buy['avg_rate']), 2) if buy.get('avg_rate') else None,
            'sold_qty': sold_qty,
            'sold_amount': float(sold_amount),
            'sell_count': sell.get('trades') or 0,
            'avg_sell_rate': round(float(sell['avg_rate']), 2) if sell.get('avg_rate') else None,
            'net_qty': net_qty,
            'net_amount': float(net_amount),
            'position': _position_label(net_qty),
            'baseline_qty': baseline_qty,
            'estimated_holding_qty': estimated_holding,
            'holdings_reliability': baseline_meta['reliability'],
            'daily_net': series,
        })

    # --- Share of net activity (drives the magnitude bars in the UI) --------
    # Computed over every matching broker, before `limit` is applied, so the
    # share stays meaningful for the returned subset and the summary totals below
    # always describe the whole range.
    total_abs_net = sum(abs(r['net_qty']) for r in records) or 1
    for record in records:
        record['share_pct'] = round(
            100.0 * abs(record['net_qty']) / total_abs_net, 2
        )

    # --- Summary (over all matching brokers, independent of `limit`) ---------
    # Amounts are summed straight from the per-broker Decimal aggregates rather
    # than from the per-broker floats, so the totals stay exact for large values.
    total_bought_qty = sum(row['qty'] or 0 for row in buyers.values())
    total_sold_qty = sum(row['qty'] or 0 for row in sellers.values())
    total_bought_amount = sum(
        (row['amount'] or Decimal('0')) for row in buyers.values()
    )
    total_sold_amount = sum(
        (row['amount'] or Decimal('0')) for row in sellers.values()
    )

    # Concentration across every broker that touched the stock in the range,
    # using the same thresholds as FloorsheetAnalysisView.
    hhi_score, hhi_label = _hhi([row['qty'] or 0 for row in buyers.values()])

    top_accumulator = max(records, key=lambda r: r['net_qty']) if records else None
    top_distributor = min(records, key=lambda r: r['net_qty']) if records else None

    # --- Sort + limit -------------------------------------------------------
    if sort_by == 'bought':
        records.sort(key=lambda r: r['bought_qty'], reverse=True)
    elif sort_by == 'sold':
        records.sort(key=lambda r: r['sold_qty'], reverse=True)
    elif sort_by == 'broker':
        records.sort(key=lambda r: r['broker'])
    else:
        records.sort(key=lambda r: abs(r['net_qty']), reverse=True)
    brokers_matched = len(records)
    records = records[:limit]

    raw_stats = in_range.aggregate(
        total_qty=Sum('quantity'),
        self_qty=Sum('quantity', filter=Q(buyer_broker=F('seller_broker'))),
        total_trades=Count('id'),
        unique_buyers=Count('buyer_broker', distinct=True),
        unique_sellers=Count('seller_broker', distinct=True),
    )
    raw_total_qty = raw_stats['total_qty'] or 0
    self_trade_pct = (
        round(100.0 * (raw_stats['self_qty'] or 0) / raw_total_qty, 2)
        if raw_total_qty else 0.0
    )

    # --- Warnings + notes ---------------------------------------------------
    warnings = []
    if not records:
        warnings.append(
            'No floorsheet transactions found for this stock in the selected range.'
        )
    if expected_days and coverage_pct < 100.0:
        warnings.append(
            f'Floorsheet data covers {coverage_pct}% of the {len(expected_days)} '
            f'trading days in this range. Range analytics below only reflect days '
            f'that were actually scraped.'
        )
    if baseline_meta['reliability'] == 'none':
        warnings.append(
            'No floorsheet history exists before the start of this range, so a '
            'carry-forward holdings estimate cannot be computed. Only in-range '
            'buy/sell activity is shown.'
        )
    elif baseline_meta['reliability'] == 'partial':
        warnings.append(
            f'Prior floorsheet history starts {baseline_meta["first_data_date"]} '
            f'and is not continuous back through the requested '
            f'{lookback_days}-day lookback, so holdings figures are partial.'
        )

    notes = []
    odd_brokers = sorted(
        b for b in broker_ids
        if b < EXPECTED_BROKER_MIN or b > EXPECTED_BROKER_MAX
    )
    if odd_brokers:
        notes.append(
            f'Broker ids {odd_brokers} fall outside the expected '
            f'{EXPECTED_BROKER_MIN}-{EXPECTED_BROKER_MAX} range used by the '
            f'scrapers, but carry real quantities and are included.'
        )
    notes.append(
        'NEPSE floorsheet shows broker agency flow, not beneficial ownership - '
        'brokers trade on behalf of clients.'
    )

    return {
        'symbol': stock.symbol,
        'security_name': stock.security_name,
        'stock_type': stock.stock_type,
        'date_range': {
            'start': start_date,
            'end': end_date,
            'trading_days_expected': len(expected_days),
            'trading_days_with_data': len(expected_days & days_with_data),
        },
        'baseline': baseline_meta,
        'coverage': {
            'trading_days_expected': len(expected_days),
            'trading_days_with_data': len(expected_days & days_with_data),
            'coverage_pct': coverage_pct,
            'missing_days': missing_days,
            'warnings': warnings,
        },
        'summary': {
            'total_bought_qty': total_bought_qty,
            'total_sold_qty': total_sold_qty,
            'total_bought_amount': round(total_bought_amount, 2),
            'total_sold_amount': round(total_sold_amount, 2),
            'net_qty': total_bought_qty - total_sold_qty,
            'net_amount': round(total_bought_amount - total_sold_amount, 2),
            'brokers_matched': brokers_matched,
            'brokers_reported': len(records),
            'unique_buyers': raw_stats['unique_buyers'] or 0,
            'unique_sellers': raw_stats['unique_sellers'] or 0,
            'total_trades': raw_stats['total_trades'] or 0,
            'self_trade_qty_pct': self_trade_pct,
            'self_trades_excluded': exclude_self_trades,
            'top_accumulator': (
                {'broker': top_accumulator['broker'], 'net_qty': top_accumulator['net_qty']}
                if top_accumulator else None
            ),
            'top_distributor': (
                {'broker': top_distributor['broker'], 'net_qty': top_distributor['net_qty']}
                if top_distributor else None
            ),
            'concentration': {'hhi': hhi_score, 'interpretation': hhi_label},
        },
        'brokers': records,
        'notes': notes,
    }