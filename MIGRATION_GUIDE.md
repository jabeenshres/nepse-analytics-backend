# Data Migration Guide

This guide explains how to migrate data from the old `StockData` app to the new `stock_data` app.

## Prerequisites

1. **Keep StockData in INSTALLED_APPS**: The old `StockData` app must remain in `INSTALLED_APPS` temporarily during migration.

2. **Backup your database**: Always backup your database before running migrations:
   ```bash
   # For SQLite
   cp db.sqlite3 db.sqlite3.backup
   
   # For PostgreSQL
   pg_dump your_database > backup.sql
   ```

3. **Migrations already run?** If you've already created and run migrations for `stock_data` app (which creates empty tables), that's perfectly fine! The migration command will work regardless:
   - If tables are empty: It will create all records
   - If tables already have data: It will update existing records and create new ones
   - The command uses `get_or_create` and `update_or_create` which handle both scenarios

   If you haven't run migrations yet:
   ```bash
   python manage.py makemigrations stock_data
   python manage.py migrate stock_data
   ```

## Migration Steps

### Step 1: Test Migration (Dry Run)

First, run the migration in dry-run mode to see what will happen without actually saving data:

```bash
python manage.py migrate_from_old_app --dry-run
```

This will:
- Show you how many records will be migrated
- Identify any potential issues
- Not save any data to the database

### Step 2: Review the Output

Check the dry-run output for:
- Number of records to be created/updated
- Any errors or warnings
- Skipped records and why

### Step 3: Run the Actual Migration

Once you're satisfied with the dry-run results, run the actual migration:

```bash
python manage.py migrate_from_old_app
```

This will:
- Copy all Stock records from `StockData.Stock` to `stock_data.Stock`
- Copy all StockData records from `StockData.StockData` to `stock_data.StockData`
- Maintain all relationships (foreign keys)
- Update existing records if they already exist
- Preserve all ML prediction metrics

### Step 4: Verify the Migration

After migration, verify the data:

```bash
# Check stock counts
python manage.py shell
```

```python
from stock_data.models import Stock, StockData
from StockData.models import Stock as OldStock, StockData as OldStockData

# Compare counts
print(f"Old Stocks: {OldStock.objects.count()}")
print(f"New Stocks: {Stock.objects.count()}")

print(f"Old StockData: {OldStockData.objects.count()}")
print(f"New StockData: {StockData.objects.count()}")

# Verify a few records
old_stock = OldStock.objects.first()
new_stock = Stock.objects.get(symbol=old_stock.symbol)
print(f"Old: {old_stock.symbol} - {old_stock.security_name}")
print(f"New: {new_stock.symbol} - {new_stock.security_name}")
```

## Command Options

### Basic Usage

```bash
python manage.py migrate_from_old_app
```

### Options

- `--dry-run`: Run without saving data (for testing)
  ```bash
  python manage.py migrate_from_old_app --dry-run
  ```

- `--skip-stocks`: Skip migrating Stock records (only migrate StockData)
  ```bash
  python manage.py migrate_from_old_app --skip-stocks
  ```

- `--skip-stock-data`: Skip migrating StockData records (only migrate Stocks)
  ```bash
  python manage.py migrate_from_old_app --skip-stock-data
  ```

- Combine options:
  ```bash
  python manage.py migrate_from_old_app --dry-run --skip-stocks
  ```

## What Gets Migrated

### Stock Records
- All fields including:
  - `symbol`, `security_id`, `security_name`
  - `fifty_two_weeks_high`, `fifty_two_weeks_low`
  - All ML metrics (LSTM and RF MAE, R-squared values)

### StockData Records
- All fields including:
  - All price fields (open, high, low, close)
  - Trading volumes and values
  - ML predictions (LSTM and RF predicted prices)
  - Market capitalization

### Relationships
- Foreign key relationships are maintained
- StockData records are linked to the correct Stock records in the new app

## Important: Tables Already Exist?

**If you've already run migrations** (which creates empty tables), the migration command will still work perfectly:
- Empty tables: All data will be inserted
- Tables with existing data: Existing records will be updated, new ones will be created
- The command is idempotent - you can run it multiple times safely

## Handling Duplicates

The migration script handles duplicates intelligently:

- **Stocks**: Uses `get_or_create` based on `symbol`. If a stock already exists, it updates the record with latest data.
- **StockData**: Uses `update_or_create` based on `stock` and `date`. Existing records are updated with latest data.

## Error Handling

The script:
- Continues processing even if individual records fail
- Logs all errors
- Provides a summary of errors at the end
- Uses database transactions to ensure data consistency

## After Migration

Once migration is complete and verified:

1. **Test the new API endpoints**:
   ```bash
   # Test stock listing
   curl http://localhost:8000/api/stock-data/
   
   # Test stock data listing
   curl http://localhost:8000/api/stock-data/entries/
   ```

2. **Remove old app** (optional, after thorough testing):
   - Remove `StockData` from `INSTALLED_APPS` in `settings.py`
   - Delete the `StockData` directory (optional, keep as backup)

3. **Update any external scripts** that reference the old app models

## Troubleshooting

### Import Error: Cannot import StockData models

**Solution**: Make sure `StockData` is still in `INSTALLED_APPS` in `settings.py`

### Foreign Key Constraint Errors

**Solution**: Make sure Stocks are migrated before StockData. Don't use `--skip-stocks` unless you've already migrated stocks.

### Duplicate Key Errors

**Solution**: The script handles duplicates automatically. If you see this error, there might be a data integrity issue in the old app.

### Missing Stock References

**Solution**: If StockData records reference stocks that don't exist, they will be skipped. Check the summary output for skipped records.

## Example Output

```
======================================================================
Data Migration: StockData App -> stock_data App
======================================================================

Migrating Stock records...
  Found 250 Stock records to migrate
  [1/250] Created: NBL
  [2/250] Created: ADBL
  [3/250] Updated: SCB
  ...

Migrating StockData records...
  Found 5000 StockData records to migrate
  [1/5000] Created: NBL - 2024-01-15
  [2/5000] Created: NBL - 2024-01-16
  ...

======================================================================
Migration Summary
======================================================================

Stock Records:
  Created: 245
  Updated: 5
  Skipped: 0

StockData Records:
  Created: 4950
  Updated: 50
  Skipped: 0

Total Records Processed: 5250

Migration completed successfully!
```

## Support

If you encounter issues during migration:
1. Check the error messages in the output
2. Review the logs
3. Verify database integrity
4. Restore from backup if needed
