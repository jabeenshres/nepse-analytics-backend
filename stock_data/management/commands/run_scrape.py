"""
Run scraper jobs from cron/systemd instead of a long HTTP request.

Long Selenium runs inside a web worker will tie up Gunicorn for minutes or hours and
will usually hit Nginx's proxy timeout. Production should schedule them here.

Examples
--------
    # Today's Price (all symbols) for a date range
    python manage.py run_scrape today-price --from 2026-11-01 --to 2026-11-09

    # Whole-market floorsheet from nepalstock.com (current day only)
    python manage.py run_scrape floorsheet --source nepalstock

    # Per-symbol floorsheet history from merolagani.com
    python manage.py run_scrape floorsheet --source merolagani \
        --symbol AKJCL --from 2026-11-01 --to 2026-11-09

    # Several symbols
    python manage.py run_scrape floorsheet --source merolagani \
        --symbols AKJCL,NABIL --from 2026-11-01 --to 2026-11-09

Dates are always YYYY-MM-DD here; the scraper converts to MM/DD/YYYY internally.
"""
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError

from stock_data.constants import NEPAL_STOCK_BASE_URL
from stock_data.models import Stock, StockData


DATE_FORMAT = '%Y-%m-%d'
SCRAPER_DATE_FORMAT = '%m/%d/%Y'


class Command(BaseCommand):
    help = 'Run a scraper job (today-price or floorsheet) from the command line'

    def add_arguments(self, parser):
        parser.add_argument(
            'mode',
            choices=['today-price', 'floorsheet'],
            help='Which dataset to scrape',
        )
        parser.add_argument(
            '--source',
            choices=['nepalstock', 'merolagani'],
            default='nepalstock',
            help='Floorsheet source (ignored for today-price)',
        )
        parser.add_argument('--symbol', help='Single symbol (merolagani only)')
        parser.add_argument(
            '--symbols',
            help='Comma-separated symbols (merolagani only)',
        )
        parser.add_argument(
            '--from',
            dest='date_from',
            required=True,
            help='Start date, YYYY-MM-DD',
        )
        parser.add_argument(
            '--to',
            dest='date_to',
            required=True,
            help='End date, YYYY-MM-DD',
        )
        parser.add_argument(
            '--no-headless',
            action='store_true',
            help='Show the browser window (debugging only)',
        )

    def handle(self, *args, **options):
        date_from = self._parse_date(options['date_from'])
        date_to = self._parse_date(options['date_to'])
        if date_from > date_to:
            raise CommandError('--from must be on or before --to')

        headless = not options['no_headless']
        mode = options['mode']

        self.stdout.write(
            f"Scrape mode={mode} source={options['source']} "
            f"{date_from}..{date_to} headless={headless}"
        )

        try:
            if mode == 'today-price':
                self._run_today_price(date_from, date_to, headless)
            else:
                self._run_floorsheet(options, date_from, date_to, headless)
        except Exception as exc:  # noqa: BLE001 - surface a clear CLI error
            raise CommandError(f'Scrape failed: {exc}') from exc

    # ------------------------------------------------------------------

    def _run_today_price(self, date_from, date_to, headless):
        from stock_data.utils import NepalStockScraper

        scraper = NepalStockScraper(headless=headless)
        try:
            scraper.load_page(NEPAL_STOCK_BASE_URL)
            stats = scraper.loop_through_date_range(
                Stock, StockData, date_from, date_to, save_to_db=True
            )
        finally:
            scraper.close()

        self.stdout.write(self.style.SUCCESS(
            f"today-price done: processed={stats['dates_processed']} "
            f"failed={stats['dates_failed']} rows_created={stats['rows_created']} "
            f"rows_skipped={stats['rows_skipped']}"
        ))
        if stats.get('unresolved_symbols'):
            self.stdout.write(
                f"unresolved symbols: {', '.join(stats['unresolved_symbols'])}"
            )

    def _run_floorsheet(self, options, date_from, date_to, headless):
        if options['source'] == 'nepalstock':
            from stock_data.nepalstock_floorsheet_scraper import (
                NepalstockFloorsheetScraper,
            )

            scraper = NepalstockFloorsheetScraper(headless=headless)
            try:
                transactions, metadata = scraper.scrape_from_url(save_to_db=True)
            finally:
                scraper.close()
            self.stdout.write(self.style.SUCCESS(
                f"nepalstock floorsheet done: {len(transactions)} transactions, "
                f"symbols={len(metadata.get('symbols_found', []))}"
            ))
            return

        from stock_data.floorsheet_scraper import MerolaganiFloorsheetScraper

        symbols = self._symbols(options)
        if not symbols:
            raise CommandError(
                '--symbol or --symbols is required for --source merolagani'
            )

        start = date_from.strftime(SCRAPER_DATE_FORMAT)
        end = date_to.strftime(SCRAPER_DATE_FORMAT)

        scraper = MerolaganiFloorsheetScraper(headless=headless)
        try:
            results = scraper.scrape_multiple_symbols(
                symbols=symbols,
                date_from=start,
                date_to=end,
                scrape_all_pages=True,
                skip_existing_dates=True,
                save_to_db=True,
            )
        finally:
            scraper.close()

        self.stdout.write(self.style.SUCCESS(
            f"merolagani floorsheet done: "
            f"{results['successful']}/{results['total_symbols']} symbols, "
            f"{results['total_transactions']} transactions"
        ))

    # ------------------------------------------------------------------

    @staticmethod
    def _parse_date(value):
        try:
            return datetime.strptime(value, DATE_FORMAT).date()
        except (TypeError, ValueError):
            raise CommandError(f"Invalid date '{value}'. Use YYYY-MM-DD.")

    @staticmethod
    def _symbols(options):
        symbols = []
        if options.get('symbol'):
            symbols.append(options['symbol'])
        if options.get('symbols'):
            symbols.extend(
                part.strip() for part in options['symbols'].split(',') if part.strip()
            )
        return [symbol.upper() for symbol in symbols]
