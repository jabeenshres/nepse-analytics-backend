"""
Django management command to migrate data from old StockData app to new stock_data app.

This command copies all Stock and StockData records from the old app to the new app,
maintaining all relationships and data integrity.

Usage:
    python manage.py migrate_from_old_app [--dry-run] [--skip-stocks] [--skip-stock-data]
"""
import logging
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Migrate data from old StockData app to new stock_data app'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Run without actually saving data (for testing)',
        )
        parser.add_argument(
            '--skip-stocks',
            action='store_true',
            help='Skip migrating Stock records',
        )
        parser.add_argument(
            '--skip-stock-data',
            action='store_true',
            help='Skip migrating StockData records',
        )

    def handle(self, *args, **options):
        """Execute the migration command."""
        dry_run = options['dry_run']
        skip_stocks = options['skip_stocks']
        skip_stock_data = options['skip_stock_data']

        self.stdout.write(
            self.style.WARNING('=' * 70)
        )
        self.stdout.write(
            self.style.WARNING('Data Migration: StockData App -> stock_data App')
        )
        self.stdout.write(
            self.style.WARNING('=' * 70)
        )

        if dry_run:
            self.stdout.write(
                self.style.WARNING('\nDRY RUN MODE - No data will be saved\n')
            )

        try:
            # Import old models
            try:
                from StockData.models import Stock as OldStock
                from StockData.models import StockData as OldStockData
            except ImportError as e:
                self.stdout.write(
                    self.style.ERROR(
                        f'Failed to import old models: {e}\n'
                        'Make sure StockData app is still in INSTALLED_APPS'
                    )
                )
                return

            # Import new models
            from stock_data.models import Stock as NewStock
            from stock_data.models import StockData as NewStockData

            # Track statistics
            stats = {
                'stocks_created': 0,
                'stocks_updated': 0,
                'stocks_skipped': 0,
                'stock_data_created': 0,
                'stock_data_updated': 0,
                'stock_data_skipped': 0,
                'errors': []
            }

            # Migrate Stocks
            if not skip_stocks:
                self.stdout.write('\n' + self.style.SUCCESS('Migrating Stock records...'))
                stats = self._migrate_stocks(
                    OldStock, NewStock, stats, dry_run
                )
            else:
                self.stdout.write(
                    self.style.WARNING('\nSkipping Stock migration (--skip-stocks)')
                )

            # Migrate StockData
            if not skip_stock_data:
                self.stdout.write('\n' + self.style.SUCCESS('Migrating StockData records...'))
                stats = self._migrate_stock_data(
                    OldStockData, NewStockData, NewStock, stats, dry_run
                )
            else:
                self.stdout.write(
                    self.style.WARNING('\nSkipping StockData migration (--skip-stock-data)')
                )

            # Print summary
            self._print_summary(stats, dry_run)

        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'\nFatal error during migration: {e}')
            )
            logger.exception('Migration failed')
            raise

    def _migrate_stocks(self, OldStock, NewStock, stats, dry_run):
        """Migrate Stock records from old app to new app."""
        old_stocks = OldStock.objects.all()
        total = old_stocks.count()

        if total == 0:
            self.stdout.write(
                self.style.WARNING('  No Stock records found in old app')
            )
            return stats

        self.stdout.write(f'  Found {total} Stock records to migrate')

        with transaction.atomic():
            for idx, old_stock in enumerate(old_stocks, 1):
                try:
                    # Check if stock already exists in new app
                    new_stock, created = NewStock.objects.get_or_create(
                        symbol=old_stock.symbol,
                        defaults={
                            'security_id': old_stock.security_id,
                            'security_name': old_stock.security_name,
                            'fifty_two_weeks_high': old_stock.fifty_two_weeks_high,
                            'fifty_two_weeks_low': old_stock.fifty_two_weeks_low,
                            'LSTM_Mean_Absolute_Error': old_stock.LSTM_Mean_Absolute_Error,
                            'Overall_LSTM_Mean_Absolute_Error': old_stock.Overall_LSTM_Mean_Absolute_Error,
                            'LSTM_R_Square': old_stock.LSTM_R_Square,
                            'Overall_LSTM_R_Square': old_stock.Overall_LSTM_R_Square,
                            'RF_Mean_Absolute_Error': old_stock.RF_Mean_Absolute_Error,
                            'Overall_RF_Mean_Absolute_Error': old_stock.Overall_RF_Mean_Absolute_Error,
                            'RF_R_Square': old_stock.RF_R_Square,
                            'Overall_RF_R_Square': old_stock.Overall_RF_R_Square,
                        }
                    )

                    if created:
                        stats['stocks_created'] += 1
                        if not dry_run:
                            self.stdout.write(
                                f'  [{idx}/{total}] Created: {old_stock.symbol}'
                            )
                        else:
                            self.stdout.write(
                                f'  [{idx}/{total}] Would create: {old_stock.symbol}'
                            )
                    else:
                        # Update existing stock with latest data
                        updated = False
                        if new_stock.security_id != old_stock.security_id:
                            new_stock.security_id = old_stock.security_id
                            updated = True
                        if new_stock.security_name != old_stock.security_name:
                            new_stock.security_name = old_stock.security_name
                            updated = True
                        if new_stock.fifty_two_weeks_high != old_stock.fifty_two_weeks_high:
                            new_stock.fifty_two_weeks_high = old_stock.fifty_two_weeks_high
                            updated = True
                        if new_stock.fifty_two_weeks_low != old_stock.fifty_two_weeks_low:
                            new_stock.fifty_two_weeks_low = old_stock.fifty_two_weeks_low
                            updated = True

                        # Update ML metrics if they exist in old stock
                        if old_stock.LSTM_Mean_Absolute_Error is not None:
                            new_stock.LSTM_Mean_Absolute_Error = old_stock.LSTM_Mean_Absolute_Error
                            updated = True
                        if old_stock.Overall_LSTM_Mean_Absolute_Error is not None:
                            new_stock.Overall_LSTM_Mean_Absolute_Error = old_stock.Overall_LSTM_Mean_Absolute_Error
                            updated = True
                        if old_stock.LSTM_R_Square is not None:
                            new_stock.LSTM_R_Square = old_stock.LSTM_R_Square
                            updated = True
                        if old_stock.Overall_LSTM_R_Square is not None:
                            new_stock.Overall_LSTM_R_Square = old_stock.Overall_LSTM_R_Square
                            updated = True
                        if old_stock.RF_Mean_Absolute_Error is not None:
                            new_stock.RF_Mean_Absolute_Error = old_stock.RF_Mean_Absolute_Error
                            updated = True
                        if old_stock.Overall_RF_Mean_Absolute_Error is not None:
                            new_stock.Overall_RF_Mean_Absolute_Error = old_stock.Overall_RF_Mean_Absolute_Error
                            updated = True
                        if old_stock.RF_R_Square is not None:
                            new_stock.RF_R_Square = old_stock.RF_R_Square
                            updated = True
                        if old_stock.Overall_RF_R_Square is not None:
                            new_stock.Overall_RF_R_Square = old_stock.Overall_RF_R_Square
                            updated = True

                        if updated and not dry_run:
                            new_stock.save()
                            stats['stocks_updated'] += 1
                            self.stdout.write(
                                f'  [{idx}/{total}] Updated: {old_stock.symbol}'
                            )
                        elif updated and dry_run:
                            stats['stocks_updated'] += 1
                            self.stdout.write(
                                f'  [{idx}/{total}] Would update: {old_stock.symbol}'
                            )
                        else:
                            stats['stocks_skipped'] += 1

                except Exception as e:
                    error_msg = f'Error migrating stock {old_stock.symbol}: {e}'
                    stats['errors'].append(error_msg)
                    self.stdout.write(
                        self.style.ERROR(f'  [{idx}/{total}] {error_msg}')
                    )
                    logger.exception(error_msg)

            if dry_run:
                transaction.set_rollback(True)

        return stats

    def _migrate_stock_data(self, OldStockData, NewStockData, NewStock, stats, dry_run):
        """Migrate StockData records from old app to new app."""
        old_stock_data = OldStockData.objects.select_related('stock').all()
        total = old_stock_data.count()

        if total == 0:
            self.stdout.write(
                self.style.WARNING('  No StockData records found in old app')
            )
            return stats

        self.stdout.write(f'  Found {total} StockData records to migrate')

        # Create a mapping of old stock symbols to new stock objects
        stock_mapping = {}
        for new_stock in NewStock.objects.all():
            stock_mapping[new_stock.symbol] = new_stock

        with transaction.atomic():
            for idx, old_data in enumerate(old_stock_data, 1):
                try:
                    # Find corresponding new stock
                    old_stock_symbol = old_data.stock.symbol
                    if old_stock_symbol not in stock_mapping:
                        stats['stock_data_skipped'] += 1
                        self.stdout.write(
                            self.style.WARNING(
                                f'  [{idx}/{total}] Skipped: Stock "{old_stock_symbol}" not found in new app'
                            )
                        )
                        continue

                    new_stock = stock_mapping[old_stock_symbol]

                    # Create or update StockData
                    new_data, created = NewStockData.objects.update_or_create(
                        stock=new_stock,
                        date=old_data.date,
                        defaults={
                            'open_price': old_data.open_price,
                            'high_price': old_data.high_price,
                            'low_price': old_data.low_price,
                            'close_price': old_data.close_price,
                            'total_traded_quantity': old_data.total_traded_quantity,
                            'total_traded_value': old_data.total_traded_value,
                            'previous_day_close_price': old_data.previous_day_close_price,
                            'last_updated_price': old_data.last_updated_price,
                            'total_trades': old_data.total_trades,
                            'average_traded_price': old_data.average_traded_price,
                            'market_capitalization': old_data.market_capitalization,
                            'LSTM_predicted_close_price': old_data.LSTM_predicted_close_price,
                            'RF_predicted_close_price': old_data.RF_predicted_close_price,
                        }
                    )

                    if created:
                        stats['stock_data_created'] += 1
                        if not dry_run:
                            self.stdout.write(
                                f'  [{idx}/{total}] Created: {old_stock_symbol} - {old_data.date}'
                            )
                        else:
                            self.stdout.write(
                                f'  [{idx}/{total}] Would create: {old_stock_symbol} - {old_data.date}'
                            )
                    else:
                        stats['stock_data_updated'] += 1
                        if not dry_run:
                            self.stdout.write(
                                f'  [{idx}/{total}] Updated: {old_stock_symbol} - {old_data.date}'
                            )
                        else:
                            self.stdout.write(
                                f'  [{idx}/{total}] Would update: {old_stock_symbol} - {old_data.date}'
                            )

                except Exception as e:
                    error_msg = f'Error migrating stock data {old_data.stock.symbol} - {old_data.date}: {e}'
                    stats['errors'].append(error_msg)
                    self.stdout.write(
                        self.style.ERROR(f'  [{idx}/{total}] {error_msg}')
                    )
                    logger.exception(error_msg)

            if dry_run:
                transaction.set_rollback(True)

        return stats

    def _print_summary(self, stats, dry_run):
        """Print migration summary."""
        self.stdout.write('\n' + self.style.SUCCESS('=' * 70))
        self.stdout.write(self.style.SUCCESS('Migration Summary'))
        self.stdout.write(self.style.SUCCESS('=' * 70))

        mode = 'DRY RUN - ' if dry_run else ''
        self.stdout.write(f'\n{mode}Stock Records:')
        self.stdout.write(f'  Created: {stats["stocks_created"]}')
        self.stdout.write(f'  Updated: {stats["stocks_updated"]}')
        self.stdout.write(f'  Skipped: {stats["stocks_skipped"]}')

        self.stdout.write(f'\n{mode}StockData Records:')
        self.stdout.write(f'  Created: {stats["stock_data_created"]}')
        self.stdout.write(f'  Updated: {stats["stock_data_updated"]}')
        self.stdout.write(f'  Skipped: {stats["stock_data_skipped"]}')

        total_processed = (
            stats['stocks_created'] + stats['stocks_updated'] +
            stats['stock_data_created'] + stats['stock_data_updated']
        )
        self.stdout.write(f'\n{mode}Total Records Processed: {total_processed}')

        if stats['errors']:
            self.stdout.write(
                self.style.ERROR(f'\nErrors encountered: {len(stats["errors"])}')
            )
            for error in stats['errors'][:10]:  # Show first 10 errors
                self.stdout.write(self.style.ERROR(f'  - {error}'))
            if len(stats['errors']) > 10:
                self.stdout.write(
                    self.style.ERROR(f'  ... and {len(stats["errors"]) - 10} more errors')
                )

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    '\nThis was a DRY RUN. No data was actually saved.\n'
                    'Run without --dry-run to perform the actual migration.'
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS('\nMigration completed successfully!')
            )
