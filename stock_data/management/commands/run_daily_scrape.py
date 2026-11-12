"""
Run the full daily scrape for one date, with retries, database verification and alerting.

Usage
-----
    python manage.py run_daily_scrape
    python manage.py run_daily_scrape --date 2026-11-05
    python manage.py run_daily_scrape --only indices,today-price
    python manage.py run_daily_scrape --allow-empty        # known holiday
    python manage.py run_daily_scrape --dry-run            # show DB state only

Exit codes: 0 = every task satisfied, 1 = at least one task unfinished.
"""
import fcntl
import json
import os
from datetime import datetime
from urllib import request

from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from stock_data.nepse_calendar import is_trading_day
from stock_data.scraping_jobs import (
    is_satisfied,
    parse_holidays,
    run_floorsheet,
    run_indices,
    run_today_price,
    run_with_retries,
    verify_date,
)

TASKS = ('indices', 'today-price', 'floorsheet')
DATE_FORMAT = '%Y-%m-%d'


class Command(BaseCommand):
    help = 'Run the daily NEPSE scrapes, verify the database, retry and report'

    def add_arguments(self, parser):
        parser.add_argument(
            '--date',
            help='YYYY-MM-DD (default: today in the configured TIME_ZONE)',
        )
        parser.add_argument(
            '--only',
            help='Comma list of tasks: indices,today-price,floorsheet',
        )
        parser.add_argument('--skip', help='Comma list of tasks to skip')
        parser.add_argument('--attempts', type=int, default=3)
        parser.add_argument(
            '--delays',
            default='30,120,300',
            help='Retry delays in seconds (default: 30,120,300)',
        )
        parser.add_argument(
            '--allow-empty',
            action='store_true',
            help='Treat "no data" as a skip instead of a failure (holidays)',
        )
        parser.add_argument(
            '--min-stock-rows',
            type=int,
            default=int(os.environ.get('MIN_STOCK_DATA_ROWS', '100')),
            help='Rows required to consider Today\'s Price complete (default 100)',
        )
        parser.add_argument(
            '--lock-file',
            default=os.environ.get('SCRAPE_LOCK_FILE', '/tmp/nepse-scrape.lock'),
            help='Lock file that prevents overlapping runs',
        )
        parser.add_argument(
            '--alert-webhook',
            default=os.environ.get('SCRAPE_ALERT_WEBHOOK', ''),
            help='POST a JSON summary here on failure',
        )
        parser.add_argument(
            '--healthcheck-url',
            default=os.environ.get('SCRAPE_HEALTHCHECK_URL', ''),
            help='GET this URL after a fully successful run',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Only print the current database counts for the date',
        )
        parser.add_argument(
            '--no-warm-analytics',
            action='store_false',
            dest='warm_analytics',
            help='Skip precomputing StockAnalyticsCache after a successful run',
        )

    def handle(self, *args, **options):
        target = self._resolve_date(options.get('date'))
        holidays = parse_holidays(os.environ.get('NEPSE_HOLIDAYS'))

        if not is_trading_day(target) or target in holidays:
            reason = 'holiday' if target in holidays else 'weekend'
            self.stdout.write(self.style.WARNING(
                f'{target} is not a trading day ({reason}); nothing to do.'
            ))
            return

        tasks = self._tasks(options)

        if options['dry_run']:
            counts = verify_date(target)
            self.stdout.write(f'Dry run for {target}: {counts}')
            return

        lock = self._lock(options['lock_file'])
        if lock is None:
            self.stdout.write(self.style.WARNING(
                'Another scrape is already running; exiting without doing anything.'
            ))
            return

        try:
            self.stdout.write(
                f'Daily scrape {target}: {", ".join(tasks)} '
                f'(attempts={options["attempts"]})'
            )
            results = {}

            for task in tasks:
                result = run_with_retries(
                    task,
                    self._job(task, target),
                    attempts=max(1, options['attempts']),
                    delays=self._delays(options['delays']),
                )
                counts = verify_date(target)
                satisfied = is_satisfied(task, counts, options['min_stock_rows'])
                status, note = self._final_status(
                    result, satisfied, options['allow_empty']
                )

                results[task] = {
                    'status': status,
                    'rows': result.rows,
                    'detail': result.detail,
                    'duration': result.duration,
                    'note': note,
                    'counts': counts,
                }
                self._print_task(task, result, status, counts, note)

            # Stored data changed; drop any cached API responses.
            cache.clear()

            failed = [t for t, r in results.items() if r['status'] in ('no_data', 'error')]
            summary = self._summary(target, results, failed)
            self.stdout.write('\n' + summary)

            if failed:
                self._alert(options['alert_webhook'], summary)
                raise CommandError(f"Unfinished tasks: {', '.join(failed)}")

            if options['warm_analytics']:
                self._warm_analytics(target)

            self._ping(options['healthcheck_url'])
        finally:
            self._unlock(lock)

    def _warm_analytics(self, target):
        """Precompute analytics so the first request after the scrape is fast.

        A failure here must not fail the scrape: the data itself is already
        stored and the endpoints fall back to lazy computation.
        """
        self.stdout.write('Precomputing analytics cache...')
        try:
            call_command('warm_analytics', date=target.isoformat(), verbosity=0)
        except Exception as exc:  # noqa: BLE001 - best effort
            self.stderr.write(f'Analytics warm-up skipped: {exc}')
        else:
            self.stdout.write(self.style.SUCCESS('Analytics cache warmed.'))

    # ------------------------------------------------------------------
    # Task wiring
    # ------------------------------------------------------------------

    def _job(self, task, target):
        if task == 'indices':
            return lambda: run_indices(target)
        if task == 'today-price':
            return lambda: run_today_price(target, target)
        return lambda: run_floorsheet(source='nepalstock')

    @staticmethod
    def _final_status(result, satisfied, allow_empty):
        if satisfied:
            note = '' if result.status == 'ok' else 'already present in database'
            return 'ok', note
        if result.status == 'no_data':
            return ('skipped' if allow_empty else 'no_data'), 'no data'
        return 'error', result.detail

    def _print_task(self, task, result, status, counts, note):
        icon = {'ok': '✓', 'skipped': '–', 'no_data': '✗', 'error': '✗'}.get(status, '?')
        line = (
            f"  {icon} {task:12} {status:8} rows={result.rows:<7} "
            f"db[indices={counts['indices']}, stock={counts['stock_data']}, "
            f"floorsheet={counts['floorsheet']}] {result.duration}s"
        )
        if note:
            line += f"  ({note})"
        if status == 'ok':
            self.stdout.write(self.style.SUCCESS(line))
        elif status == 'skipped':
            self.stdout.write(self.style.WARNING(line))
        else:
            self.stdout.write(self.style.ERROR(line))

    @staticmethod
    def _summary(target, results, failed):
        lines = [f'NEPSE scrape summary for {target}']
        for task, row in results.items():
            lines.append(
                f"  {task}: {row['status']} (rows={row['rows']}, {row['detail']})"
            )
        lines.append('  overall: ' + ('FAILED' if failed else 'OK'))
        return '\n'.join(lines)

    # ------------------------------------------------------------------
    # Argument helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_date(value):
        if not value:
            return timezone.localdate()
        try:
            return datetime.strptime(value, DATE_FORMAT).date()
        except ValueError:
            raise CommandError(f"Invalid --date '{value}'. Use YYYY-MM-DD.")

    @staticmethod
    def _delays(raw):
        try:
            return tuple(int(part) for part in raw.split(',') if part.strip())
        except ValueError:
            raise CommandError('--delays must be comma-separated integers')

    def _tasks(self, options):
        only = self._csv(options.get('only'))
        skip = set(self._csv(options.get('skip')))

        if only:
            unknown = set(only) - set(TASKS)
            if unknown:
                raise CommandError(f"Unknown tasks: {', '.join(sorted(unknown))}")
            selected = [task for task in TASKS if task in only]
        else:
            selected = list(TASKS)

        selected = [task for task in selected if task not in skip]
        if not selected:
            raise CommandError('No tasks selected')
        return selected

    @staticmethod
    def _csv(value):
        return [part.strip() for part in (value or '').split(',') if part.strip()]

    # ------------------------------------------------------------------
    # Lock / alerting
    # ------------------------------------------------------------------

    @staticmethod
    def _lock(path):
        handle = None
        try:
            handle = open(path, 'w')
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            handle.write(str(os.getpid()))
            handle.flush()
            return handle
        except OSError:
            if handle:
                handle.close()
            return None

    @staticmethod
    def _unlock(handle):
        try:
            fcntl.flock(handle, fcntl.LOCK_UN)
            handle.close()
        except OSError:
            pass

    def _alert(self, url, text):
        if not url:
            return
        try:
            body = json.dumps({'text': text}).encode()
            req = request.Request(
                url,
                data=body,
                headers={'Content-Type': 'application/json'},
                method='POST',
            )
            request.urlopen(req, timeout=10).read()
            self.stdout.write('Alert sent.')
        except Exception as exc:  # noqa: BLE001 - never hide the original failure
            self.stderr.write(f'Alert webhook failed: {exc}')

    def _ping(self, url):
        if not url:
            return
        try:
            request.urlopen(url, timeout=10).read()
        except Exception as exc:  # noqa: BLE001 - best effort
            self.stderr.write(f'Healthcheck ping failed: {exc}')
