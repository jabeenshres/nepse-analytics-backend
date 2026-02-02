"""
NEPSE Indices Scraper
Scrapes datewise indices data from nepalstock.com/indices using Selenium.
Runs in headless mode for automated scraping.
"""

import logging
import time
import re
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import List, Dict, Optional, Set

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    WebDriverException,
    StaleElementReferenceException,
    ElementClickInterceptedException,
)
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Constants
BASE_URL = "https://nepalstock.com/indices"
PAGE_LOAD_WAIT_TIME = 15  # Increased for Angular app
ELEMENT_WAIT_TIMEOUT = 30  # Increased for Angular app
PAGINATION_WAIT_TIME = 5
ANGULAR_BOOTSTRAP_WAIT = 15  # Time for Angular to fully bootstrap

# Index mappings
INDEX_MAPPING = {
    51: 'Banking SubIndex',
    52: 'Hotels And Tourism Index',
    53: 'Others Index',
    54: 'HydroPower Index',
    55: 'Development Bank Index',
    56: 'Manufacturing And Processing',
    57: 'Sensitive Index',
    58: 'NEPSE Index',
    59: 'Non Life Insurance',
    60: 'Finance Index',
    61: 'Trading Index',
    62: 'Float Index',
    63: 'Sensitive Float Index',
    64: 'Microfinance Index',
    65: 'Life Insurance',
    66: 'Mutual Fund',
    67: 'Investment Index',
}


