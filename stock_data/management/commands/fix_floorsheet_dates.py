"""
Repair floorsheet rows whose transaction_date does not match their contract number.

Background
----------
NEPSE contract numbers start with the trade date as ``YYYYMMDD``, e.g.
``2026110505013245`` was traded on 2026-11-05.

``NepalstockFloorsheetScraper`` used to stamp every row with ``date.today()``
because the floorsheet table has no date column. The daily floorsheet is published
a trading day late, so any run that happened before publication wrote the previous
session's contracts under the current date. Two runs on 2026-11-05 (04:17 UTC and
16:36 UTC) therefore produced one date bucket containing both 2026-11-04 and
2026-11-05 contracts.

This command derives the real date from the contract prefix and rewrites
``transaction_date``. It is safe to run repeatedly: rows that already match are
left alone, and ``(stock, transaction_no)`` is unique so moving a row cannot collide.

Usage
-----
    python manage.py fix_floorsheet_dates                     # report only
    python manage.py fix_floorsheet_dates --apply             # write changes
    python manage.py fix_floorsheet_dates --apply --batch-size 5000
"""
from collections import Counter

from django.core.management.base import BaseCommand
from django.db import transaction

from stock_data.models import FloorsheetData
from stock_data.nepalstock_floorsheet_scraper import NepalstockFloorsheetScraper


class Command(BaseCommand):
    help = (
        'Correct FloorsheetData.transaction_date using the date embedded in the '
        'contract number'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply',
            action='store_true',
            help='Write the corrected dates. Without this the command only reports.',
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=2000,
            help='Rows to update per bulk_update call (default: 2000).',
        )
        parser.add_argument(
            '--start-date',
            help='Only inspect rows on or after this YYYY-MM-DD date.',
        )
        parser.add_argument(
            '--end-date',
            help='Only inspect rows on or before this YYYY-MM-DD date.',
        )

    def handle(self, *args, **options):
        apply_changes = options['apply']
        batch_size = options['batch_size']

        if not apply_changes:
            self.stdout.write(self.style.WARNING(
                'REPORT ONLY - nothing will be written. Re-run with --apply to fix.'
            ))

        queryset = FloorsheetData.objects.all()
        if options['start_date']:
            queryset = queryset.filter(transaction_date__gte=options['start_date'])
        if options['end_date']:
            queryset = queryset.filter(transaction_date__lte=options['end_date'])

        self.stdout.write('Scanning rows...')
        already_correct = 0
        unparseable = 0
        pairs = Counter()
        pending = []  # (id, corrected_date)

        for row in queryset.only('id', 'transaction_no', 'transaction_date').iterator(
            chunk_size=batch_size
        ):
            contract_date = NepalstockFloorsheetScraper._date_from_contract(
                row.transaction_no
            )
            if contract_date is None:
                unparseable += 1
                continue

            contract_date = contract_date.date()
            if contract_date == row.transaction_date:
                already_correct += 1
                continue

            pairs[(row.transaction_date, contract_date)] += 1
            pending.append((row.id, contract_date))

        self.stdout.write(f'  already correct : {already_correct:,}')
        self.stdout.write(f'  unparseable     : {unparseable:,}')
        self.stdout.write(f'  to correct      : {len(pending):,}')

        if not pending:
            self.stdout.write(self.style.SUCCESS('Nothing to fix.'))
            return

        self.stdout.write('\nStored date -> corrected date (top 25 by row count):')
        for (old_date, new_date), count in pairs.most_common(25):
            self.stdout.write(f'  {old_date} -> {new_date}  ({count:,} rows)')

        if not apply_changes:
            self.stdout.write(self.style.WARNING(
                '\nNo changes written. Re-run with --apply to apply them.'
            ))
            return

        updated = 0
        with transaction.atomic():
            for offset in range(0, len(pending), batch_size):
                chunk = pending[offset:offset + batch_size]
                objs = [
                    FloorsheetData(id=row_id, transaction_date=new_date)
                    for row_id, new_date in chunk
                ]
                FloorsheetData.objects.bulk_update(
                    objs, ['transaction_date'], batch_size=batch_size
                )
                updated += len(chunk)
                self.stdout.write(f'  updated {updated:,}/{len(pending):,}')

        self.stdout.write(self.style.SUCCESS(f'\nDone. Corrected {updated:,} rows.'))
