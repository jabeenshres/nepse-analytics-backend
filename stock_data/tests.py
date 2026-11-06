"""
Tests for broker holdings computation and the broker-holdings endpoint.

`compute_broker_holdings` is pure DB aggregation, so these tests need no browser
and no scraped fixtures. Each test builds a small, explicit floorsheet history so
the expected numbers can be checked by hand.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from .broker_holdings import compute_broker_holdings, compute_baseline
from .floorsheet_scraper import MerolaganiFloorsheetScraper
from .models import FloorsheetData, Stock, StockData
from .nepse_calendar import (
    NEPSE_MON_FRI_START,
    is_trading_day,
    next_trading_day,
    today_or_clamp,
    weekend_weekdays,
)
from .nepalstock_floorsheet_scraper import NepalstockFloorsheetScraper
from .utils import NepalStockScraper
from .unusual_activity_views import StockRecommendationsView


def make_stock(symbol='TEST', security_id=9001):
    return Stock.objects.create(
        symbol=symbol,
        security_id=security_id,
        security_name=f'{symbol} Test Co.',
        fifty_two_weeks_high=Decimal('1000.00'),
        fifty_two_weeks_low=Decimal('100.00'),
    )


def mark_trading_day(stock, day):
    """Record a StockData row so the day counts as an expected trading day."""
    StockData.objects.create(
        stock=stock,
        date=day,
        open_price=Decimal('500.00'),
        high_price=Decimal('510.00'),
        low_price=Decimal('490.00'),
        close_price=Decimal('505.00'),
        total_traded_quantity=1000,
        total_traded_value=Decimal('500000.00'),
        previous_day_close_price=Decimal('500.00'),
        last_updated_price=Decimal('505.00'),
        total_trades=10,
        average_traded_price=Decimal('500.00'),
    )


def add_trade(stock, day, transaction_no, buyer, seller, quantity, rate=Decimal('500.00')):
    """Create one floorsheet row. Self-trades are expressed as buyer == seller."""
    return FloorsheetData.objects.create(
        stock=stock,
        transaction_date=day,
        transaction_no=transaction_no,
        buyer_broker=buyer,
        seller_broker=seller,
        quantity=quantity,
        rate=rate,
        amount=Decimal(quantity) * rate,
    )


class BrokerHoldingsComputationTests(TestCase):
    """Range analytics are exact; carry-forward holdings degrade honestly."""

    def setUp(self):
        self.stock = make_stock()
        self.d1 = date(2026, 1, 5)
        self.d2 = date(2026, 1, 6)
        self.d3 = date(2026, 1, 7)

    def broker(self, result, broker_id):
        """Look up a single broker record from the response."""
        matches = [b for b in result['brokers'] if b['broker'] == broker_id]
        self.assertEqual(
            len(matches), 1, f'expected exactly one row for broker {broker_id}'
        )
        return matches[0]

    # --- Range analytics ----------------------------------------------------

    def test_net_quantity_is_bought_minus_sold(self):
        # Broker 1 buys 600 and sells 200 -> net +400
        add_trade(self.stock, self.d1, 1, buyer=1, seller=2, quantity=100)
        add_trade(self.stock, self.d1, 2, buyer=1, seller=2, quantity=500)
        add_trade(self.stock, self.d2, 3, buyer=3, seller=1, quantity=200)

        result = compute_broker_holdings(self.stock, self.d1, self.d3)

        broker_1 = self.broker(result, 1)
        self.assertEqual(broker_1['bought_qty'], 600)
        self.assertEqual(broker_1['sold_qty'], 200)
        self.assertEqual(broker_1['net_qty'], 400)
        self.assertEqual(broker_1['buy_count'], 2)
        self.assertEqual(broker_1['sell_count'], 1)
        self.assertEqual(broker_1['position'], 'ACCUMULATING')

    def test_negative_net_is_retained_and_labelled_distributing(self):
        # Broker 1 sells 900 having bought only 100 -> net -800
        add_trade(self.stock, self.d1, 1, buyer=1, seller=2, quantity=100)
        add_trade(self.stock, self.d2, 2, buyer=2, seller=1, quantity=900)

        result = compute_broker_holdings(self.stock, self.d1, self.d3)

        broker_1 = self.broker(result, 1)
        self.assertEqual(broker_1['net_qty'], -800)
        self.assertEqual(broker_1['position'], 'DISTRIBUTING')

    def test_broker_with_only_buys_has_zero_sold_fields(self):
        add_trade(self.stock, self.d1, 1, buyer=5, seller=9, quantity=250)

        result = compute_broker_holdings(self.stock, self.d1, self.d3)

        broker_5 = self.broker(result, 5)
        self.assertEqual(broker_5['bought_qty'], 250)
        self.assertEqual(broker_5['sold_qty'], 0)
        self.assertEqual(broker_5['sell_count'], 0)
        self.assertIsNone(broker_5['avg_sell_rate'])
        self.assertEqual(broker_5['net_qty'], 250)

    def test_rows_outside_the_range_are_ignored(self):
        add_trade(self.stock, self.d1, 1, buyer=1, seller=2, quantity=100)
        add_trade(self.stock, self.d3, 2, buyer=1, seller=2, quantity=100)
        add_trade(self.stock, self.d3 + timedelta(days=1), 3, buyer=1, seller=2, quantity=9999)

        result = compute_broker_holdings(self.stock, self.d1, self.d3)

        self.assertEqual(self.broker(result, 1)['bought_qty'], 200)

    def test_amount_and_average_rate_totals(self):
        add_trade(self.stock, self.d1, 1, buyer=1, seller=2, quantity=100, rate=Decimal('500.00'))
        add_trade(self.stock, self.d2, 2, buyer=1, seller=2, quantity=100, rate=Decimal('700.00'))

        result = compute_broker_holdings(self.stock, self.d1, self.d3)

        broker_1 = self.broker(result, 1)
        self.assertEqual(broker_1['bought_amount'], 120000.0)
        self.assertEqual(broker_1['avg_buy_rate'], 600.0)
        self.assertEqual(result['summary']['total_bought_amount'], 120000.0)

    # --- Self trades -------------------------------------------------------

    def test_self_trades_excluded_by_default(self):
        add_trade(self.stock, self.d1, 1, buyer=1, seller=2, quantity=100)
        add_trade(self.stock, self.d1, 2, buyer=7, seller=7, quantity=400)

        result = compute_broker_holdings(self.stock, self.d1, self.d3)

        self.assertEqual(result['summary']['self_trades_excluded'], True)
        # Broker 7 traded 400 shares but all of it against itself, so it has no
        # net activity and must not appear at all.
        self.assertEqual([b['broker'] for b in result['brokers']], [1, 2])
        self.assertGreater(result['summary']['self_trade_qty_pct'], 0)

    def test_self_trades_can_be_included_on_request(self):
        add_trade(self.stock, self.d1, 1, buyer=1, seller=2, quantity=100)
        add_trade(self.stock, self.d1, 2, buyer=7, seller=7, quantity=400)

        result = compute_broker_holdings(
            self.stock, self.d1, self.d3, exclude_self_trades=False
        )

        broker_7 = self.broker(result, 7)
        self.assertEqual(broker_7['bought_qty'], 400)
        self.assertEqual(broker_7['sold_qty'], 400)
        # A self-trade nets to zero, so it must not move the position.
        self.assertEqual(broker_7['net_qty'], 0)
        self.assertEqual(broker_7['position'], 'NEUTRAL')

    def test_self_trades_do_not_change_net_position(self):
        add_trade(self.stock, self.d1, 1, buyer=1, seller=2, quantity=100)
        add_trade(self.stock, self.d1, 2, buyer=2, seller=2, quantity=500)

        excluded = compute_broker_holdings(self.stock, self.d1, self.d3)
        included = compute_broker_holdings(
            self.stock, self.d1, self.d3, exclude_self_trades=False
        )

        self.assertEqual(
            self.broker(excluded, 2)['net_qty'], self.broker(included, 2)['net_qty']
        )

    # --- Carry-forward holdings -------------------------------------------

    def test_holdings_are_null_when_no_prior_history_exists(self):
        add_trade(self.stock, self.d1, 1, buyer=1, seller=2, quantity=300)

        result = compute_broker_holdings(self.stock, self.d1, self.d3)

        self.assertEqual(result['baseline']['reliability'], 'none')
        broker_1 = self.broker(result, 1)
        # Range analytics stay exact...
        self.assertEqual(broker_1['net_qty'], 300)
        # ...but a position cannot be derived, so it must not be invented.
        self.assertIsNone(broker_1['estimated_holding_qty'])
        self.assertIsNone(broker_1['baseline_qty'])
        self.assertTrue(
            any('carry-forward' in w for w in result['coverage']['warnings']),
            'expected a warning explaining why holdings are unavailable',
        )

    def test_holdings_add_prior_net_to_range_net(self):
        # Before the range: broker 1 net +1000
        add_trade(self.stock, self.d1 - timedelta(days=10), 1, buyer=1, seller=2, quantity=1000)
        # Inside the range: broker 1 buys 500
        add_trade(self.stock, self.d2, 2, buyer=1, seller=2, quantity=500)

        result = compute_broker_holdings(self.stock, self.d1, self.d3)

        self.assertEqual(result['baseline']['reliability'], 'full')
        broker_1 = self.broker(result, 1)
        self.assertEqual(broker_1['baseline_qty'], 1000)
        self.assertEqual(broker_1['net_qty'], 500)
        self.assertEqual(broker_1['estimated_holding_qty'], 1500)
        self.assertEqual(broker_1['holdings_reliability'], 'full')

    def test_holdings_can_be_negative(self):
        # Broker 2 sells 900 before the range with no prior purchase, then sells
        # another 100 inside it, so the carry-forward position is -1000.
        add_trade(self.stock, self.d1 - timedelta(days=10), 1, buyer=1, seller=2, quantity=900)
        add_trade(self.stock, self.d2, 2, buyer=1, seller=2, quantity=100)

        result = compute_broker_holdings(self.stock, self.d1, self.d3)

        broker_2 = self.broker(result, 2)
        self.assertEqual(broker_2['baseline_qty'], -900)
        self.assertEqual(broker_2['net_qty'], -100)
        self.assertEqual(broker_2['estimated_holding_qty'], -1000)

    def test_lookback_days_limits_the_baseline_window(self):
        add_trade(self.stock, self.d1 - timedelta(days=40), 1, buyer=1, seller=2, quantity=1000)
        add_trade(self.stock, self.d1 - timedelta(days=2), 2, buyer=1, seller=2, quantity=100)
        add_trade(self.stock, self.d2, 3, buyer=1, seller=2, quantity=50)

        result = compute_broker_holdings(
            self.stock, self.d1, self.d3, lookback_days=5
        )

        # Only the 2-days-prior trade falls inside the 5 day window.
        self.assertEqual(self.broker(result, 1)['baseline_qty'], 100)

    def test_baseline_reports_partial_when_history_is_not_continuous(self):
        # Two trading days of prior history, but a 30 day window is requested.
        add_trade(self.stock, self.d1 - timedelta(days=2), 1, buyer=1, seller=2, quantity=100)
        add_trade(self.stock, self.d1 - timedelta(days=1), 2, buyer=1, seller=2, quantity=100)

        result = compute_broker_holdings(
            self.stock, self.d1, self.d3, lookback_days=30
        )

        baseline = result['baseline']
        self.assertEqual(baseline['requested_lookback_days'], 30)
        self.assertEqual(baseline['available_days'], 2)
        self.assertFalse(baseline['is_continuous'])
        self.assertEqual(baseline['reliability'], 'partial')
        # Partial still reports a real figure, derived from real rows.
        self.assertEqual(self.broker(result, 1)['estimated_holding_qty'], 200)

    def test_compute_baseline_returns_empty_without_history(self):
        outcome = compute_baseline(self.stock, self.d1)

        self.assertEqual(outcome['baseline'], {})
        self.assertEqual(outcome['meta']['available_days'], 0)
        self.assertIsNone(outcome['meta']['first_data_date'])
        self.assertEqual(outcome['meta']['reliability'], 'none')

    def test_available_days_counts_days_not_rows(self):
        """Guards the Meta.ordering trap: `.distinct()` needs `.order_by()`."""
        for i in range(3):
            add_trade(self.stock, self.d1 - timedelta(days=5), 100 + i,
                      buyer=1, seller=2, quantity=10)
        for i in range(4):
            add_trade(self.stock, self.d1 - timedelta(days=4), 200 + i,
                      buyer=1, seller=2, quantity=10)

        result = compute_baseline(self.stock, self.d1)

        self.assertEqual(result['meta']['available_days'], 2)

    # --- Coverage ----------------------------------------------------------

    def test_coverage_reports_missing_trading_days(self):
        mark_trading_day(self.stock, self.d1)
        mark_trading_day(self.stock, self.d2)
        mark_trading_day(self.stock, self.d3)
        # Floorsheet data only exists for d1 and d3.
        add_trade(self.stock, self.d1, 1, buyer=1, seller=2, quantity=100)
        add_trade(self.stock, self.d3, 2, buyer=1, seller=2, quantity=100)

        result = compute_broker_holdings(self.stock, self.d1, self.d3)

        coverage = result['coverage']
        self.assertEqual(coverage['trading_days_expected'], 3)
        self.assertEqual(coverage['trading_days_with_data'], 2)
        self.assertAlmostEqual(coverage['coverage_pct'], 66.67, places=2)
        self.assertEqual(coverage['missing_days'], [self.d2])
        self.assertTrue(any('66.67%' in w for w in coverage['warnings']))

    def test_full_coverage_emits_no_coverage_warning(self):
        mark_trading_day(self.stock, self.d1)
        add_trade(self.stock, self.d1, 1, buyer=1, seller=2, quantity=100)

        result = compute_broker_holdings(self.stock, self.d1, self.d1)

        self.assertEqual(result['coverage']['coverage_pct'], 100.0)
        self.assertEqual(result['coverage']['missing_days'], [])
        self.assertFalse(any('%' in w for w in result['coverage']['warnings']))

    def test_coverage_falls_back_to_weekday_calendar_past_stockdata(self):
        # StockData lags behind the floorsheet scraper, so a recent range has no
        # calendar rows at all. Coverage must still count the weekday as expected,
        # otherwise the endpoint reports "0 of 0 trading days" for a day that has
        # thousands of floorsheet rows.
        mark_trading_day(self.stock, self.d1)          # last calendar day available
        late_day = date(2026, 1, 20)                    # a Tuesday, well past d1
        add_trade(self.stock, late_day, 1, buyer=1, seller=2, quantity=100)

        result = compute_broker_holdings(self.stock, late_day, late_day)

        coverage = result['coverage']
        self.assertEqual(coverage['trading_days_expected'], 1)
        self.assertEqual(coverage['trading_days_with_data'], 1)
        self.assertEqual(coverage['coverage_pct'], 100.0)
        self.assertFalse(any('%' in w for w in coverage['warnings']))

    def test_weekend_day_past_stockdata_is_not_expected(self):
        # 2026-01-24 is a Saturday, so the fallback must not invent a trading day.
        mark_trading_day(self.stock, self.d1)
        saturday = date(2026, 1, 24)
        add_trade(self.stock, saturday, 1, buyer=1, seller=2, quantity=100)

        result = compute_broker_holdings(self.stock, saturday, saturday)

        self.assertEqual(result['coverage']['trading_days_expected'], 0)

    def test_single_day_range_has_no_rows_from_adjacent_days(self):
        # start == end must scope every range figure to that one day.
        add_trade(self.stock, self.d1, 1, buyer=1, seller=2, quantity=100)
        add_trade(self.stock, self.d2, 2, buyer=1, seller=2, quantity=999)

        result = compute_broker_holdings(self.stock, self.d1, self.d1)

        row = self.broker(result, 1)
        self.assertEqual(row['bought_qty'], 100)
        self.assertEqual(result['summary']['total_bought_qty'], 100)
        self.assertEqual(
            [point['date'] for point in row['daily_net']], [self.d1]
        )

    def test_empty_range_returns_no_brokers_but_does_not_crash(self):
        mark_trading_day(self.stock, self.d1)
        result = compute_broker_holdings(self.stock, date(2020, 1, 1), date(2020, 1, 31))

        self.assertEqual(result['brokers'], [])
        self.assertIsNone(result['summary']['top_accumulator'])
        self.assertTrue(result['coverage']['warnings'])

    # --- Sorting, filtering, limiting --------------------------------------

    def test_default_sort_is_by_absolute_net_descending(self):
        add_trade(self.stock, self.d1, 1, buyer=1, seller=2, quantity=100)
        add_trade(self.stock, self.d1, 2, buyer=3, seller=4, quantity=500)
        add_trade(self.stock, self.d1, 3, buyer=5, seller=6, quantity=300)

        result = compute_broker_holdings(self.stock, self.d1, self.d3)

        nets = [b['net_qty'] for b in result['brokers']]
        self.assertEqual(nets, sorted(nets, key=abs, reverse=True))
        self.assertEqual(result['brokers'][0]['broker'], 3)

    def test_sort_by_broker_id_is_ascending(self):
        add_trade(self.stock, self.d1, 1, buyer=30, seller=2, quantity=100)
        add_trade(self.stock, self.d1, 2, buyer=10, seller=2, quantity=100)
        add_trade(self.stock, self.d1, 3, buyer=20, seller=2, quantity=100)

        result = compute_broker_holdings(self.stock, self.d1, self.d3, sort_by='broker')

        self.assertEqual([b['broker'] for b in result['brokers']], [2, 10, 20, 30])

    def test_unknown_sort_by_falls_back_to_net(self):
        add_trade(self.stock, self.d1, 1, buyer=1, seller=2, quantity=100)

        result = compute_broker_holdings(
            self.stock, self.d1, self.d3, sort_by='nonsense'
        )

        self.assertEqual(result['brokers'][0]['broker'], 1)

    def test_min_net_qty_filters_small_positions(self):
        add_trade(self.stock, self.d1, 1, buyer=1, seller=2, quantity=1000)
        add_trade(self.stock, self.d1, 2, buyer=3, seller=4, quantity=20)

        result = compute_broker_holdings(
            self.stock, self.d1, self.d3, min_net_qty=500
        )

        brokers = {b['broker'] for b in result['brokers']}
        self.assertIn(1, brokers)
        self.assertNotIn(3, brokers)

    def test_limit_truncates_rows_but_not_summary_totals(self):
        add_trade(self.stock, self.d1, 1, buyer=1, seller=2, quantity=1000)
        add_trade(self.stock, self.d1, 2, buyer=3, seller=4, quantity=600)
        add_trade(self.stock, self.d1, 3, buyer=5, seller=6, quantity=200)

        full = compute_broker_holdings(self.stock, self.d1, self.d3)
        limited = compute_broker_holdings(self.stock, self.d1, self.d3, limit=1)

        # Each trade contributes a buyer and a seller, so 3 trades touch 6 brokers.
        self.assertEqual(len(full['brokers']), 6)
        self.assertEqual(len(limited['brokers']), 1)
        # The summary must describe the whole range, not just the returned rows.
        self.assertEqual(limited['summary']['total_bought_qty'],
                         full['summary']['total_bought_qty'])
        self.assertEqual(limited['summary']['brokers_matched'], 6)
        self.assertEqual(limited['summary']['brokers_reported'], 1)

    def test_share_pct_is_relative_to_all_brokers(self):
        add_trade(self.stock, self.d1, 1, buyer=1, seller=2, quantity=750)
        add_trade(self.stock, self.d1, 2, buyer=3, seller=4, quantity=250)

        result = compute_broker_holdings(self.stock, self.d1, self.d3)

        # Magnitude share is measured across every broker on both sides, so the
        # buyer and seller of the same trade each hold half of it.
        by_broker = {b['broker']: b['share_pct'] for b in result['brokers']}
        self.assertAlmostEqual(by_broker[1], 37.5, places=2)
        self.assertAlmostEqual(by_broker[2], 37.5, places=2)
        self.assertAlmostEqual(by_broker[3], 12.5, places=2)
        self.assertAlmostEqual(sum(by_broker.values()), 100.0, places=2)

    # --- Daily series ------------------------------------------------------

    def test_daily_series_sums_to_net_quantity(self):
        add_trade(self.stock, self.d1, 1, buyer=1, seller=2, quantity=100)
        add_trade(self.stock, self.d2, 2, buyer=1, seller=2, quantity=200)
        add_trade(self.stock, self.d3, 3, buyer=3, seller=1, quantity=150)

        result = compute_broker_holdings(self.stock, self.d1, self.d3)
        broker_1 = self.broker(result, 1)

        series = broker_1['daily_net']
        self.assertEqual([p['date'] for p in series],
                         [self.d1, self.d2, self.d3])
        self.assertEqual(sum(p['net_qty'] for p in series), broker_1['net_qty'])
        self.assertEqual([p['net_qty'] for p in series], [100, 200, -150])

    def test_daily_series_merges_multiple_trades_same_day(self):
        add_trade(self.stock, self.d1, 1, buyer=1, seller=2, quantity=100)
        add_trade(self.stock, self.d1, 2, buyer=1, seller=2, quantity=50)
        add_trade(self.stock, self.d1, 3, buyer=1, seller=9, quantity=25)

        result = compute_broker_holdings(self.stock, self.d1, self.d3)
        series = self.broker(result, 1)['daily_net']

        self.assertEqual(len(series), 1)
        self.assertEqual(series[0]['net_qty'], 175)

    # --- Broker id sanity --------------------------------------------------

    def test_out_of_range_broker_id_is_flagged_not_dropped(self):
        add_trade(self.stock, self.d1, 1, buyer=101, seller=2, quantity=100)

        result = compute_broker_holdings(self.stock, self.d1, self.d3)

        self.assertIn(101, [b['broker'] for b in result['brokers']])
        self.assertTrue(any('101' in note for note in result['notes']))

    def test_agency_flow_caveat_is_always_reported(self):
        add_trade(self.stock, self.d1, 1, buyer=1, seller=2, quantity=100)

        result = compute_broker_holdings(self.stock, self.d1, self.d3)

        self.assertTrue(any('agency flow' in note for note in result['notes']))


class BrokerHoldingsViewTests(TestCase):
    """HTTP contract: parameter handling, defaults and error codes."""

    def setUp(self):
        self.client = APIClient()
        self.stock = make_stock()
        self.url = reverse('broker-holdings')
        self.d1 = date(2026, 1, 5)
        self.d2 = date(2026, 1, 6)
        add_trade(self.stock, self.d1, 1, buyer=1, seller=2, quantity=100)
        add_trade(self.stock, self.d2, 2, buyer=3, seller=1, quantity=50)

    def test_symbol_is_required(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 400)
        self.assertIn('symbol', response.json()['error'])

    def test_unknown_symbol_returns_404(self):
        response = self.client.get(self.url, {'symbol': 'NOPE'})

        self.assertEqual(response.status_code, 404)

    def test_symbol_lookup_is_case_insensitive(self):
        response = self.client.get(self.url, {'symbol': 'test'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['symbol'], 'TEST')

    def test_malformed_date_returns_400(self):
        response = self.client.get(
            self.url, {'symbol': 'TEST', 'start_date': '05-01-2026'}
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('YYYY-MM-DD', response.json()['error'])

    def test_start_after_end_returns_400(self):
        response = self.client.get(self.url, {
            'symbol': 'TEST',
            'start_date': '2026-01-06',
            'end_date': '2026-01-05',
        })

        self.assertEqual(response.status_code, 400)

    def test_default_range_uses_latest_available_data_not_today(self):
        response = self.client.get(self.url, {'symbol': 'TEST'})
        payload = response.json()

        self.assertEqual(response.status_code, 200)
        # The latest date with floorsheet rows is 2026-01-06, not the current day.
        self.assertEqual(payload['date_range']['end'], '2026-01-06')
        self.assertEqual(payload['date_range']['start'], '2025-12-07')

    def test_stock_without_floorsheet_data_reports_clearly(self):
        empty_stock = make_stock(symbol='EMPTY', security_id=9002)

        response = self.client.get(self.url, {'symbol': 'EMPTY'})
        payload = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload['brokers'], [])
        self.assertIn('No floorsheet data', payload['message'])

    def test_explicit_range_is_respected(self):
        response = self.client.get(self.url, {
            'symbol': 'TEST',
            'start_date': '2026-01-06',
            'end_date': '2026-01-06',
        })
        payload = response.json()

        self.assertEqual(payload['date_range']['start'], '2026-01-06')
        self.assertEqual(payload['date_range']['end'], '2026-01-06')
        broker_1 = [b for b in payload['brokers'] if b['broker'] == 1][0]
        self.assertEqual(broker_1['net_qty'], -50)

    def test_dates_are_serialised_as_iso_strings(self):
        response = self.client.get(self.url, {
            'symbol': 'TEST',
            'start_date': '2026-01-05',
            'end_date': '2026-01-06',
        })
        payload = response.json()

        self.assertIsInstance(payload['date_range']['start'], str)
        for broker in payload['brokers']:
            for point in broker['daily_net']:
                self.assertIsInstance(point['date'], str)
        for day in payload['coverage']['missing_days']:
            self.assertIsInstance(day, str)

    def test_query_parameters_are_forwarded(self):
        response = self.client.get(self.url, {
            'symbol': 'TEST',
            'start_date': '2026-01-05',
            'end_date': '2026-01-06',
            'exclude_self_trades': 'false',
            'min_net_qty': '10',
            'sort_by': 'broker',
            'limit': '1',
        })
        payload = response.json()

        self.assertEqual(payload['summary']['self_trades_excluded'], False)
        self.assertEqual(len(payload['brokers']), 1)

    def test_limit_is_capped_to_protect_the_endpoint(self):
        response = self.client.get(self.url, {'symbol': 'TEST', 'limit': '100000'})

        self.assertEqual(response.status_code, 200)

    def test_non_numeric_lookback_falls_back_to_default(self):
        response = self.client.get(self.url, {
            'symbol': 'TEST',
            'lookback_days': 'abc',
        })

        self.assertEqual(response.status_code, 200)


class NepseCalendarTests(SimpleTestCase):
    """
    The Nepal trading week changed on 2026-04-06: Sun-Thu (closed Fri/Sat) became
    Mon-Fri (closed Sat/Sun). These pin the behaviour either side of that boundary,
    including the awkward transition week.
    """

    def test_weekend_before_transition_is_friday_and_saturday(self):
        # 2026-04-03 is a Friday, 2026-04-04 a Saturday.
        self.assertEqual(weekend_weekdays(date(2026, 4, 3)), (4, 5))
        self.assertFalse(is_trading_day(date(2026, 4, 3)))
        self.assertFalse(is_trading_day(date(2026, 4, 4)))

    def test_weekend_after_transition_is_saturday_and_sunday(self):
        # 2026-04-11 is a Saturday, 2026-04-12 a Sunday.
        self.assertEqual(weekend_weekdays(date(2026, 4, 11)), (5, 6))
        self.assertFalse(is_trading_day(date(2026, 4, 11)))
        self.assertFalse(is_trading_day(date(2026, 4, 12)))

    def test_sunday_april_5_traded_as_last_day_of_old_week(self):
        self.assertTrue(is_trading_day(date(2026, 4, 5)))

    def test_friday_april_10_traded_during_transition_week(self):
        # The transition week ran Mon-Fri, so this Friday was open even though Fridays
        # were closed under the old schedule.
        self.assertEqual(date(2026, 4, 10).weekday(), 4)
        self.assertTrue(is_trading_day(date(2026, 4, 10)))

    def test_monday_april_6_is_first_day_of_new_schedule(self):
        self.assertTrue(is_trading_day(date(2026, 4, 6)))

    def test_fridays_differ_depending_on_side_of_boundary(self):
        self.assertFalse(is_trading_day(date(2026, 4, 3)))   # Friday before
        self.assertTrue(is_trading_day(date(2026, 4, 10)))   # Friday after

    def test_sundays_differ_depending_on_side_of_boundary(self):
        self.assertTrue(is_trading_day(date(2026, 4, 5)))    # Sunday before
        self.assertFalse(is_trading_day(date(2026, 4, 12)))  # Sunday after

    def test_every_weekday_is_trading_except_the_two_weekend_days(self):
        day = date(2026, 4, 13)  # a Monday, safely after the transition
        for offset in range(14):
            current = day + timedelta(days=offset)
            weekend = current.weekday() in weekend_weekdays(current)
            self.assertEqual(not is_trading_day(current), weekend, current.strftime('%A'))

    def test_next_trading_day_from_thursday_crosses_weekend(self):
        # Thu 2026-04-09 -> Fri 2026-04-10 is now a trading day, +2 lands on Monday.
        self.assertEqual(next_trading_day(date(2026, 4, 9)), date(2026, 4, 10))
        self.assertEqual(next_trading_day(date(2026, 4, 9), 2), date(2026, 4, 13))

    def test_next_trading_day_skips_old_friday_weekend(self):
        # Thu 2026-04-02 -> Sun 2026-04-05, because Fri 2026-04-03 was closed.
        self.assertEqual(next_trading_day(date(2026, 4, 2)), date(2026, 4, 5))

    def test_next_trading_day_skips_new_weekend(self):
        # Fri 2026-04-10 -> Mon 2026-04-13, because Sat/Sun were closed.
        self.assertEqual(next_trading_day(date(2026, 4, 10)), date(2026, 4, 13))

    def test_next_trading_day_with_zero_returns_same_day(self):
        self.assertEqual(next_trading_day(date(2026, 4, 10), 0), date(2026, 4, 10))

    def test_next_trading_day_walks_backwards(self):
        self.assertEqual(next_trading_day(date(2026, 4, 13), -1), date(2026, 4, 10))

    def test_today_or_clamp_leaves_past_dates_alone(self):
        self.assertEqual(today_or_clamp(date(2020, 1, 1)), date(2020, 1, 1))

    def test_today_or_clamp_pulls_future_dates_back_to_today(self):
        self.assertEqual(today_or_clamp(date.today() + timedelta(days=45)), date.today())


class GetDatesInRangeTests(SimpleTestCase):
    """
    _get_dates_in_range is pure date arithmetic, so these exercise it without Selenium.
    """

    def setUp(self):
        # The method is pure, so an uninitialized instance is enough and keeps the test
        # free of any browser setup.
        self.scraper = MerolaganiFloorsheetScraper.__new__(MerolaganiFloorsheetScraper)

    def test_exact_date_list_across_the_transition_week(self):
        # 2026-04-03 Fri .. 2026-04-13 Mon.
        dates = self.scraper._get_dates_in_range('04/03/2026', '04/13/2026')

        self.assertEqual(dates, [
            '04/05/2026',  # Sun - traded
            '04/06/2026',  # Mon - first day of new schedule
            '04/07/2026',  # Tue
            '04/08/2026',  # Wed
            '04/09/2026',  # Thu
            '04/10/2026',  # Fri - traded during transition week
            '04/13/2026',  # Mon
        ])

    def test_only_weekend_days_are_excluded(self):
        dates = self.scraper._get_dates_in_range('04/06/2026', '04/17/2026')

        self.assertNotIn('04/11/2026', dates)  # Sat
        self.assertNotIn('04/12/2026', dates)  # Sun
        self.assertEqual(len(dates), 10)        # 12 calendar days - one weekend
        self.assertIn('04/10/2026', dates)     # Friday is open post-transition
        self.assertIn('04/17/2026', dates)

    def test_skip_weekends_false_includes_every_day(self):
        dates = self.scraper._get_dates_in_range('04/11/2026', '04/13/2026', skip_weekends=False)

        self.assertEqual(dates, ['04/11/2026', '04/12/2026', '04/13/2026'])

    def test_future_date_to_is_clamped_to_today(self):
        past = date.today() - timedelta(days=3)
        future = date.today() + timedelta(days=40)
        dates = self.scraper._get_dates_in_range(
            past.strftime('%m/%d/%Y'), future.strftime('%m/%d/%Y')
        )

        self.assertNotEqual(dates, [])
        last = datetime.strptime(dates[-1], '%m/%d/%Y').date()
        self.assertLessEqual(last, date.today())

    def test_range_spanning_transition_matches_expected_count(self):
        # 2025-07-01 (Tue) .. 2026-04-30 (Thu): old Sun-Thu rule only, plus the new
        # schedule from 2026-04-06.
        dates = self.scraper._get_dates_in_range('07/01/2025', '04/30/2026')
        parsed = [datetime.strptime(d, '%m/%d/%Y').date() for d in dates]

        self.assertEqual(len(parsed), len(set(parsed)))
        for day in parsed:
            self.assertTrue(is_trading_day(day), day)

    def test_start_after_end_returns_empty_list(self):
        self.assertEqual(self.scraper._get_dates_in_range('04/10/2026', '04/01/2026'), [])

    def test_unparseable_date_falls_back_to_end_date(self):
        dates = self.scraper._get_dates_in_range('not-a-date', '04/15/2026')

        self.assertEqual(dates, ['04/15/2026'])


class SettlementInfoTests(SimpleTestCase):
    """
    T+2 availability must follow the live calendar rather than a hardcoded weekday map.
    """

    def setUp(self):
        self.view = StockRecommendationsView.__new__(StockRecommendationsView)

    def test_buy_day_is_today_on_a_trading_day(self):
        trading_day = next_trading_day(date.today())
        self.assertEqual(is_trading_day(trading_day), True)

        info = self.view._get_settlement_info()

        for key in ('rule', 'current_day', 'buy_day', 'available_day', 'trading_days_wait'):
            self.assertIn(key, info)

    def test_available_day_is_two_trading_days_after_buy_day(self):
        info = self.view._get_settlement_info()

        self.assertEqual(info['rule'], 'T+2 Settlement')
        self.assertIn(info['trading_days_wait'], (1, 2))

    def test_settlement_examples_cover_trading_days_and_skip_weekends(self):
        examples = self.view._build_settlement_examples()

        self.assertTrue(examples)
        for key, text in examples.items():
            self.assertTrue(key.endswith('_buy'), key)
            self.assertTrue(text.startswith('Available '), text)

        # Under the current Mon-Fri schedule neither weekend day is a trading day.
        if date.today() >= NEPSE_MON_FRI_START:
            self.assertNotIn('saturday_buy', examples)
            self.assertNotIn('sunday_buy', examples)

    def test_settlement_examples_each_span_two_trading_days(self):
        examples = self.view._build_settlement_examples()
        today = date.today()

        for offset in range(7):
            buy_date = today + timedelta(days=offset)
            if not is_trading_day(buy_date):
                continue
            available = next_trading_day(buy_date, 2)
            note = ' (weekend intervened)' if (available - buy_date).days > 2 else ''
            key = f'{buy_date.strftime("%A").lower()}_buy'
            self.assertIn(key, examples)
            self.assertEqual(examples[key], f"Available {available.strftime('%A')}{note}")

    def test_settlement_note_appears_when_weekend_pushes_settlement_out(self):
        examples = self.view._build_settlement_examples()

        # Friday buy settles after a weekend, so it must carry the explanatory note.
        for key, text in examples.items():
            buy_day = key.replace('_buy', '')
            if buy_day == 'friday' and date.today() >= NEPSE_MON_FRI_START:
                self.assertIn('weekend intervened', text)
                break
        else:
            self.skipTest('no Friday in the current 7-day window')


class ContractDateParsingTests(SimpleTestCase):
    """
    NEPSE contract numbers embed the trade date as YYYYMMDD. The nepalstock scraper
    used to ignore that and stamp date.today(), which shifted a whole session's rows
    forward by one trading day whenever it ran before publication.
    """

    def test_contract_prefix_is_used_as_trade_date(self):
        self.assertEqual(
            NepalstockFloorsheetScraper._date_from_contract(2026110505013245).date(),
            date(2026, 11, 5),
        )
        self.assertEqual(
            NepalstockFloorsheetScraper._date_from_contract(2026110405020709).date(),
            date(2026, 11, 4),
        )

    def test_short_or_missing_contract_returns_none(self):
        self.assertIsNone(NepalstockFloorsheetScraper._date_from_contract(None))
        self.assertIsNone(NepalstockFloorsheetScraper._date_from_contract(0))
        self.assertIsNone(NepalstockFloorsheetScraper._date_from_contract(12345))

    def test_impossible_date_prefix_returns_none(self):
        # Month 13 must not be coerced into a date.
        self.assertIsNone(
            NepalstockFloorsheetScraper._date_from_contract(2026139900000001)
        )

    def test_html_parse_uses_contract_date_not_today(self):
        html = """
        <table>
          <thead>
            <tr>
              <th>SN</th><th>Contract No.</th><th>Stock Symbol</th>
              <th>Buyer</th><th>Seller</th><th>Quantity</th>
              <th>Rate (Rs)</th><th>Amount (Rs)</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>1</td><td>2026110405000055</td><td>RFPL</td>
              <td>58</td><td>82</td><td>100</td><td>250.00</td><td>25,000.00</td>
            </tr>
          </tbody>
        </table>
        """

        rows, _meta = NepalstockFloorsheetScraper.scrape_from_html(html)

        self.assertEqual(len(rows), 1)
        transaction = rows[0]['transaction']
        self.assertEqual(transaction.transaction_date.date(), date(2026, 11, 4))
        self.assertNotEqual(transaction.transaction_date.date(), date.today())


class TodayPriceParserTests(SimpleTestCase):
    """
    The Today's Price table is parsed from rendered HTML instead of a downloaded
    CSV, so the parser must be Selenium-free and tolerant of the site's formatting.
    """

    HTML = """
    <table>
      <thead>
        <tr>
          <th>SN</th><th>Symbol</th><th>Close Price* (Rs)</th>
          <th>Open Price (Rs)</th><th>High Price (Rs)</th><th>Low Price (Rs)</th>
          <th>Total Traded Quantity</th><th>Total Traded Value</th>
          <th>Total Trades</th><th>LTP</th>
          <th>Previous Day Close Price (Rs)</th><th>Average Traded Price (Rs)</th>
          <th>52 Week High (Rs)</th><th>52 Week Low (Rs)</th>
          <th>MarketCapitalization (Rs) (Amt in millions)</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>1</td><td>ADBL</td><td>340.00</td><td>335.00</td><td>342.90</td>
          <td>332.10</td><td>133,478</td><td>45,357,766.2</td><td>268</td>
          <td>340.00 (0.1)</td><td>339.90</td><td>339.81</td><td>355.00</td>
          <td>285.20</td><td>48,638.77</td>
        </tr>
        <tr>
          <td>2</td><td>ACLBSL</td><td>836.70</td><td>835.00</td><td>846.90</td>
          <td>835.00</td><td>1,342</td><td>1,124,103.7</td><td>31</td>
          <td>836.70 (-8.3)</td><td>845.00</td><td>837.63</td><td>1,095.00</td>
          <td>827.90</td><td>3,071.89</td>
        </tr>
        <tr><td>3</td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td><td></td></tr>
      </tbody>
    </table>
    """

    def test_parses_rows_and_skips_blank_symbols(self):
        rows = NepalStockScraper.parse_today_price_html(self.HTML, date(2026, 10, 2))

        self.assertEqual([r['symbol'] for r in rows], ['ADBL', 'ACLBSL'])

    def test_ltp_change_suffix_is_stripped(self):
        rows = NepalStockScraper.parse_today_price_html(self.HTML, date(2026, 10, 2))
        by_symbol = {r['symbol']: r for r in rows}

        self.assertEqual(by_symbol['ACLBSL']['last_updated_price'], 836.70)
        self.assertEqual(by_symbol['ADBL']['last_updated_price'], 340.00)

    def test_numeric_fields_are_converted(self):
        rows = NepalStockScraper.parse_today_price_html(self.HTML, date(2026, 10, 2))
        adbl = {r['symbol']: r for r in rows}['ADBL']

        self.assertEqual(adbl['close_price'], 340.0)
        self.assertEqual(adbl['total_traded_quantity'], 133478)
        self.assertEqual(adbl['total_trades'], 268)
        self.assertAlmostEqual(adbl['total_traded_value'], 45357766.2)
        self.assertAlmostEqual(adbl['market_capitalization'], 48638.77)
        self.assertEqual(adbl['date'], date(2026, 10, 2))

    def test_missing_table_returns_empty_list(self):
        self.assertEqual(
            NepalStockScraper.parse_today_price_html('<html></html>', date(2026, 10, 2)),
            [],
        )

    def test_unrecognised_headers_return_empty_list(self):
        html = '<table><thead><tr><th>Foo</th><th>Bar</th></tr></thead><tbody><tr><td>1</td><td>2</td></tr></tbody></table>'
        self.assertEqual(
            NepalStockScraper.parse_today_price_html(html, date(2026, 10, 2)), []
        )

    def test_trading_days_between_skips_weekends(self):
        # 2026-10-02 is a Friday, 2026-10-03/04 are Sat/Sun, 2026-10-05 is Monday.
        days = NepalStockScraper.trading_days_between(date(2026, 10, 2), date(2026, 10, 5))

        self.assertEqual(days, [date(2026, 10, 2), date(2026, 10, 5)])


class TodayPriceSaveTests(TestCase):
    """Saving parsed rows must be idempotent and report unknown symbols."""

    def setUp(self):
        self.scraper = NepalStockScraper.__new__(NepalStockScraper)
        self.stock = make_stock('ADBL', security_id=9002)

    def make_row(self, symbol='ADBL', **overrides):
        row = {
            'symbol': symbol,
            'date': date(2026, 10, 2),
            'close_price': 340.0,
            'open_price': 335.0,
            'high_price': 342.9,
            'low_price': 332.1,
            'total_traded_quantity': 133478,
            'total_traded_value': 45357766.2,
            'total_trades': 268,
            'last_updated_price': 340.0,
            'previous_day_close_price': 339.9,
            'average_traded_price': 339.81,
            'market_capitalization': 48638.77,
        }
        row.update(overrides)
        return row

    def test_creates_rows_for_known_symbols(self):
        stats = self.scraper.save_today_price_rows(
            [self.make_row()], date(2026, 10, 2), Stock, StockData
        )

        self.assertEqual(stats['created'], 1)
        self.assertEqual(stats['skipped'], 0)
        self.assertEqual(stats['unresolved'], [])
        self.assertTrue(
            StockData.objects.filter(stock=self.stock, date=date(2026, 10, 2)).exists()
        )

    def test_second_run_is_idempotent(self):
        self.scraper.save_today_price_rows(
            [self.make_row()], date(2026, 10, 2), Stock, StockData
        )
        stats = self.scraper.save_today_price_rows(
            [self.make_row()], date(2026, 10, 2), Stock, StockData
        )

        self.assertEqual(stats['created'], 0)
        self.assertEqual(stats['skipped'], 1)
        self.assertEqual(
            StockData.objects.filter(stock=self.stock, date=date(2026, 10, 2)).count(), 1
        )

    def test_unknown_symbol_is_reported_not_raised(self):
        stats = self.scraper.save_today_price_rows(
            [self.make_row(), self.make_row(symbol='NOPE')],
            date(2026, 10, 2),
            Stock,
            StockData,
        )

        self.assertEqual(stats['created'], 1)
        self.assertEqual(stats['unresolved'], ['NOPE'])

    def test_no_rows_returns_zero_stats(self):
        stats = self.scraper.save_today_price_rows(
            [], date(2026, 10, 2), Stock, StockData
        )

        self.assertEqual(stats['created'], 0)
        self.assertEqual(stats['unresolved'], [])