class NepseIndicesScraper:
    """Scraper for NEPSE indices data from nepalstock.com."""

    def __init__(self):
        self.driver = None
        self.wait = None

    def _init_driver(self):
        """Initialize the Chrome WebDriver in headless mode."""
        chrome_options = webdriver.ChromeOptions()
        
        # Headless mode
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--disable-notifications")
        chrome_options.add_argument("--disable-popup-blocking")
        chrome_options.add_argument("--enable-javascript")
        
        # User agent to appear as real browser
        chrome_options.add_argument(
            "--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        
        # Prevent detection
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        
        # Accept notifications to prevent popup
        chrome_options.add_experimental_option("prefs", {
            "profile.default_content_setting_values.notifications": 1
        })

        self.driver = webdriver.Chrome(options=chrome_options)
        self.driver.implicitly_wait(5)
        self.wait = WebDriverWait(self.driver, ELEMENT_WAIT_TIMEOUT)
        
        # Set page load timeout
        self.driver.set_page_load_timeout(90)
        
        print("Chrome WebDriver initialized in headless mode")

    def _close_driver(self):
        """Close the WebDriver."""
        if self.driver:
            try:
                self.driver.quit()
                print("WebDriver closed")
            except Exception as e:
                logger.warning(f"Error closing driver: {e}")
            finally:
                self.driver = None
                self.wait = None

    def load_page(self) -> bool:
        """Load the indices page."""
        try:
            print(f"Loading page: {BASE_URL}")
            self.driver.get(BASE_URL)
            
            # Wait for Angular to bootstrap - this is critical for Angular SPAs
            print(f"Waiting {ANGULAR_BOOTSTRAP_WAIT}s for Angular to bootstrap...")
            time.sleep(ANGULAR_BOOTSTRAP_WAIT)
            
            # Wait for page to be ready
            self.wait.until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
            
            # Wait for the Angular component to appear
            print("Waiting for Angular component...")
            self.wait.until(
                EC.presence_of_element_located((By.TAG_NAME, "app-datewise-indices"))
            )
            
            # Wait for table rows to be present (actual data loaded)
            print("Waiting for table data...")
            self.wait.until(
                EC.presence_of_element_located((By.XPATH, "//tbody/tr"))
            )
            
            # Additional wait for data to settle
            time.sleep(2)
            
            # Verify we have data
            rows = self.driver.find_elements(By.XPATH, "//tbody/tr")
            print(f"Page loaded successfully with {len(rows)} rows")
            return len(rows) > 0
            
        except TimeoutException:
            print("Timeout waiting for page to load")
            return False
        except Exception as e:
            print(f"Error loading page: {e}")
            return False

    def select_index(self, index_id: int) -> bool:
        """Select an index from the dropdown."""
        try:
            print(f"Selecting index: {index_id} ({INDEX_MAPPING.get(index_id, 'Unknown')})")
            
            # Find all select elements
            selects = self.driver.find_elements(By.TAG_NAME, "select")
            
            if len(selects) < 1:
                print("No select dropdowns found")
                return False
            
            # First select is the index dropdown
            dropdown = selects[0]
            
            # Use Select to interact with dropdown
            select = Select(dropdown)
            select.select_by_value(str(index_id))
            
            time.sleep(2)
            print(f"Selected index: {INDEX_MAPPING.get(index_id, str(index_id))}")
            return True
            
        except Exception as e:
            print(f"Error selecting index {index_id}: {e}")
            return False

    def set_items_per_page(self, items: int = 500) -> bool:
        """Set items per page to maximize data per request."""
        try:
            print(f"Setting items per page to: {items}")
            
            # Find all selects - second one is items per page
            selects = self.driver.find_elements(By.TAG_NAME, "select")
            
            if len(selects) >= 2:
                items_dropdown = selects[1]
            else:
                # Try to find by looking for the one with specific options
                items_dropdown = self.driver.find_element(
                    By.XPATH, "//select[.//option[@value='500']]"
                )
            
            select = Select(items_dropdown)
            select.select_by_value(str(items))
            
            time.sleep(2)
            print(f"Items per page set to: {items}")
            return True
            
        except Exception as e:
            print(f"Error setting items per page: {e}")
            return False

    def click_filter_button(self) -> bool:
        """Click the filter button to apply selections."""
        try:
            print("Clicking filter button...")
            
            # Find button by text content
            filter_btn = self.driver.find_element(
                By.XPATH, "//button[contains(text(), 'Filter')]"
            )
            
            # Scroll into view
            self.driver.execute_script("arguments[0].scrollIntoView(true);", filter_btn)
            time.sleep(1)
            
            # Click using JavaScript
            self.driver.execute_script("arguments[0].click();", filter_btn)
            
            # Wait for data to load - Angular needs time to update
            print("Waiting for data to load...")
            time.sleep(PAGINATION_WAIT_TIME)
            
            # Wait for table rows to be present
            self.wait.until(
                EC.presence_of_element_located((By.XPATH, "//tbody/tr"))
            )
            
            # Additional wait for data to settle
            time.sleep(2)
            
            rows = self.driver.find_elements(By.XPATH, "//tbody/tr")
            print(f"Filter applied successfully - {len(rows)} rows loaded")
            return True
            
        except Exception as e:
            print(f"Error clicking filter button: {e}")
            return False

    def _parse_number(self, value: str) -> Optional[Decimal]:
        """Parse a number string, handling commas and special characters."""
        if not value:
            return None
        
        try:
            # Remove commas, parentheses, percentage signs, and whitespace
            cleaned = value.replace(',', '').replace('(', '').replace(')', '').replace('%', '').strip()
            
            # Handle empty or invalid values
            if not cleaned or cleaned == '-':
                return Decimal('0')
            
            return Decimal(cleaned)
        except (InvalidOperation, ValueError) as e:
            logger.warning(f"Could not parse number: {value} - {e}")
            return None

    def _parse_change_value(self, cell) -> tuple:
        """Parse absolute change and percentage change from a cell."""
        try:
            text = cell.get_text(strip=True)
            
            # Check for negative (changedown class)
            is_negative = 'changedown' in str(cell) or 'negative' in str(cell)
            
            # Extract the number
            value = self._parse_number(text)
            
            if value is not None and is_negative and value > 0:
                value = -value
            
            return value
        except Exception as e:
            logger.warning(f"Error parsing change value: {e}")
            return Decimal('0')

    def parse_table_data(self, index_id: int) -> List[Dict]:
        """Parse the indices table data from current page."""
        records = []
        
        try:
            # Get the page source and parse with BeautifulSoup
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            
            # Find the table
            table = soup.find('table', class_='table')
            if not table:
                print("Table not found on page")
                return records
            
            tbody = table.find('tbody')
            if not tbody:
                print("Table body not found")
                return records
            
            rows = tbody.find_all('tr')
            print(f"Found {len(rows)} rows in table")
            
            for row in rows:
                cells = row.find_all('td')
                
                if len(cells) < 12:
                    continue
                
                try:
                    # Parse date (format: YYYY-MM-DD)
                    date_text = cells[1].get_text(strip=True)
                    try:
                        date_obj = datetime.strptime(date_text, '%Y-%m-%d').date()
                    except ValueError:
                        print(f"Invalid date format: {date_text}")
                        continue
                    
                    # Parse numeric values
                    close = self._parse_number(cells[2].get_text(strip=True))
                    high = self._parse_number(cells[3].get_text(strip=True))
                    low = self._parse_number(cells[4].get_text(strip=True))
                    absolute_change = self._parse_change_value(cells[5])
                    percentage_change = self._parse_change_value(cells[6])
                    fifty_two_weeks_high = self._parse_number(cells[7].get_text(strip=True))
                    fifty_two_weeks_low = self._parse_number(cells[8].get_text(strip=True))
                    turnover_value = self._parse_number(cells[9].get_text(strip=True))
                    turnover_volume = self._parse_number(cells[10].get_text(strip=True))
                    total_transactions = self._parse_number(cells[11].get_text(strip=True))
                    
                    # Skip if essential values are missing
                    if close is None or high is None or low is None:
                        continue
                    
                    record = {
                        'index_id': index_id,
                        'index_name': INDEX_MAPPING.get(index_id, f'Index {index_id}'),
                        'date': date_obj,
                        'close': close,
                        'high': high,
                        'low': low,
                        'absolute_change': absolute_change or Decimal('0'),
                        'percentage_change': percentage_change or Decimal('0'),
                        'fifty_two_weeks_high': fifty_two_weeks_high or Decimal('0'),
                        'fifty_two_weeks_low': fifty_two_weeks_low or Decimal('0'),
                        'turnover_value': turnover_value or Decimal('0'),
                        'turnover_volume': int(turnover_volume) if turnover_volume else 0,
                        'total_transactions': int(total_transactions) if total_transactions else 0,
                    }
                    
                    records.append(record)
                    
                except Exception as e:
                    logger.warning(f"Error parsing row: {e}")
                    continue
            
            print(f"Parsed {len(records)} records from current page")
            
        except Exception as e:
            print(f"Error parsing table data: {e}")
        
        return records

    def get_pagination_info(self) -> Dict:
        """Get pagination information."""
        try:
            pagination = self.driver.find_element(By.CSS_SELECTOR, "pagination-controls")
            
            # Get total pages from the text like "1 / 12"
            small_screen = pagination.find_element(By.CSS_SELECTOR, "li.small-screen")
            text = small_screen.text.strip()
            
            match = re.search(r'(\d+)\s*/\s*(\d+)', text)
            if match:
                current_page = int(match.group(1))
                total_pages = int(match.group(2))
                
                print(f"Pagination: Page {current_page} of {total_pages}")
                return {
                    'current_page': current_page,
                    'total_pages': total_pages
                }
        except Exception as e:
            print(f"Error getting pagination info: {e}")
        
        return {'current_page': 1, 'total_pages': 1}

    def click_next_page(self) -> bool:
        """Click the next page button."""
        try:
            # Find the next button
            next_btn = self.wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "li.pagination-next a"))
            )
            
            # Check if disabled
            parent = next_btn.find_element(By.XPATH, "..")
            if 'disabled' in parent.get_attribute('class'):
                print("Next button is disabled - no more pages")
                return False
            
            # Scroll into view and click
            self.driver.execute_script("arguments[0].scrollIntoView(true);", next_btn)
            time.sleep(0.5)
            self.driver.execute_script("arguments[0].click();", next_btn)
            
            time.sleep(PAGINATION_WAIT_TIME)
            print("Navigated to next page")
            return True
            
        except Exception as e:
            print(f"Error clicking next page: {e}")
            return False

    def scrape_index(self, index_id: int, max_pages: int = None, target_date: str = None) -> List[Dict]:
        """
        Scrape data for a specific index.
        
        Args:
            index_id: The index ID to scrape
            max_pages: Maximum number of pages to scrape (None = all)
            target_date: If provided (YYYY-MM-DD), only return data for this specific date
        """
        all_records = []
        seen_dates = set()
        
        print(f"\n{'='*60}")
        print(f"Scraping index: {INDEX_MAPPING.get(index_id, str(index_id))}")
        if target_date:
            print(f"Target date filter: {target_date}")
        print(f"{'='*60}")
        
        # Parse target date if provided
        target_date_obj = None
        if target_date:
            try:
                target_date_obj = datetime.strptime(target_date, '%Y-%m-%d').date()
            except ValueError:
                print(f"Invalid target_date format: {target_date}. Use YYYY-MM-DD")
                return all_records
        
        try:
            # Select the index
            if not self.select_index(index_id):
                return all_records
            
            # Set items per page to 500
            if not self.set_items_per_page(500):
                print("Warning: Could not set items per page, using default")
            
            # Click filter to apply
            if not self.click_filter_button():
                return all_records
            
            # Get pagination info
            pagination = self.get_pagination_info()
            total_pages = pagination.get('total_pages', 1)
            
            # If we have a target date, we only need to check first page
            # (latest data is on first page)
            if target_date_obj:
                max_pages = 1
                print(f"Target date specified - only scraping first page for latest data")
            
            if max_pages:
                total_pages = min(total_pages, max_pages)
            
            print(f"Will scrape {total_pages} pages")
            
            # Scrape each page
            current_page = 1
            found_target_date = False
            
            while current_page <= total_pages:
                print(f"\nScraping page {current_page}/{total_pages}...")
                
                # Parse data from current page
                records = self.parse_table_data(index_id)
                
                # Add only new records (avoid duplicates)
                for record in records:
                    date_key = str(record['date'])
                    
                    # If target_date is specified, only include matching records
                    if target_date_obj:
                        if record['date'] == target_date_obj:
                            if date_key not in seen_dates:
                                seen_dates.add(date_key)
                                all_records.append(record)
                                found_target_date = True
                                print(f"Found target date: {target_date}")
                    else:
                        if date_key not in seen_dates:
                            seen_dates.add(date_key)
                            all_records.append(record)
                
                print(f"Total unique records so far: {len(all_records)}")
                
                # If we found the target date on first page, we're done
                if target_date_obj and found_target_date:
                    break
                
                # Go to next page if not last page
                if current_page < total_pages:
                    if not self.click_next_page():
                        break
                
                current_page += 1
            
            if target_date_obj and not found_target_date:
                print(f"Warning: Target date {target_date} not found in scraped data")
            
            print(f"\nCompleted scraping {INDEX_MAPPING.get(index_id, str(index_id))}")
            print(f"Total records: {len(all_records)}")
            
        except Exception as e:
            print(f"Error scraping index {index_id}: {e}")
        
        return all_records

    def scrape_all_indices(self, index_ids: List[int] = None, max_pages_per_index: int = None, target_date: str = None) -> Dict[int, List[Dict]]:
        """
        Scrape data for multiple indices.
        
        Args:
            index_ids: List of index IDs to scrape (None = all)
            max_pages_per_index: Maximum pages per index
            target_date: If provided (YYYY-MM-DD), only return data for this specific date
        """
        if index_ids is None:
            index_ids = list(INDEX_MAPPING.keys())
        
        results = {}
        
        try:
            self._init_driver()
            
            # Load the page once
            if not self.load_page():
                print("Failed to load page")
                return results
            
            for index_id in index_ids:
                try:
                    records = self.scrape_index(index_id, max_pages_per_index, target_date)
                    results[index_id] = records
                    
                    # Small delay between indices
                    time.sleep(1)
                    
                except Exception as e:
                    print(f"Error scraping index {index_id}: {e}")
                    results[index_id] = []
            
        finally:
            self._close_driver()
        
        return results

    def scrape_single_index(self, index_id: int, max_pages: int = None, target_date: str = None) -> List[Dict]:
        """
        Scrape data for a single index.
        
        Args:
            index_id: The index ID to scrape
            max_pages: Maximum number of pages to scrape
            target_date: If provided (YYYY-MM-DD), only return data for this specific date
        """
        records = []
        
        try:
            self._init_driver()
            
            if not self.load_page():
                return records
            
            records = self.scrape_index(index_id, max_pages, target_date)
            
        finally:
            self._close_driver()
        
        return records


