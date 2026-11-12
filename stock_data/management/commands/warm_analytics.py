"""
Precompute the daily analytics (top stocks, breakout watchlist, accumulation
alerts) and store them in ``StockAnalyticsCache``.

Requests otherwise compute these lazily: on a fresh trading date the first
visitor waits ~6-10 s per endpoint while 300+ stocks are recalculated. Running
this command at the end of the scrape means every request hits the cache.

Usage
-----
    python manage.py warm_analytics
    python manage.py warm_analytics --date 2026-11-06
    python manage.py warm_analytics --keep-days 30 --stock-type all
"""
from datetime import datetime, timedelta

from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Max

from stock_data.models import Stock, StockAnalyticsCache, StockData
from stock_data.unusual_activity_views import (
    NO_DATA_CACHE,
    AccumulationAlertView,
    BreakoutWatchlistView,
    TopStocksToWatchView,
    save_analytics_cache_safe,
)

DATE_FORMAT = '%Y-%m-%d'

# (cache_type, view instance, analysis method)
JOBS = (
    ('top_stocks', TopStocksToWatchView, '_analyze_stock_comprehensive'),
    ('breakout_watchlist', BreakoutWatchlistView, '_analyze_breakout_potential'),
    ('accumulation_alerts', AccumulationAlertView, '_analyze_single_stock'),
)


class Command(BaseCommand):
    help = 'Precompute StockAnalyticsCache rows for a trading date'

    def add_arguments(self, parser):
        parser.add_argument(
            '--date',
            help='YYYY-MM-DD (default: latest date with stock data)',
        )
        parser.add_argument(
            '--stock-type',
            default='stock',
            help="stock_type to warm, or 'all' (default: stock)",
        )
        parser.add_argument(
            '--keep-days',
            type=int,
            default=14,
            help='Delete cache rows older than this many days (default: 14)',
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=0,
            help='Only process the first N stocks (debugging)',
        )

    def handle(self, *args, **options):
        target = self._resolve_date(options.get('date'))

        stocks = Stock.objects.all()
        if options['stock_type'].lower() != 'all':
            stocks = stocks.filter(stock_type=options['stock_type'])
        if options['limit']:
            stocks = stocks[:options['limit']]

        stocks = list(stocks)
        if not stocks:
            raise CommandError('No stocks matched the filter')

        self.stdout.write(
            f'Warming analytics for {target}: {len(stocks)} stocks x {len(JOBS)} types'
        )

        # Instantiate once; the analysis methods do not touch self.request.
        views = {
            cache_type: cls()
            for cache_type, cls, _ in JOBS
        }

        written = 0
        skipped = 0

        for index, stock in enumerate(stocks, 1):
            for cache_type, _, method_name in JOBS:
                result = getattr(views[cache_type], method_name)(stock, target)
                if not result:
                    # Remember the negative result too; otherwise these stocks
                    # are re-analysed on every request.
                    skipped += 1
                save_analytics_cache_safe(
                    stock, target, cache_type, result or NO_DATA_CACHE
                )
                written += 1

            if index % 50 == 0:
                self.stdout.write(f'  {index}/{len(stocks)} stocks processed')

        cutoff = target - timedelta(days=max(1, options['keep_days']))
        deleted, _ = (
            StockAnalyticsCache.objects
            .filter(analysis_date__lt=cutoff)
            .delete()
        )

        # Data changed; drop any file/memory cached responses for this run.
        cache.clear()

        self.stdout.write(self.style.SUCCESS(
            f'Done: {written} cache rows written, {skipped} skipped, '
            f'{deleted} old rows deleted'
        ))

    @staticmethod
    def _resolve_date(value):
        if value:
            try:
                return datetime.strptime(value, DATE_FORMAT).date()
            except ValueError:
                raise CommandError(f"Invalid --date '{value}'. Use YYYY-MM-DD.")

        latest = StockData.objects.aggregate(latest=Max('date'))['latest']
        if not latest:
            raise CommandError('No stock data available to warm')
        return latest
