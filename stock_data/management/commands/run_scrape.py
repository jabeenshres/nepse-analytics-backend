"""
Run one scraper job from the command line.

Examples
--------
    # NEPSE indices for a date
    python manage.py run_scrape indices --date 2026-11-05

    # Today's Price for a date or range
    python manage.py run_scrape today-price --date 2026-11-06
    python manage.py run_scrape today-price --from 2026-11-01 --to 2026-11-09

    # Whole-market floorsheet from nepalstock.com
    python manage.py run_scrape floorsheet --source nepalstock

    # Per-symbol floorsheet history from merolagani.com
    python manage.py run_scrape floorsheet --source merolagani \
        --symbol AKJCL --from 2026-11-01 --to 2026-11-09

Dates are always YYYY-MM-DD here; the scrapers convert to MM/DD/YYYY internally.
For the full daily sequence use ``run_daily_scrape`` instead.
"""
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError

from stock_data.scraping_jobs import (
    run_floorsheet,
    run_indices,
    run_today_price,
)


DATE_FORMAT = '%Y-%m-%d'


class Command(BaseCommand):
    help = 'Run a scraper job (indices, today-price or floorsheet)'

    def add_arguments(self, parser):
        parser.add_argument(
            'mode',
            choices=['indices', 'today-price', 'floorsheet'],
            help='Which dataset to scrape',
        )
        parser.add_argument(
            '--date',
            help='Single date, YYYY-MM-DD (sets --from and --to)',
        )
        parser.add_argument('--from', dest='date_from', help='Start date, YYYY-MM-DD')
        parser.add_argument('--to', dest='date_to', help='End date, YYYY-MM-DD')
        parser.add_argument(
            '--source',
            choices=['nepalstock', 'merolagani'],
            default='nepalstock',
            help='Floorsheet source (ignored otherwise)',
        )
        parser.add_argument('--symbol', help='Single symbol (merolagani only)')
        parser.add_argument(
            '--symbols',
            help='Comma-separated symbols (merolagani only)',
        )
        parser.add_argument(
            '--index-ids',
            help='Comma-separated NEPSE index IDs (indices only, default all)',
        )
        parser.add_argument(
            '--no-headless',
            action='store_true',
            help='Show the browser window (debugging only)',
        )
        parser.add_argument(
            '--allow-empty',
            action='store_true',
            help='Exit 0 when no data is found (e.g. a market holiday)',
        )

    def handle(self, *args, **options):
        date_from, date_to = self._resolve_dates(options)
        headless = not options['no_headless']
        mode = options['mode']

        self.stdout.write(
            f"Scrape mode={mode} {date_from}..{date_to} headless={headless}"
        )

        try:
            if mode == 'indices':
                if date_from != date_to:
                    raise CommandError('indices mode expects a single --date')
                result = run_indices(date_from, self._index_ids(options))
            elif mode == 'today-price':
                result = run_today_price(date_from, date_to, headless=headless)
            else:
                result = run_floorsheet(
                    source=options['source'],
                    symbols=self._symbols(options),
                    date_from=date_from,
                    date_to=date_to,
                    headless=headless,
                )
        except Exception as exc:  # noqa: BLE001 - surface a clear CLI error
            raise CommandError(f'Scrape failed: {exc}') from exc

        line = (
            f"{result.name}: status={result.status} rows={result.rows} "
            f"({result.detail}) in {result.duration}s"
        )
        if result.status == 'ok':
            self.stdout.write(self.style.SUCCESS(line))
        elif result.status == 'no_data':
            if options['allow_empty']:
                self.stdout.write(self.style.WARNING(f"{line} (allowed empty)"))
            else:
                raise CommandError(line)
        else:
            raise CommandError(line)

    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_dates(options):
        if options.get('date'):
            value = options['date']
            parsed = Command._parse_date(value)
            return parsed, parsed

        if not options.get('date_from') or not options.get('date_to'):
            raise CommandError('Provide --date, or both --from and --to')

        date_from = Command._parse_date(options['date_from'])
        date_to = Command._parse_date(options['date_to'])
        if date_from > date_to:
            raise CommandError('--from must be on or before --to')
        return date_from, date_to

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

    @staticmethod
    def _index_ids(options):
        raw = options.get('index_ids')
        if not raw:
            return None
        try:
            return [int(part.strip()) for part in raw.split(',') if part.strip()]
        except ValueError:
            raise CommandError('--index-ids must be comma-separated integers')