def save_indices_to_db(records: List[Dict], skip_existing: bool = True) -> Dict:
    """Save scraped indices data to database."""
    from .models import NepseIndex
    
    created_count = 0
    updated_count = 0
    skipped_count = 0
    error_count = 0
    
    if not records:
        return {
            'created': created_count,
            'updated': updated_count,
            'skipped': skipped_count,
            'errors': error_count
        }
    
    # Get existing records for this index
    index_id = records[0]['index_id']
    existing_dates = set()
    
    if skip_existing:
        existing_dates = set(
            NepseIndex.objects.filter(index_id=index_id)
            .values_list('date', flat=True)
        )
        print(f"Found {len(existing_dates)} existing dates for index {index_id}")
    
    for record in records:
        try:
            if skip_existing and record['date'] in existing_dates:
                skipped_count += 1
                continue
            
            obj, created = NepseIndex.objects.update_or_create(
                index_id=record['index_id'],
                date=record['date'],
                defaults={
                    'index_name': record['index_name'],
                    'close': record['close'],
                    'high': record['high'],
                    'low': record['low'],
                    'absolute_change': record['absolute_change'],
                    'percentage_change': record['percentage_change'],
                    'fifty_two_weeks_high': record['fifty_two_weeks_high'],
                    'fifty_two_weeks_low': record['fifty_two_weeks_low'],
                    'turnover_value': record['turnover_value'],
                    'turnover_volume': record['turnover_volume'],
                    'total_transactions': record['total_transactions'],
                }
            )
            
            if created:
                created_count += 1
            else:
                updated_count += 1
                
        except Exception as e:
            logger.error(f"Error saving record for date {record['date']}: {e}")
            error_count += 1
    
    print(f"Saved to DB - Created: {created_count}, Updated: {updated_count}, Skipped: {skipped_count}, Errors: {error_count}")
    
    return {
        'created': created_count,
        'updated': updated_count,
        'skipped': skipped_count,
        'errors': error_count
    }
