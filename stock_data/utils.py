"""
Utilities for scraping stock data from Nepal Stock Exchange.
"""
import logging
import os
import re
import tempfile
import time
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import pandas as pd
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.common.exceptions import (
    WebDriverException,
    NoSuchElementException,
    StaleElementReferenceException,
)

from .constants import NEPAL_STOCK_DATE_FORMAT
from .nepse_calendar import is_trading_day

logger = logging.getLogger(__name__)


class NepalStockScraper:
    """
    Scraper for fetching stock data from Nepal Stock Exchange website.
    """
    DOWNLOAD_WAIT_TIMEOUT = 60
    PAGE_LOAD_WAIT_TIME = 2
    DATE_CHANGE_WAIT_TIME = 3
    EXPECTED_PAGE_TITLE = "Nepal Stock Exchange"

    def __init__(self, headless: bool = True):
        """
        Initialize the scraper with Chrome WebDriver.

        Args:
            headless: Run Chrome without a visible window (default: True).
                The option set mirrors NepalstockFloorsheetScraper, which is known
                to work headless on this machine.
        """
        self.temp_dir = tempfile.mkdtemp()
        self.headless = headless
        chrome_options = webdriver.ChromeOptions()

        if headless:
            chrome_options.add_argument("--headless=new")

        # Essential options (same set that works for the floorsheet scraper)
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")

        # Disable automation detection
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option("useAutomationExtension", False)
        chrome_options.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )

        download_preferences = {"download.default_directory": self.temp_dir}
        chrome_options.add_experimental_option("prefs", download_preferences)
        try:
            self.driver = webdriver.Chrome(options=chrome_options)
            self.driver.implicitly_wait(3)
            print(f"  ✓ Chrome started ({'headless' if headless else 'visible'})")
            logger.info(
                f"Chrome WebDriver initialized successfully (headless={headless})"
            )
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
            print(f"  Loading page: {url}")
            self.driver.get(url)
            time.sleep(self.PAGE_LOAD_WAIT_TIME)
            if self.EXPECTED_PAGE_TITLE not in self.driver.title:
                raise ValueError(
                    f"Page title does not contain '{self.EXPECTED_PAGE_TITLE}'"
                )
            print(f"  ✓ Page loaded")
            logger.info(f"Successfully loaded page: {url}")
        except Exception as e:
            print(f"  ✗ Failed to load page: {e}")
            logger.error(f"Error loading page {url}: {e}")
            raise

    def _table_signature(self):
        """
        Cheap fingerprint of the current table body, used to detect a refresh.

        Returns:
            tuple: (row_count, first_row_text). (0, None) when no table exists.
        """
        try:
            tbody = self.driver.find_element(By.XPATH, "//tbody")
            rows = tbody.find_elements(By.XPATH, "./tr")
            if not rows:
                return (0, None)
            first_text = rows[0].text.replace("\n", "|")[:160]
            return (len(rows), first_text)
        except (NoSuchElementException, StaleElementReferenceException):
            return (0, None)

    def _wait_for_table_refresh(self, previous_signature, timeout=20):
        """
        Wait until the table body differs from ``previous_signature``.

        The page is Angular, so clicking Filter re-renders the table
        asynchronously. A fixed sleep either wastes time or races the render.

        Returns:
            bool: True if the table changed, False on timeout.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(0.5)
            if self._table_signature() != previous_signature:
                return True
        return False

    def _set_date_input_js(self, date):
        """Set the date field through the DOM (fallback for headless input quirks)."""
        date_input = self.driver.find_element(By.XPATH, "//input[@bsdatepicker='']")
        self.driver.execute_script(
            "arguments[0].value = arguments[1];"
            "arguments[0].dispatchEvent(new Event('input', {bubbles: true}));"
            "arguments[0].dispatchEvent(new Event('change', {bubbles: true}));",
            date_input,
            date,
        )

    def change_date(self, date):
        """
        Change the date filter on the page and wait for the table to refresh.

        Args:
            date: Date string in MM/DD/YYYY format

        Raises:
            Exception: If date change fails
        """
        try:
            previous_signature = self._table_signature()

            date_input = self.driver.find_element(
                By.XPATH, "//input[@bsdatepicker='']"
            )
            filter_button = self.driver.find_element(
                By.CLASS_NAME, "box__filter--search"
            )

            try:
                date_input.clear()
                date_input.send_keys(date)
            except (StaleElementReferenceException, WebDriverException) as e:
                logger.debug(f"send_keys failed ({e}), using JS fallback")
                self._set_date_input_js(date)

            self.driver.execute_script(
                "arguments[0].scrollIntoView({block: 'center'});", filter_button
            )
            try:
                filter_button.click()
            except (WebDriverException, StaleElementReferenceException):
                self.driver.execute_script("arguments[0].click();", filter_button)

            if not self._wait_for_table_refresh(previous_signature):
                print(f"    Table did not refresh for {date}, retrying with JS value set")
                logger.warning(
                    f"Table did not refresh after filtering {date}, retrying with JS value set"
                )
                self._set_date_input_js(date)
                filter_button = self.driver.find_element(
                    By.CLASS_NAME, "box__filter--search"
                )
                self.driver.execute_script("arguments[0].click();", filter_button)
                refreshed = self._wait_for_table_refresh(previous_signature)
                print(
                    f"    {'✓ Table refreshed' if refreshed else '✗ Table still unchanged'}"
                )
            else:
                print(f"    ✓ Table refreshed")

            logger.debug(f"Changed date to: {date}")
        except NoSuchElementException as e:
            print(f"    ✗ Date filter element not found: {e}")
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

    # ------------------------------------------------------------------
    # Today's Price table parsing (HTML, no CSV download)
    # ------------------------------------------------------------------

    # Header text -> model field. Headers are normalised before lookup, so
    # "Close Price* (Rs)" matches ("close price",).
    TODAY_PRICE_COLUMNS = {
        'symbol': ('symbol',),
        'close_price': ('close price',),
        'open_price': ('open price',),
        'high_price': ('high price',),
        'low_price': ('low price',),
        'total_traded_quantity': ('total traded quantity',),
        'total_traded_value': ('total traded value',),
        'total_trades': ('total trades',),
        'last_updated_price': ('ltp', 'last updated price', 'last traded price'),
        'previous_day_close_price': ('previous day close price',),
        'average_traded_price': ('average traded price',),
        'fifty_two_weeks_high': ('52 week high',),
        'fifty_two_weeks_low': ('52 week low',),
        'market_capitalization': ('marketcapitalization', 'market capitalization'),
    }

    @staticmethod
    def _normalize_header(text):
        """Lowercase, strip units/asterisks/parentheticals, collapse whitespace."""
        value = (text or '').lower().replace('*', ' ')
        value = re.sub(r'\(.*?\)', ' ', value)
        value = re.sub(r'\brs\b\.?', ' ', value)
        value = re.sub(r'[^a-z0-9]+', ' ', value).strip()
        return re.sub(r'\s+', ' ', value)

    @classmethod
    def _map_today_price_headers(cls, headers):
        """Map field name -> column index using the normalised header row."""
        normalized = [cls._normalize_header(h) for h in headers]
        mapping = {}
        for field, aliases in cls.TODAY_PRICE_COLUMNS.items():
            for index, header in enumerate(normalized):
                if header in aliases:
                    mapping[field] = index
                    break
        return mapping

    @staticmethod
    def _to_number(value):
        """
        Convert a table cell to a number.

        Handles thousands separators and the LTP change suffix, e.g.
        "836.70 (-8.3)" -> 836.7. Returns None for blank/dash cells.
        """
        if value is None:
            return None
        text = str(value).strip().replace(',', '')
        if not text or text in ('-', '—', '--'):
            return None
        # Drop a trailing "(change)" annotation. Only strip when the text before
        # the parenthesis still parses, so negative values are not mangled.
        if '(' in text:
            candidate = text.split('(')[0].strip()
            try:
                return float(candidate)
            except ValueError:
                pass
        try:
            return float(text)
        except ValueError:
            return None

    @classmethod
    def parse_today_price_html(cls, html_content, selected_date):
        """
        Parse the Today's Price table out of raw HTML.

        Kept Selenium-free so it can be unit tested against a saved page.

        Args:
            html_content: Raw page HTML.
            selected_date: date object the data belongs to.

        Returns:
            List of dicts with model-ready field names. Rows without a symbol or
            a close price are dropped.
        """
        soup = BeautifulSoup(html_content, 'html.parser')
        table = soup.find('table')
        if table is None:
            return []

        header_row = table.find('thead')
        header_cells = (
            header_row.find_all('th') if header_row else table.find_all('th')
        )
        headers = [cell.get_text(' ', strip=True) for cell in header_cells]
        mapping = cls._map_today_price_headers(headers)

        # Bail out if the header layout is not what we expect; positional guessing
        # would silently store the wrong column in the wrong field.
        if 'symbol' not in mapping or 'close_price' not in mapping:
            logger.warning(f"Unexpected Today's Price headers: {headers}")
            return []

        body = table.find('tbody')
        rows = body.find_all('tr') if body else table.find_all('tr')[1:]

        parsed = []
        for row in rows:
            cells = row.find_all('td')
            if not cells:
                continue
            values = [cell.get_text(' ', strip=True) for cell in cells]

            def cell(field):
                index = mapping.get(field)
                if index is None or index >= len(values):
                    return None
                return values[index]

            symbol = (cell('symbol') or '').strip().upper()
            if not symbol:
                continue

            close_price = cls._to_number(cell('close_price'))
            if close_price is None:
                logger.debug(f"Skipping {symbol}: no close price")
                continue

            def number_or_zero(field):
                return cls._to_number(cell(field)) or 0

            parsed.append({
                'symbol': symbol,
                'date': selected_date,
                'close_price': close_price,
                'open_price': number_or_zero('open_price'),
                'high_price': number_or_zero('high_price'),
                'low_price': number_or_zero('low_price'),
                'total_traded_quantity': int(number_or_zero('total_traded_quantity')),
                'total_traded_value': number_or_zero('total_traded_value'),
                'total_trades': int(number_or_zero('total_trades')),
                'last_updated_price': number_or_zero('last_updated_price'),
                'previous_day_close_price': number_or_zero('previous_day_close_price'),
                'average_traded_price': number_or_zero('average_traded_price'),
                'market_capitalization': cls._to_number(cell('market_capitalization')),
            })

        return parsed

    def parse_today_price_table(self, selected_date):
        """Parse the currently rendered Today's Price table."""
        return self.parse_today_price_html(self.driver.page_source, selected_date)

    def _set_items_per_page(self, size=500):
        """
        Raise the table's page size so a normal trading day fits on one page.

        The page defaults to 20 rows over ~18 pages. The filter bar exposes a
        <select> with 10/20/50/200/300/500 options.
        """
        try:
            from selenium.webdriver.support.ui import Select

            previous_signature = self._table_signature()
            select_el = self.driver.find_element(By.CSS_SELECTOR, "select")
            try:
                Select(select_el).select_by_value(str(size))
            except Exception:
                Select(select_el).select_by_visible_text(str(size))

            if not self._wait_for_table_refresh(previous_signature, timeout=10):
                # Angular may not react to the synthetic change; force it via JS.
                self.driver.execute_script(
                    "arguments[0].value = arguments[1];"
                    "arguments[0].dispatchEvent(new Event('change', {bubbles: true}));",
                    select_el,
                    str(size),
                )
                self._wait_for_table_refresh(previous_signature, timeout=10)

            print(f"  Setting items per page to {size}...")
            logger.info(f"Set items per page to {size}")
        except (NoSuchElementException, StaleElementReferenceException, WebDriverException) as e:
            print(f"  ⚠ Could not set items per page to {size}: {e}")
            logger.warning(f"Could not set items per page to {size}: {e}")

    def _go_to_next_page(self):
        """Click the ngx-pagination 'Next' control. Returns False when exhausted."""
        try:
            next_li = self.driver.find_element(
                By.CSS_SELECTOR, "ul.ngx-pagination li.pagination-next"
            )
            if "disabled" in (next_li.get_attribute("class") or ""):
                return False

            previous_signature = self._table_signature()
            link = next_li.find_element(By.TAG_NAME, "a")
            self.driver.execute_script("arguments[0].click();", link)
            return self._wait_for_table_refresh(previous_signature, timeout=15)
        except (NoSuchElementException, StaleElementReferenceException):
            return False

    def scrape_all_today_price_pages(self, selected_date):
        """
        Parse every page of the current result set, de-duplicated by symbol.

        With items-per-page raised this is normally a single page; the loop is a
        safety net for days with more rows than the page size.
        """
        rows_by_symbol = {}
        page = 0
        for _ in range(50):  # hard stop against a stuck paginator
            page += 1
            page_rows = self.parse_today_price_table(selected_date)
            print(f"    Page {page}: {len(page_rows)} rows")
            for row in page_rows:
                rows_by_symbol.setdefault(row['symbol'], row)
            if not self._go_to_next_page():
                break
        print(f"    Total: {len(rows_by_symbol)} unique symbols from {page} page(s)")
        return list(rows_by_symbol.values())

    @staticmethod
    def trading_days_between(date_from, date_to):
        """
        Return the actual NEPSE trading days in an inclusive date range.

        Uses the shared calendar (Sun-Thu before 2026-04-06, Mon-Fri after), so
        weekends and holidays do not cost a pointless filter click.
        """
        days = []
        current = date_from
        while current <= date_to:
            if is_trading_day(current):
                days.append(current)
            current += timedelta(days=1)
        return days

    def save_today_price_rows(self, rows, selected_date, Stock, StockData):
        """
        Persist parsed Today's Price rows for one date.

        Symbols that are not already in the Stock table are skipped: the HTML has
        no security id and Stock.security_id is unique/non-null, so creating them
        from this page alone is not safe. They are returned in ``unresolved``.

        Returns:
            dict: created, skipped, unresolved, errors
        """
        from django.db import transaction as db_transaction

        stats = {
            'created': 0,
            'skipped': 0,
            'errors': 0,
            'unresolved': [],
            'error_messages': [],
        }
        if not rows:
            print("    No rows to save")
            return stats

        print(
            f"    Saving {len(rows)} rows for {selected_date} "
            f"({len({r['symbol'] for r in rows})} symbols)"
        )

        symbols = {row['symbol'] for row in rows}
        stocks_by_symbol = {
            stock.symbol.upper(): stock
            for stock in Stock.objects.filter(symbol__in=symbols)
        }

        objects = []
        for row in rows:
            stock = stocks_by_symbol.get(row['symbol'])
            if stock is None:
                stats['unresolved'].append(row['symbol'])
                continue
            try:
                objects.append(StockData(
                    stock=stock,
                    date=selected_date,
                    open_price=row['open_price'],
                    high_price=row['high_price'],
                    low_price=row['low_price'],
                    close_price=row['close_price'],
                    total_traded_quantity=row['total_traded_quantity'],
                    total_traded_value=row['total_traded_value'],
                    previous_day_close_price=row['previous_day_close_price'],
                    last_updated_price=row['last_updated_price'],
                    total_trades=row['total_trades'],
                    average_traded_price=row['average_traded_price'],
                    market_capitalization=row['market_capitalization'],
                ))
            except (TypeError, ValueError) as e:
                stats['errors'] += 1
                stats['error_messages'].append(f"{row['symbol']}: {e}")

        if objects:
            existing_stock_ids = set(
                StockData.objects.filter(
                    stock_id__in=[obj.stock_id for obj in objects],
                    date=selected_date,
                ).values_list('stock_id', flat=True)
            )
            new_objects = [
                obj for obj in objects if obj.stock_id not in existing_stock_ids
            ]
            stats['skipped'] = len(objects) - len(new_objects)

            if new_objects:
                try:
                    with db_transaction.atomic():
                        StockData.objects.bulk_create(
                            new_objects, ignore_conflicts=True, batch_size=500
                        )
                    stats['created'] = len(new_objects)
                except Exception as e:
                    print(f"    ✗ Bulk insert failed: {e}")
                    logger.error(f"Bulk insert failed for {selected_date}: {e}")
                    stats['errors'] += len(new_objects)
                    stats['error_messages'].append(str(e))

        stats['unresolved'] = sorted(set(stats['unresolved']))
        print(
            f"    Saved: {stats['created']} new, {stats['skipped']} already existed, "
            f"{stats['errors']} errors"
        )
        if stats['unresolved']:
            print(
                f"    Skipped {len(stats['unresolved'])} unknown symbol(s): "
                f"{', '.join(stats['unresolved'])}"
            )
        return stats

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

    def loop_through_date_range(
        self, Stock, StockData, date_from, date_to, save_to_db=True
    ):
        """
        Loop through a date range, filter each date, and scrape the table directly.

        Non-trading days are skipped using the shared NEPSE calendar, and the CSV
        download path is no longer used (see the commented block below).

        Args:
            Stock: Stock model class
            StockData: StockData model class
            date_from: Start date (date object)
            date_to: End date (date object)
            save_to_db: Persist parsed rows to the database (default: True)

        Returns:
            dict: Statistics about the operation
        """
        stats = {
            # Keys the frontend reads
            'total_dates': 0,
            'dates_processed': 0,
            'dates_skipped': 0,
            'dates_failed': 0,
            'stocks_created': 0,
            'stocks_updated': 0,
            # Extra detail
            'trading_days': 0,
            'rows_parsed': 0,
            'rows_created': 0,
            'rows_skipped': 0,
            'unresolved_symbols': [],
            'error_messages': [],
        }

        try:
            if isinstance(date_from, datetime):
                date_from_obj = date_from.date()
            else:
                date_from_obj = date_from

            if isinstance(date_to, datetime):
                date_to_obj = date_to.date()
            else:
                date_to_obj = date_to

            total_days = (date_to_obj - date_from_obj).days + 1
            trading_days = self.trading_days_between(date_from_obj, date_to_obj)

            stats['total_dates'] = total_days
            stats['trading_days'] = len(trading_days)
            stats['dates_skipped'] = total_days - len(trading_days)

            print("=" * 60)
            print(
                f"Starting fetch: {date_from_obj} to {date_to_obj} "
                f"({total_days} calendar days, {len(trading_days)} trading days)"
            )
            print("=" * 60)
            logger.info(
                f"Starting data fetch from {date_from_obj} to {date_to_obj} "
                f"({total_days} days, {len(trading_days)} trading days)"
            )

            unresolved = set()

            # One page rather than 18. Done once; changing the date keeps it.
            self._set_items_per_page(500)

            for index, date_obj in enumerate(trading_days, 1):
                date_str = date_obj.strftime(NEPAL_STOCK_DATE_FORMAT)
                print(f"\n  Date {index}/{len(trading_days)}: {date_str}")
                logger.info(
                    f"[{index}/{len(trading_days)}] Processing data for date: {date_str}"
                )

                try:
                    self.change_date(date_str)
                    rows = self.scrape_all_today_price_pages(date_obj)

                    if not rows:
                        print(f"    ✗ No rows returned")
                        logger.warning(f"No rows found for date {date_str}")
                        stats['dates_failed'] += 1
                        continue

                    if save_to_db:
                        save_stats = self.save_today_price_rows(
                            rows, date_obj, Stock, StockData
                        )
                        stats['rows_created'] += save_stats['created']
                        stats['rows_skipped'] += save_stats['skipped']
                        if save_stats['errors']:
                            stats['error_messages'].extend(
                                save_stats['error_messages']
                            )
                        unresolved.update(save_stats['unresolved'])

                    stats['rows_parsed'] += len(rows)
                    stats['dates_processed'] += 1
                    print(f"    ✓ Parsed {len(rows)} rows")
                    logger.info(
                        f"Processed {date_str}: {len(rows)} rows parsed"
                    )

                except Exception as e:
                    print(f"    ✗ Error: {e}")
                    logger.error(f"Error processing date {date_str}: {e}")
                    stats['dates_failed'] += 1
                    stats['error_messages'].append(f"{date_str}: {e}")

            stats['unresolved_symbols'] = sorted(unresolved)

            print("\n" + "=" * 60)
            print("Fetch complete")
            print(f"  Dates processed : {stats['dates_processed']}")
            print(f"  Dates skipped   : {stats['dates_skipped']} (non-trading days)")
            print(f"  Dates failed    : {stats['dates_failed']}")
            print(f"  Rows parsed     : {stats['rows_parsed']}")
            if save_to_db:
                print(f"  Rows created    : {stats['rows_created']}")
                print(f"  Rows skipped    : {stats['rows_skipped']} (already existed)")
                print(f"  Unknown symbols : {len(stats['unresolved_symbols'])}")
                if stats['unresolved_symbols']:
                    print(f"    {', '.join(stats['unresolved_symbols'])}")
            else:
                print("  Saving          : disabled (save_to_db=false)")
            print("=" * 60)
            logger.info(
                f"Completed date range processing. "
                f"Processed: {stats['dates_processed']}, "
                f"Skipped: {stats['dates_skipped']}, "
                f"Failed: {stats['dates_failed']}, "
                f"Rows created: {stats['rows_created']}"
            )
            return stats
        except Exception as e:
            print(f"✗ Fetch failed: {e}")
            logger.error(f"Error while looping through date range: {e}")
            raise

    def _loop_through_date_range_csv(self, Stock, StockData, date_from, date_to):
        """
        Legacy CSV-download implementation, kept for reference only.

        Superseded by the table scraper above: headless Chrome downloads are
        unreliable, and the rendered table already contains everything we need.
        Run by switching loop_through_date_range back to this method.
        """
        stats = {
            'total_dates': 0,
            'dates_processed': 0,
            'dates_skipped': 0,
            'dates_failed': 0,
            'stocks_created': 0,
            'stocks_updated': 0,
        }

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

        total_days = (date_to_obj - date_from_obj).days + 1
        stats['total_dates'] = total_days

        while current_date.date() >= date_from_obj:
            date_str = current_date.strftime(NEPAL_STOCK_DATE_FORMAT)
            try:
                self.change_date(date_str)
                if self.check_content():
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
                        else:
                            stats['dates_failed'] += 1
                else:
                    stats['dates_failed'] += 1
            except Exception as e:
                logger.error(f"Error processing date {date_str}: {e}")
                stats['dates_failed'] += 1

            current_date -= timedelta(days=1)

        return stats

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
                print("  ✓ Browser closed")
                logger.info("WebDriver closed successfully")
        except Exception as e:
            print(f"  ⚠ Error closing the browser: {e}")
            logger.error(f"Error closing the driver: {e}")
