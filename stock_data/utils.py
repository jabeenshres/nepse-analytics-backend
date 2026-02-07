"""
Utilities for scraping stock data from Nepal Stock Exchange.
"""
import logging
import os
import tempfile
import time
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.common.exceptions import WebDriverException, NoSuchElementException

from .constants import NEPAL_STOCK_DATE_FORMAT

logger = logging.getLogger(__name__)


class NepalStockScraper:
    """
    Scraper for fetching stock data from Nepal Stock Exchange website.
    """
    DOWNLOAD_WAIT_TIMEOUT = 60
    PAGE_LOAD_WAIT_TIME = 2
    DATE_CHANGE_WAIT_TIME = 3
    EXPECTED_PAGE_TITLE = "Nepal Stock Exchange"

    def __init__(self):
        """Initialize the scraper with Chrome WebDriver."""
        self.temp_dir = tempfile.mkdtemp()
        chrome_options = webdriver.ChromeOptions()
        download_preferences = {"download.default_directory": self.temp_dir}
        chrome_options.add_experimental_option("prefs", download_preferences)
        try:
            self.driver = webdriver.Chrome(options=chrome_options)
            logger.info("Chrome WebDriver initialized successfully")
        except WebDriverException as e:
            logger.error(f"Failed to initialize WebDriver: {e}")
            raise

    def load_page(self, url):
        """
        Load the Nepal Stock Exchange page.
        
        Args:
            url: URL to load
        
        Raises:
            Exception: If page title doesn't match expected title
        """
        try:
            self.driver.get(url)
            time.sleep(self.PAGE_LOAD_WAIT_TIME)
            if self.EXPECTED_PAGE_TITLE not in self.driver.title:
                raise ValueError(
                    f"Page title does not contain '{self.EXPECTED_PAGE_TITLE}'"
                )
            logger.info(f"Successfully loaded page: {url}")
        except Exception as e:
            logger.error(f"Error loading page {url}: {e}")
            raise

    def change_date(self, date):
        """
        Change the date filter on the page.
        
        Args:
            date: Date string in MM/DD/YYYY format
        
        Raises:
            Exception: If date change fails
        """
        try:
            date_input = self.driver.find_element(
                By.XPATH, "//input[@bsdatepicker='']"
            )
            filter_button = self.driver.find_element(
                By.CLASS_NAME, "box__filter--search"
            )
            date_input.clear()
            date_input.send_keys(date)
            filter_button.click()
            time.sleep(self.DATE_CHANGE_WAIT_TIME)
            logger.debug(f"Changed date to: {date}")
        except NoSuchElementException as e:
            logger.error(f"Element not found while changing date: {e}")
            raise Exception(f"Error while changing the date: {e}")

    def download_csv(self):
        """
        Click the download CSV button.
        
        Raises:
            Exception: If download button click fails
        """
        try:
            download_link = self.driver.find_element(By.CLASS_NAME, "table__file")
            download_link.click()
            logger.debug("Clicked download CSV button")
        except NoSuchElementException as e:
            logger.error(f"Download button not found: {e}")
            raise Exception(f"Error clicking download button: {e}")

    def check_content(self):
        """
        Check if the table has content.
        
        Returns:
            bool: True if table has data, False otherwise
        
        Raises:
            Exception: If table body element not found
        """
        try:
            table_body = self.driver.find_element(By.XPATH, "//tbody")
            has_data = len(table_body.find_elements(By.XPATH, ".//*")) > 0
            return has_data
        except NoSuchElementException as e:
            logger.error(f"Table body not found: {e}")
            raise Exception(f"Error while checking content: {e}")

    def download_wait(self):
        """
        Wait for CSV download to complete.
        
        Returns:
            int: Seconds waited, or -1 if timeout
        """
        seconds = 0
        while seconds < self.DOWNLOAD_WAIT_TIMEOUT:
            time.sleep(1)
            downloaded_files = os.listdir(self.temp_dir)
            is_downloading = any(
                filename.endswith(('.crdownload', '.part', '.tmp'))
                for filename in downloaded_files
            )
            if not is_downloading and downloaded_files:
                logger.debug(f"Download completed in {seconds} seconds")
                return seconds
            seconds += 1
        logger.warning("Download wait timeout")
        return -1

    def get_latest_file(self):
        """
        Get the most recently downloaded file.
        
        Returns:
            str: Path to the latest file
        """
        downloaded_files = os.listdir(self.temp_dir)
        full_paths = [
            os.path.join(self.temp_dir, filename)
            for filename in downloaded_files
        ]
        latest_file = max(full_paths, key=os.path.getmtime)
        return latest_file

    def loop_through_dates(self, Stock, StockData, days_back):
        """
        Loop through dates and download stock data.
        
        Args:
            Stock: Stock model class
            StockData: StockData model class
            days_back: Number of days to go back from start date
        """
        try:
            date_input = self.driver.find_element(By.XPATH, "//input[@bsdatepicker='']")
            start_date_str = date_input.get_attribute("value")
            start_date = datetime.strptime(start_date_str, NEPAL_STOCK_DATE_FORMAT)
            end_date = start_date - relativedelta(days=int(days_back))
            current_date = start_date

            logger.info(
                f"Starting data fetch from {start_date.date()} to {end_date.date()}"
            )

            while current_date >= end_date:
                date_str = current_date.strftime(NEPAL_STOCK_DATE_FORMAT)
                logger.info(f"Processing data for date: {date_str}")
                try:
                    self.change_date(date_str)
                    if self.check_content():
                        logger.info("Content found. Attempting to download CSV.")
                        self.download_csv()
                        if self.download_wait() >= 0:
                            downloaded_files = os.listdir(self.temp_dir)
                            if downloaded_files:
                                latest_file = self.get_latest_file()
                                self.save_to_database(latest_file, Stock, StockData)
                                os.remove(latest_file)
                                logger.info(f"Successfully processed date: {date_str}")
                            else:
                                logger.warning(f"No files found for date {date_str}.")
                    else:
                        logger.warning(f"No content available for date: {date_str}.")
                except Exception as e:
                    logger.error(f"Error processing date {date_str}: {e}")
                current_date -= timedelta(days=1)

            self.close()
            logger.info("Completed looping through dates")
        except Exception as e:
            logger.error(f"Error while looping through dates: {e}")
            raise

    def loop_through_date_range(self, Stock, StockData, date_from, date_to):
        """
        Loop through a date range and download stock data, skipping dates that already have data.
        
        Args:
            Stock: Stock model class
            StockData: StockData model class
            date_from: Start date (date object)
            date_to: End date (date object)
        
        Returns:
            dict: Statistics about the operation
        """
        stats = {
            'total_dates': 0,
            'dates_processed': 0,
            'dates_skipped': 0,
            'dates_failed': 0,
            'stocks_created': 0,
            'stocks_updated': 0,
        }
        
        try:
            # Ensure we have date objects
            if isinstance(date_from, datetime):
                date_from_obj = date_from.date()
            else:
                date_from_obj = date_from
            
            if isinstance(date_to, datetime):
                date_to_obj = date_to.date()
                current_date = date_to
            else:
                date_to_obj = date_to
                current_date = datetime.combine(date_to_obj, datetime.min.time())
            
            # Calculate total dates in range
            total_days = (date_to_obj - date_from_obj).days + 1
            stats['total_dates'] = total_days
            
            logger.info(
                f"Starting data fetch from {date_from_obj} to {date_to_obj} "
                f"({total_days} days)"
            )
            
            # Note: We no longer skip entire dates - bulk insert will handle skipping individual records
            # This allows filling in missing records for dates that have partial data
            logger.info("Processing all dates - bulk insert will skip existing stock+date combinations")

            while current_date.date() >= date_from_obj:
                date_str = current_date.strftime(NEPAL_STOCK_DATE_FORMAT)
                date_obj = current_date.date()
                
                # Optional: Check if date has complete data (all stocks) - can still process to fill gaps
                # For now, we process all dates and let bulk insert handle skipping
                
                logger.info(f"Processing data for date: {date_str}")
                try:
                    self.change_date(date_str)
                    if self.check_content():
                        logger.info("Content found. Attempting to download CSV.")
                        self.download_csv()
                        if self.download_wait() >= 0:
                            downloaded_files = os.listdir(self.temp_dir)
                            if downloaded_files:
                                latest_file = self.get_latest_file()
                                save_stats = self.save_to_database(
                                    latest_file, Stock, StockData
                                )
                                stats['stocks_created'] += save_stats.get('created', 0)
                                stats['stocks_updated'] += save_stats.get('updated', 0)
                                os.remove(latest_file)
                                stats['dates_processed'] += 1
                                logger.info(f"Successfully processed date: {date_str}")
                            else:
                                logger.warning(f"No files found for date {date_str}.")
                                stats['dates_failed'] += 1
                    else:
                        logger.warning(f"No content available for date: {date_str}.")
                        stats['dates_failed'] += 1
                except Exception as e:
                    logger.error(f"Error processing date {date_str}: {e}")
                    stats['dates_failed'] += 1
                
                current_date -= timedelta(days=1)

            logger.info(
                f"Completed date range processing. "
                f"Processed: {stats['dates_processed']}, "
                f"Skipped: {stats['dates_skipped']}, "
                f"Failed: {stats['dates_failed']}"
            )
            return stats
        except Exception as e:
            logger.error(f"Error while looping through date range: {e}")
            raise

    def save_to_database(self, file_path, Stock, StockData):
        """
        Save CSV data to database using bulk insert for better performance.
        
        Validates data, prepares all records, then bulk inserts new records.
        Skips existing stock+date combinations.
        
        Args:
            file_path: Path to CSV file
            Stock: Stock model class
            StockData: StockData model class
        
        Returns:
            dict: Statistics with 'created', 'updated', 'skipped', 'errors' counts
        
        Raises:
            Exception: If saving to database fails
        """
        from django.db import transaction as db_transaction
        from datetime import datetime as dt
        
        stats = {
            'created': 0, 
            'updated': 0, 
            'skipped': 0,
            'errors': 0,
            'stocks_created': 0,
            'total_csv_rows': 0,
            'error_messages': []
        }
        
        try:
            dataframe = pd.read_csv(file_path, on_bad_lines="skip")
            dataframe.columns = dataframe.columns.str.strip().str.lower()
            stats['total_csv_rows'] = len(dataframe)
            
            logger.info(f"Loaded {len(dataframe)} records from CSV file: {file_path}")

            # Step 1: Validate and prepare all stock records
            stocks_to_create = {}
            stocks_dict = {}  # Cache for existing stocks
            stock_data_to_create = []
            
            # Get all unique symbols from CSV
            unique_symbols = dataframe['symbol'].unique()
            
            # Fetch or create all stocks first
            for symbol in unique_symbols:
                symbol_upper = str(symbol).strip().upper()
                try:
                    stock = Stock.objects.get(symbol=symbol_upper)
                    stocks_dict[symbol_upper] = stock
                except Stock.DoesNotExist:
                    # Will create later
                    stocks_dict[symbol_upper] = None
            
            # Step 2: Process all rows and prepare data
            for idx, row in dataframe.iterrows():
                try:
                    row = row.where(pd.notna(row), None)
                    
                    # Validate required fields
                    symbol = str(row['symbol']).strip().upper() if row.get('symbol') else None
                    security_id = row.get('security id')
                    business_date = row.get('business date')
                    
                    if not symbol or not security_id or not business_date:
                        stats['errors'] += 1
                        stats['error_messages'].append(f"Row {idx+1}: Missing required fields (symbol, security_id, or date)")
                        continue
                    
                    # Parse date - handle multiple formats
                    try:
                        if isinstance(business_date, str):
                            # Clean the date string
                            business_date = business_date.strip()
                            # Try different date formats (most common first)
                            date_obj = None
                            date_formats = [
                                '%Y-%m-%d',      # 2026-02-02
                                '%m/%d/%Y',       # 02/02/2026
                                '%d/%m/%Y',       # 02/02/2026 (European)
                                '%Y.%m.%d',       # 2026.02.02
                                '%d-%m-%Y',       # 02-02-2026
                                '%Y/%m/%d',       # 2026/02/02
                            ]
                            for fmt in date_formats:
                                try:
                                    date_obj = dt.strptime(business_date, fmt).date()
                                    break
                                except ValueError:
                                    continue
                            if not date_obj:
                                # Try pandas parsing as fallback
                                try:
                                    date_obj = pd.to_datetime(business_date, errors='raise').date()
                                except:
                                    stats['errors'] += 1
                                    stats['error_messages'].append(f"Row {idx+1}: Invalid date format: '{business_date}'")
                                    continue
                        else:
                            # Handle pandas datetime or other types
                            try:
                                date_obj = pd.to_datetime(business_date, errors='raise').date()
                            except:
                                stats['errors'] += 1
                                stats['error_messages'].append(f"Row {idx+1}: Date parsing error: {business_date} (type: {type(business_date)})")
                                continue
                    except Exception as e:
                        stats['errors'] += 1
                        stats['error_messages'].append(f"Row {idx+1}: Date parsing error: {e} (value: {business_date})")
                        continue
                    
                    # Get or prepare stock
                    stock = stocks_dict.get(symbol)
                    if not stock:
                        # Prepare stock for creation
                        if symbol not in stocks_to_create:
                            stocks_to_create[symbol] = {
                                'symbol': symbol,
                                'security_id': int(security_id) if security_id else None,
                                'security_name': str(row.get('security name', '')).strip() or symbol,
                                'fifty_two_weeks_high': float(row.get('fifty two week high', 0) or 0),
                                'fifty_two_weeks_low': float(row.get('fifty two week low', 0) or 0),
                            }
                        # Will create stock later, store data with symbol reference
                        stock = None
                    
                    # Validate numeric fields
                    try:
                        open_price = float(row.get('open price', 0) or 0)
                        high_price = float(row.get('high price', 0) or 0)
                        low_price = float(row.get('low price', 0) or 0)
                        close_price = float(row.get('close price', 0) or 0)
                        total_traded_quantity = int(row.get('total traded quantity', 0) or 0)
                        total_traded_value = float(row.get('total traded value', 0) or 0)
                        previous_day_close_price = float(row.get('previous day close price', 0) or 0)
                        last_updated_price = float(row.get('last updated price', 0) or 0)
                        total_trades = int(row.get('total trades', 0) or 0)
                        average_traded_price = float(row.get('average traded price', 0) or 0)
                        market_cap = None
                        if row.get('market capitalization') and not pd.isna(row.get('market capitalization')):
                            market_cap = float(row['market capitalization'])
                    except (ValueError, TypeError) as e:
                        stats['errors'] += 1
                        stats['error_messages'].append(f"Row {idx+1}: Invalid numeric value: {e}")
                        continue
                    
                    # Prepare StockData object
                    if stock:
                        # Existing stock - store with stock reference
                        stock_data_to_create.append({
                            'stock': stock,
                            'date': date_obj,
                            'open_price': open_price,
                            'high_price': high_price,
                            'low_price': low_price,
                            'close_price': close_price,
                            'total_traded_quantity': total_traded_quantity,
                            'total_traded_value': total_traded_value,
                            'previous_day_close_price': previous_day_close_price,
                            'last_updated_price': last_updated_price,
                            'total_trades': total_trades,
                            'average_traded_price': average_traded_price,
                            'market_capitalization': market_cap,
                        })
                    else:
                        # New stock - will create stock first, then data
                        stock_data_to_create.append({
                            'symbol': symbol,
                            'date': date_obj,
                            'open_price': open_price,
                            'high_price': high_price,
                            'low_price': low_price,
                            'close_price': close_price,
                            'total_traded_quantity': total_traded_quantity,
                            'total_traded_value': total_traded_value,
                            'previous_day_close_price': previous_day_close_price,
                            'last_updated_price': last_updated_price,
                            'total_trades': total_trades,
                            'average_traded_price': average_traded_price,
                            'market_capitalization': market_cap,
                        })
                
                except Exception as e:
                    stats['errors'] += 1
                    stats['error_messages'].append(f"Row {idx+1}: Unexpected error: {e}")
                    logger.error(f"Error processing row {idx+1}: {e}")
                    continue
            
            # Step 3: Bulk create stocks first
            if stocks_to_create:
                with db_transaction.atomic():
                    stock_objects = [
                        Stock(**stock_data) for stock_data in stocks_to_create.values()
                    ]
                    created_stocks = Stock.objects.bulk_create(
                        stock_objects,
                        ignore_conflicts=True
                    )
                    stats['stocks_created'] = len(created_stocks)
                    
                    # Update stocks_dict with newly created stocks
                    for stock in created_stocks:
                        stocks_dict[stock.symbol] = stock
                    logger.info(f"Created {len(created_stocks)} new stocks")
            
            # Step 4: Convert all data to StockData objects and check for existing records
            if stock_data_to_create:
                # First, resolve all symbols to stock objects
                stock_data_objects = []
                for item in stock_data_to_create:
                    if 'symbol' in item:
                        # New stock - get from stocks_dict (should exist after Step 3)
                        symbol = item['symbol']
                        stock = stocks_dict.get(symbol)
                        if not stock:
                            stats['errors'] += 1
                            stats['error_messages'].append(f"Stock {symbol} not found after creation")
                            continue
                        stock_data_objects.append(StockData(
                            stock=stock,
                            date=item['date'],
                            open_price=item['open_price'],
                            high_price=item['high_price'],
                            low_price=item['low_price'],
                            close_price=item['close_price'],
                            total_traded_quantity=item['total_traded_quantity'],
                            total_traded_value=item['total_traded_value'],
                            previous_day_close_price=item['previous_day_close_price'],
                            last_updated_price=item['last_updated_price'],
                            total_trades=item['total_trades'],
                            average_traded_price=item['average_traded_price'],
                            market_capitalization=item['market_capitalization'],
                        ))
                    else:
                        # Existing stock - already has stock reference
                        stock_data_objects.append(StockData(
                            stock=item['stock'],
                            date=item['date'],
                            open_price=item['open_price'],
                            high_price=item['high_price'],
                            low_price=item['low_price'],
                            close_price=item['close_price'],
                            total_traded_quantity=item['total_traded_quantity'],
                            total_traded_value=item['total_traded_value'],
                            previous_day_close_price=item['previous_day_close_price'],
                            last_updated_price=item['last_updated_price'],
                            total_trades=item['total_trades'],
                            average_traded_price=item['average_traded_price'],
                            market_capitalization=item['market_capitalization'],
                        ))
                
                # Get existing stock+date combinations to skip
                if stock_data_objects:
                    # Extract unique stock_ids and dates for efficient querying
                    unique_stock_ids = list(set(sd.stock.id for sd in stock_data_objects))
                    unique_dates = list(set(sd.date for sd in stock_data_objects))
                    
                    # Query existing combinations in batches if needed (for very large datasets)
                    existing_combinations = set(
                        StockData.objects.filter(
                            stock_id__in=unique_stock_ids,
                            date__in=unique_dates
                        ).values_list('stock_id', 'date')
                    )
                    
                    logger.info(
                        f"Found {len(existing_combinations)} existing stock+date combinations "
                        f"out of {len(stock_data_objects)} records to process"
                    )
                    
                    # Filter out existing combinations
                    new_data = [
                        sd for sd in stock_data_objects
                        if (sd.stock.id, sd.date) not in existing_combinations
                    ]
                    
                    skipped_count = len(stock_data_objects) - len(new_data)
                    stats['skipped'] += skipped_count
                    
                    logger.info(
                        f"Prepared {len(new_data)} new records to insert "
                        f"(skipping {skipped_count} existing records)"
                    )
                    
                    # Bulk create new records
                    if new_data:
                        try:
                            with db_transaction.atomic():
                                created = StockData.objects.bulk_create(
                                    new_data,
                                    ignore_conflicts=True
                                )
                                stats['created'] = len(created)
                                logger.info(f"✓ Bulk created {len(created)} new stock data records")
                        except Exception as e:
                            logger.error(f"Error during bulk_create: {e}", exc_info=True)
                            # Fallback: try individual inserts for debugging
                            logger.warning("Attempting individual inserts for remaining records...")
                            created_count = 0
                            for sd in new_data:
                                try:
                                    StockData.objects.update_or_create(
                                        stock=sd.stock,
                                        date=sd.date,
                                        defaults={
                                            'open_price': sd.open_price,
                                            'high_price': sd.high_price,
                                            'low_price': sd.low_price,
                                            'close_price': sd.close_price,
                                            'total_traded_quantity': sd.total_traded_quantity,
                                            'total_traded_value': sd.total_traded_value,
                                            'previous_day_close_price': sd.previous_day_close_price,
                                            'last_updated_price': sd.last_updated_price,
                                            'total_trades': sd.total_trades,
                                            'average_traded_price': sd.average_traded_price,
                                            'market_capitalization': sd.market_capitalization,
                                        }
                                    )
                                    created_count += 1
                                except Exception as e2:
                                    stats['errors'] += 1
                                    stats['error_messages'].append(
                                        f"Failed to insert {sd.stock.symbol} for {sd.date}: {e2}"
                                    )
                            stats['created'] += created_count
                            logger.info(f"✓ Created {created_count} records via fallback method")
                    else:
                        logger.info("No new records to insert (all records already exist)")
            
            # Note: Updates are handled by checking existing records before bulk_create
            # If you need to update existing records, use update_or_create or separate update logic

            # Calculate summary
            total_processed = stats['created'] + stats['skipped'] + stats['errors']
            logger.info(
                f"\n{'='*60}\n"
                f"CSV Processing Summary for: {file_path}\n"
                f"{'='*60}\n"
                f"Total CSV rows: {stats['total_csv_rows']}\n"
                f"Records processed: {total_processed}\n"
                f"  ✓ Created: {stats['created']}\n"
                f"  ⊘ Skipped (already exist): {stats['skipped']}\n"
                f"  ✗ Errors: {stats['errors']}\n"
                f"New stocks created: {stats['stocks_created']}\n"
                f"{'='*60}\n"
            )
            
            if stats['error_messages']:
                logger.warning(
                    f"⚠ Encountered {len(stats['error_messages'])} errors during processing. "
                    f"Showing first 10 errors:"
                )
                for i, msg in enumerate(stats['error_messages'][:10], 1):
                    logger.warning(f"  {i}. {msg}")
                if len(stats['error_messages']) > 10:
                    logger.warning(f"  ... and {len(stats['error_messages']) - 10} more errors")
            
            # Warn if there's a significant discrepancy
            if stats['total_csv_rows'] > 0:
                processed_percentage = (total_processed / stats['total_csv_rows']) * 100
                if processed_percentage < 95:
                    logger.warning(
                        f"⚠ Only {processed_percentage:.1f}% of CSV rows were processed. "
                        f"This might indicate data quality issues or parsing errors."
                    )
            
            return stats
        except Exception as e:
            logger.error(f"Error while saving data to the database: {e}", exc_info=True)
            raise Exception(f"Error while saving data to the database: {e}")

    def close(self):
        """Close the WebDriver."""
        try:
            if self.driver:
                self.driver.quit()
                self.driver = None
                logger.info("WebDriver closed successfully")
        except Exception as e:
            logger.error(f"Error closing the driver: {e}")
