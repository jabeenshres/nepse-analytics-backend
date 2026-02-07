"""
Floorsheet data scraper for nepalstock.com.

This module provides utilities to scrape floorsheet data from nepalstock.com
for individual stock symbols. The floorsheet contains individual trade
transactions executed on the NEPSE floor.

Uses Selenium for JavaScript-heavy pages that require interaction
(setting items per page, clicking filter button).
"""
import logging
import time
from datetime import datetime, date
from decimal import Decimal
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    WebDriverException, 
    NoSuchElementException,
    TimeoutException,
    StaleElementReferenceException,
    ElementClickInterceptedException,
)

logger = logging.getLogger(__name__)


@dataclass
class FloorsheetTransaction:
    """Represents a single floorsheet transaction."""
    transaction_date: datetime
    transaction_no: int
    buyer_broker: int
    seller_broker: int
    quantity: int
    rate: Decimal
    amount: Decimal


class NepalstockFloorsheetScraper:
    """
    Scraper for floorsheet data from nepalstock.com.
    
    Uses Selenium WebDriver for JavaScript-heavy pages.
    
    Usage:
        scraper = NepalstockFloorsheetScraper()
        transactions, metadata = scraper.scrape_from_url('MBJC', date_from='01/01/2026', date_to='01/31/2026')
        scraper.close()
    """
    
    BASE_URL = "https://nepalstock.com"  # Main page, then navigate to floorsheet
    PAGE_LOAD_WAIT_TIME = 1  # Reduced - site is fast
    ELEMENT_WAIT_TIMEOUT = 10  # Reduced
    FILTER_WAIT_TIME = 2  # Reduced - wait after clicking filter
    
    def __init__(self, headless: bool = False):
        """
        Initialize the scraper with Chrome WebDriver.
        
        Args:
            headless: Run browser in headless mode (default: False for easier debugging)
        """
        self.driver = None
        self.headless = headless
    
    def _init_driver(self):
        """Initialize Chrome WebDriver if not already initialized."""
        if self.driver is not None:
            return
            
        try:
            chrome_options = webdriver.ChromeOptions()
            
            if self.headless:
                chrome_options.add_argument("--headless=new")
            
            # Essential options
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--window-size=1920,1080")
            
            # Disable automation detection
            chrome_options.add_argument("--disable-blink-features=AutomationControlled")
            chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
            chrome_options.add_experimental_option("useAutomationExtension", False)
            
            # User agent
            chrome_options.add_argument(
                "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            
            # Allow notifications
            prefs = {
                "profile.default_content_setting_values.notifications": 1,
                "profile.default_content_settings.popups": 0,
            }
            chrome_options.add_experimental_option("prefs", prefs)
            
            self.driver = webdriver.Chrome(options=chrome_options)
            self.driver.implicitly_wait(3)
            
            logger.info("Chrome WebDriver initialized for Nepalstock scraper")
        except WebDriverException as e:
            logger.error(f"Failed to initialize WebDriver: {e}")
            raise
    
    def close(self):
        """Close the WebDriver."""
        try:
            if self.driver:
                self.driver.quit()
                self.driver = None
                logger.info("WebDriver closed successfully")
        except Exception as e:
            logger.error(f"Error closing the driver: {e}")
    
    def load_page(self) -> bool:
        """
        Load the main page, then navigate to floorsheet via navbar.
        
        Returns:
            bool: True if page loaded and navigated successfully
        """
        self._init_driver()
        
        try:
            # Load the main page
            print(f"  Loading main page: {self.BASE_URL}")
            self.driver.get(self.BASE_URL)
            
            # Wait for page to load
            WebDriverWait(self.driver, self.ELEMENT_WAIT_TIMEOUT).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
            
            time.sleep(self.PAGE_LOAD_WAIT_TIME)
            print(f"  ✓ Main page loaded")
            
            # Click "NEPSE Data" in navbar
            print(f"  Clicking 'NEPSE Data' in navbar...")
            nepse_data_menu = WebDriverWait(self.driver, self.ELEMENT_WAIT_TIMEOUT).until(
                EC.element_to_be_clickable((By.XPATH, "//a[contains(text(), 'NEPSE Data') or contains(text(), 'Nepse Data')]"))
            )
            self.driver.execute_script("arguments[0].click();", nepse_data_menu)
            time.sleep(0.5)  # Small wait for dropdown to appear
            print(f"  ✓ Clicked 'NEPSE Data'")
            
            # Click "Today's Floor Sheet" from dropdown
            print(f"  Clicking 'Today's Floor Sheet'...")
            floorsheet_link = WebDriverWait(self.driver, self.ELEMENT_WAIT_TIMEOUT).until(
                EC.element_to_be_clickable((By.XPATH, "//a[contains(text(), 'Floor Sheet') or contains(text(), 'floor sheet')]"))
            )
            self.driver.execute_script("arguments[0].click();", floorsheet_link)
            
            # Wait for floorsheet page to load
            time.sleep(self.PAGE_LOAD_WAIT_TIME)
            
            # Wait for page to be ready
            WebDriverWait(self.driver, self.ELEMENT_WAIT_TIMEOUT).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
            
            logger.info(f"Successfully navigated to floorsheet page")
            return True
                
        except Exception as e:
            logger.error(f"Error loading/navigating to floorsheet page: {e}")
            return False
    
    def _debug_save_page_source(self, filename: str = "debug_page.html"):
        """Save current page source for debugging."""
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(self.driver.page_source)
            logger.info(f"Saved page source to {filename} for debugging")
        except Exception as e:
            logger.warning(f"Could not save page source: {e}")
    
    def set_items_per_page(self, items: int = 500) -> bool:
        """
        Set the "Items Per Page" dropdown to the specified value.
        Uses the same approach as nepse_indices_scraper.
        
        Args:
            items: Number of items per page (default: 500)
            
        Returns:
            bool: True if successfully set
        """
        try:
            # Find all select elements - second one is typically items per page
            selects = self.driver.find_elements(By.TAG_NAME, "select")
            
            if len(selects) >= 2:
                # Second select is usually items per page (like in indices scraper)
                items_dropdown = selects[1]
            else:
                # Try to find by looking for the one with 500 option
                try:
                    items_dropdown = self.driver.find_element(
                        By.XPATH, "//select[.//option[@value='500']]"
                    )
                except:
                    # Fallback: use first select if only one exists
                    if len(selects) >= 1:
                        items_dropdown = selects[0]
                    else:
                        logger.warning("No select dropdowns found")
                        return False
            
            # Use Select class to interact with dropdown
            select = Select(items_dropdown)
            select.select_by_value(str(items))
            
            time.sleep(0.5)  # Reduced wait time
            logger.info(f"Set items per page to {items}")
            return True
            
        except Exception as e:
            logger.error(f"Error setting items per page: {e}")
            return False
    
    def click_filter_button(self) -> bool:
        """
        Click the Filter button to apply filters and load data.
        Uses the same approach as nepse_indices_scraper.
        
        Returns:
            bool: True if filter button clicked successfully
        """
        try:
            # Find button by text content (same as indices scraper)
            filter_btn = self.driver.find_element(
                By.XPATH, "//button[contains(text(), 'Filter')]"
            )
            
            # Scroll into view
            self.driver.execute_script("arguments[0].scrollIntoView(true);", filter_btn)
            time.sleep(0.3)  # Reduced wait time
            
            # Click using JavaScript (same as indices scraper)
            self.driver.execute_script("arguments[0].click();", filter_btn)
            
            # Wait for data to load
            time.sleep(self.FILTER_WAIT_TIME)
            
            # Wait for table rows to be present
            try:
                WebDriverWait(self.driver, self.ELEMENT_WAIT_TIMEOUT).until(
                    EC.presence_of_element_located((By.XPATH, "//tbody/tr"))
                )
                logger.info("Filter applied successfully - table data loaded")
            except TimeoutException:
                logger.warning("Timeout waiting for table data after filter click")
            
            return True
            
        except Exception as e:
            logger.error(f"Error clicking filter button: {e}")
            return False
    
    def get_pagination_info(self) -> Dict:
        """
        Get pagination information from the page.
        
        Returns:
            Dict with total_pages, current_page, has_pagination
        """
        info = {
            'total_pages': 1,
            'current_page': 1,
            'has_pagination': False,
            'total_records': 0
        }
        
        try:
            # Wait a bit for pagination to appear
            time.sleep(0.5)
            
            # Look for pagination elements
            # Common patterns: "Page 1 of 10", "Showing 1-500 of 5000", pagination links
            
            # Try to find pagination text
            pagination_text_selectors = [
                "//*[contains(text(), 'Page') and contains(text(), 'of')]",
                "//*[contains(text(), 'Showing') and contains(text(), 'of')]",
                "//*[contains(text(), 'page') and contains(text(), 'of')]",
                ".pagination-info",
                ".page-info",
                "[class*='pagination']",
            ]
            
            import re
            for selector in pagination_text_selectors:
                try:
                    if selector.startswith("//"):
                        elements = self.driver.find_elements(By.XPATH, selector)
                    else:
                        elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    
                    for elem in elements:
                        text = elem.text
                        # Extract page numbers from text like "Page 1 of 10" or "Showing 1-500 of 5000"
                        # Pattern: "Page X of Y"
                        page_match = re.search(r'page\s+(\d+)\s+of\s+(\d+)', text, re.IGNORECASE)
                        if page_match:
                            info['current_page'] = int(page_match.group(1))
                            info['total_pages'] = int(page_match.group(2))
                            info['has_pagination'] = info['total_pages'] > 1
                            logger.info(f"Found pagination info from text: {text}")
                            print(f"  Pagination text found: {text}")
                            break
                        
                        # Pattern: "Showing X-Y of Z"
                        showing_match = re.search(r'showing\s+(\d+)[-\s]+(\d+)\s+of\s+(\d+)', text, re.IGNORECASE)
                        if showing_match:
                            total = int(showing_match.group(3))
                            info['total_records'] = total
                            # Estimate pages (assuming 500 per page)
                            if total > 500:
                                info['total_pages'] = (total + 499) // 500
                                info['has_pagination'] = True
                            logger.info(f"Found total records from text: {text}")
                            print(f"  Pagination text found: {text} (total: {total})")
                            break
                    
                    if info['has_pagination']:
                        break
                except Exception:
                    continue
            
            # Try to find pagination links/buttons (Next, page numbers, etc.)
            if not info['has_pagination']:
                # Look for "Next" button - if it exists, there's pagination
                try:
                    next_buttons = self.driver.find_elements(By.XPATH, 
                        "//a[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'next')] | "
                        "//button[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'next')]"
                    )
                    if next_buttons:
                        # Check if next button is enabled (not disabled)
                        for btn in next_buttons:
                            if btn.is_displayed() and 'disabled' not in (btn.get_attribute('class') or '').lower():
                                info['has_pagination'] = True
                                # Try to estimate pages by counting page number links
                                page_links = self.driver.find_elements(By.CSS_SELECTOR, 
                                    ".pagination a, .pagination button, [class*='pagination'] a"
                                )
                                max_page = 1
                                for link in page_links:
                                    try:
                                        text = link.text.strip()
                                        if text.isdigit():
                                            page_num = int(text)
                                            if page_num > max_page:
                                                max_page = page_num
                                    except:
                                        pass
                                if max_page > 1:
                                    info['total_pages'] = max_page
                                else:
                                    # If we have next button but can't count pages, assume multiple pages
                                    info['total_pages'] = 2  # At least 2 pages
                                logger.info(f"Found pagination via Next button, estimated {info['total_pages']} pages")
                                print(f"  Found Next button - pagination exists (estimated {info['total_pages']} pages)")
                                break
                except Exception as e:
                    logger.debug(f"Error checking for Next button: {e}")
                
                # Also try to find page number links
                if not info['has_pagination']:
                    pagination_link_selectors = [
                        ".pagination a",
                        ".pagination button",
                        "[class*='pagination'] a",
                        "[class*='pagination'] button",
                        "a[href*='page']",
                        "button[onclick*='page']",
                    ]
                    
                    max_page = 1
                    for selector in pagination_link_selectors:
                        try:
                            links = self.driver.find_elements(By.CSS_SELECTOR, selector)
                            for link in links:
                                try:
                                    text = link.text.strip()
                                    if text.isdigit():
                                        page_num = int(text)
                                        if page_num > max_page:
                                            max_page = page_num
                                except:
                                    pass
                        except Exception:
                            continue
                    
                    if max_page > 1:
                        info['total_pages'] = max_page
                        info['has_pagination'] = True
                        logger.info(f"Found {max_page} pages from pagination links")
                        print(f"  Found {max_page} pages from pagination links")
            
            return info
            
        except Exception as e:
            logger.warning(f"Error getting pagination info: {e}")
            return info
    
    def click_next_page(self) -> bool:
        """
        Click the next page button in pagination.
        
        Returns:
            bool: True if successfully navigated to next page, False if button not found or disabled
        """
        try:
            # Find next page button/link
            next_selectors = [
                "//a[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'next')]",
                "//button[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'next')]",
                "a[aria-label*='next' i]",
                "button[aria-label*='next' i]",
                ".pagination .next",
                ".pagination a:last-child",
                "//a[contains(@class, 'next')]",
                "//button[contains(@class, 'next')]",
            ]
            
            next_btn = None
            for selector in next_selectors:
                try:
                    if selector.startswith("//"):
                        elements = self.driver.find_elements(By.XPATH, selector)
                    else:
                        elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    
                    for elem in elements:
                        if not elem.is_displayed():
                            continue
                        
                        # Check if disabled
                        disabled = (
                            elem.get_attribute('disabled') is not None or
                            'disabled' in (elem.get_attribute('class') or '').lower() or
                            'disabled' in (elem.get_attribute('aria-disabled') or '').lower() or
                            'disabled' in (elem.get_attribute('style') or '').lower()
                        )
                        
                        if not disabled:
                            next_btn = elem
                            logger.info(f"Found next page button with selector: {selector[:50]}")
                            break
                    if next_btn:
                        break
                except Exception:
                    continue
            
            if not next_btn:
                logger.debug("Next page button not found or all buttons are disabled")
                return False
            
            # Scroll into view and click
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", next_btn)
            time.sleep(0.5)
            
            try:
                self.driver.execute_script("arguments[0].click();", next_btn)
            except:
                try:
                    next_btn.click()
                except Exception as e:
                    logger.warning(f"Failed to click next button: {e}")
                    return False
            
            # Wait for page to load
            time.sleep(self.FILTER_WAIT_TIME)
            
            # Wait for table to update
            try:
                WebDriverWait(self.driver, self.ELEMENT_WAIT_TIMEOUT).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "table tbody tr"))
                )
            except TimeoutException:
                logger.warning("Timeout waiting for table after next page click")
            
            return True
            
        except Exception as e:
            logger.error(f"Error clicking next page: {e}")
            return False
    
    def get_page_html(self) -> str:
        """
        Get the current page HTML source.
        
        Returns:
            str: HTML source of the page
        """
        if self.driver:
            return self.driver.page_source
        return ""
    
    @staticmethod
    def _parse_date(date_str: str) -> Optional[datetime]:
        """
        Parse date string from floorsheet.
        
        Handles various date formats.
        
        Args:
            date_str: Date string from HTML.
            
        Returns:
            Parsed datetime or None if parsing fails.
        """
        date_str = date_str.strip()
        formats = [
            '%Y/%m/%d', '%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y',
            '%d-%m-%Y', '%Y.%m.%d', '%d.%m.%Y',
            '%B %d, %Y', '%b %d, %Y',  # "January 01, 2026"
        ]
        
        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue
        
        logger.warning(f"Could not parse date: {date_str}")
        return None
    
    @staticmethod
    def _parse_number(value: str) -> Optional[int]:
        """
        Parse integer from string, handling commas.
        
        Args:
            value: Number string possibly with commas.
            
        Returns:
            Parsed integer or None.
        """
        try:
            cleaned = value.strip().replace(',', '').replace(' ', '')
            return int(cleaned)
        except (ValueError, AttributeError):
            return None
    
    @staticmethod
    def _parse_decimal(value: str) -> Optional[Decimal]:
        """
        Parse decimal from string, handling commas.
        
        Args:
            value: Decimal string possibly with commas.
            
        Returns:
            Parsed Decimal or None.
        """
        try:
            cleaned = value.strip().replace(',', '').replace(' ', '')
            return Decimal(cleaned)
        except Exception:
            return None
    
    @classmethod
    def scrape_from_html(
        cls, 
        html_content: str
    ) -> Tuple[List[Dict], Dict]:
        """
        Parse floorsheet data from HTML content.
        
        Returns transactions with symbol information extracted from table.
        
        Args:
            html_content: Raw HTML string containing floorsheet data.
            
        Returns:
            Tuple of (list of dicts with transaction data including symbol, metadata dict)
            Each dict has: transaction, symbol (extracted from table)
        """
        soup = BeautifulSoup(html_content, 'html.parser')
        transactions = []
        metadata = {
            'total_rows_found': 0,
            'successfully_parsed': 0,
            'parse_errors': 0,
            'symbols_found': set(),
            'errors': []
        }
        
        # Find the floorsheet table
        # Try multiple table selectors
        table = None
        table_selectors = [
            'table',
            'table.table',
            'table.table-striped',
            'table.table-bordered',
            'table#floorsheetTable',
            'table.floorsheet-table',
        ]
        
        for selector in table_selectors:
            table = soup.select_one(selector)
            if table:
                logger.info(f"Found table with selector: {selector}")
                break
        
        if not table:
            logger.warning("No floorsheet table found in HTML")
            # Save HTML for debugging
            try:
                with open("debug_no_table_found.html", 'w', encoding='utf-8') as f:
                    f.write(html_content)
                logger.info("Saved HTML to debug_no_table_found.html for debugging")
            except:
                pass
            return transactions, metadata
        
        # Find all table rows (skip header row)
        rows = table.find_all('tr')
        logger.info(f"Found {len(rows)} rows in table")
        
        if len(rows) == 0:
            logger.warning("Table found but has no rows")
            return transactions, metadata
        
        # Try to identify header row to skip it and get column mapping
        header_row_idx = 0
        header_cells = []
        column_mapping = {}  # Map column names to indices
        
        for i, row in enumerate(rows[:3]):  # Check first 3 rows
            cells = row.find_all(['th', 'td'])
            cell_texts = [cell.get_text(strip=True).lower() for cell in cells]
            
            # Check if this looks like a header row
            header_keywords = ['contract', 'transaction', 'date', 'buyer', 'seller', 'quantity', 'rate', 'amount', 'symbol']
            if any(keyword in ' '.join(cell_texts) for keyword in header_keywords):
                header_row_idx = i
                header_cells = cell_texts
                # Map column names to indices
                for idx, text in enumerate(cell_texts):
                    text_lower = text.lower()
                    if 'symbol' in text_lower or 'stock' in text_lower:
                        column_mapping['symbol'] = idx
                    elif 'contract' in text_lower or ('transaction' in text_lower and 'no' in text_lower):
                        column_mapping['contract'] = idx
                    elif 'date' in text_lower:  # Removed requirement for 'transaction' - just look for 'date'
                        column_mapping['date'] = idx
                    elif 'buyer' in text_lower:
                        column_mapping['buyer'] = idx
                    elif 'seller' in text_lower:
                        column_mapping['seller'] = idx
                    elif 'quantity' in text_lower or 'qty' in text_lower:
                        column_mapping['quantity'] = idx
                    elif 'rate' in text_lower or 'price' in text_lower:
                        column_mapping['rate'] = idx
                    elif 'amount' in text_lower:
                        column_mapping['amount'] = idx
                
                logger.info(f"Column mapping from header: {column_mapping}")
                print(f"  Column mapping: {column_mapping}")
                break
        
        # Process data rows (skip header)
        for row in rows[header_row_idx + 1:]:
            cells = row.find_all('td')
            
            # Skip rows with insufficient columns
            if len(cells) < 6:
                continue
            
            metadata['total_rows_found'] += 1
            
            try:
                # Map columns - adjust indices based on actual table structure
                # Expected columns: Date, Contract Number (transaction_no), Buyer, Seller, Quantity, Rate, Amount
                # Or: Contract Number, Date, Buyer, Seller, Quantity, Rate, Amount
                
                cell_texts = [cell.get_text(strip=True) for cell in cells]
                
                # Use header mapping if available, otherwise identify by content
                if column_mapping:
                    # Use header-based mapping
                    symbol_idx = column_mapping.get('symbol')
                    contract_idx = column_mapping.get('contract')
                    date_idx = column_mapping.get('date')
                    buyer_idx = column_mapping.get('buyer')
                    seller_idx = column_mapping.get('seller')
                    qty_idx = column_mapping.get('quantity')
                    rate_idx = column_mapping.get('rate')
                    amount_idx = column_mapping.get('amount')
                else:
                    # Fallback: identify by content
                    symbol_idx = None
                    date_idx = None
                    contract_idx = None
                    buyer_idx = None
                    seller_idx = None
                    qty_idx = None
                    rate_idx = None
                    amount_idx = None
                    
                    # Find symbol column (typically short uppercase text, 2-10 chars)
                    for i, text in enumerate(cell_texts):
                        cleaned = text.strip().upper()
                        if (len(cleaned) >= 2 and len(cleaned) <= 10 and 
                            cleaned.isalnum() and cleaned.isupper()):
                            symbol_idx = i
                            break
                    
                    # Find contract number column (very long numeric, typically 16+ digits)
                    for i, text in enumerate(cell_texts):
                        cleaned = text.replace(',', '').replace(' ', '').replace('-', '')
                        if cleaned.isdigit() and len(cleaned) >= 14:  # Contract numbers are very long
                            contract_idx = i
                            break
                    
                    # Find date column - must be a valid date format (not a decimal number)
                    for i, text in enumerate(cell_texts):
                        # Skip if it looks like a decimal number (has comma and decimal point pattern)
                        if ',' in text and '.' in text:
                            # Check if it's a number pattern like "2,071.30"
                            cleaned = text.replace(',', '').replace(' ', '')
                            if cleaned.replace('.', '').isdigit():
                                continue  # This is a number, not a date
                        
                        # Check for date patterns: YYYY-MM-DD, MM/DD/YYYY, DD-MM-YYYY, etc.
                        if any(char in text for char in ['/', '-']):
                            # Must have date-like structure
                            parts = text.replace('/', '-').split('-')
                            if len(parts) == 3:
                                # Try to parse as date
                                parsed_date = cls._parse_date(text)
                                if parsed_date:
                                    date_idx = i
                                    break
                    
                    # Find buyer and seller (broker numbers, small integers, may be "-" or empty)
                    for i, text in enumerate(cell_texts):
                        if i in [symbol_idx, contract_idx, date_idx]:
                            continue
                        cleaned = text.replace(',', '').replace(' ', '').replace('-', '')
                        if cleaned.isdigit() and 1 <= int(cleaned) <= 100:  # Broker numbers 1-100
                            if buyer_idx is None:
                                buyer_idx = i
                            elif seller_idx is None and i != buyer_idx:
                                seller_idx = i
                                break
                    
                    # Find quantity, rate, amount (remaining numeric columns with decimals/commas)
                    # These are typically larger numbers
                    for i, text in enumerate(cell_texts):
                        if i in [symbol_idx, contract_idx, date_idx, buyer_idx, seller_idx]:
                            continue
                        cleaned = text.replace(',', '').replace(' ', '')
                        if cleaned.replace('.', '').isdigit() and len(cleaned) > 0:
                            # Determine which is which by value ranges
                            try:
                                num_val = float(cleaned)
                                if qty_idx is None and num_val > 0 and num_val < 1000000:  # Quantity is usually smaller
                                    qty_idx = i
                                elif rate_idx is None and '.' in text and 100 < num_val < 10000:  # Rate is usually 3-4 digits with decimal
                                    rate_idx = i
                                elif amount_idx is None:  # Amount is usually larger
                                    amount_idx = i
                            except:
                                pass
                    
                    # If still missing, assign in order
                    if qty_idx is None or rate_idx is None or amount_idx is None:
                        remaining_indices = [i for i in range(len(cell_texts)) 
                                            if i not in [symbol_idx, contract_idx, date_idx, buyer_idx, seller_idx]]
                        if qty_idx is None and len(remaining_indices) > 0:
                            qty_idx = remaining_indices[0]
                        if rate_idx is None and len(remaining_indices) > 1:
                            rate_idx = remaining_indices[1]
                        if amount_idx is None and len(remaining_indices) > 2:
                            amount_idx = remaining_indices[2]
                
                # Date will be set to today's date - no need to extract from contract or table
                # (This section removed since we always use today's date)
                
                # Validate we have all required columns (date will be set to today's date)
                required_cols = [contract_idx, buyer_idx, seller_idx, qty_idx, rate_idx, amount_idx]
                # Date is always valid (we use today's date)
                if None in required_cols:
                    metadata['parse_errors'] += 1
                    error_msg = f"Could not identify all columns in row. Found: contract={contract_idx}, buyer={buyer_idx}, seller={seller_idx}, qty={qty_idx}, rate={rate_idx}, amount={amount_idx}. Cell texts: {cell_texts[:10]}"
                    metadata['errors'].append(error_msg)
                    # Only log first few errors to avoid spam
                    if metadata['parse_errors'] <= 3:
                        logger.warning(error_msg)
                    continue
                
                # Extract symbol if available
                symbol = None
                if symbol_idx is not None:
                    symbol = cell_texts[symbol_idx].strip().upper()
                    if symbol:
                        metadata['symbols_found'].add(symbol)
                
                # Use today's date for all transactions (table doesn't have date column)
                trans_date = datetime.combine(date.today(), datetime.min.time())
                
                contract_str = cell_texts[contract_idx]
                buyer_str = cell_texts[buyer_idx]
                seller_str = cell_texts[seller_idx]
                qty_str = cell_texts[qty_idx]
                rate_str = cell_texts[rate_idx]
                amount_str = cell_texts[amount_idx]
                
                # Parse values (date is already set to today)
                transaction_no = cls._parse_number(contract_str)
                buyer_broker = cls._parse_number(buyer_str) if buyer_str and buyer_str.strip() != '-' else None
                seller_broker = cls._parse_number(seller_str) if seller_str and seller_str.strip() != '-' else None
                quantity = cls._parse_number(qty_str)
                rate = cls._parse_decimal(rate_str)
                amount = cls._parse_decimal(amount_str)
                
                # Debug first failed parse
                if metadata['parse_errors'] == 0 and not all([trans_date, transaction_no, buyer_broker is not None, 
                           seller_broker is not None, quantity, rate, amount]):
                    logger.warning(f"First parse failure - contract_str='{contract_str}', "
                                 f"buyer_str='{buyer_str}', seller_str='{seller_str}', "
                                 f"qty_str='{qty_str}', rate_str='{rate_str}', amount_str='{amount_str}'")
                    logger.warning(f"Parsed: trans_date={trans_date.date()}, transaction_no={transaction_no}, "
                                 f"buyer={buyer_broker}, seller={seller_broker}, qty={quantity}, rate={rate}, amount={amount}")
                
                # Validate required fields (date is always set to today, so we don't check it)
                if not all([transaction_no, buyer_broker is not None, 
                           seller_broker is not None, quantity, rate, amount]):
                    metadata['parse_errors'] += 1
                    if metadata['parse_errors'] <= 3:
                        metadata['errors'].append(f"Missing required field in row with contract: {contract_str}")
                    continue
                
                transaction = FloorsheetTransaction(
                    transaction_date=trans_date,
                    transaction_no=transaction_no,
                    buyer_broker=buyer_broker,
                    seller_broker=seller_broker,
                    quantity=quantity,
                    rate=rate,
                    amount=amount
                )
                
                # Store transaction with symbol
                transactions.append({
                    'transaction': transaction,
                    'symbol': symbol
                })
                metadata['successfully_parsed'] += 1
                
            except Exception as e:
                metadata['parse_errors'] += 1
                metadata['errors'].append(str(e))
                logger.warning(f"Error parsing row: {e}")
        
        # Keep symbols_found as set (will convert to list only at final return)
        # This allows it to be merged with other sets in scrape_from_url
        
        logger.info(
            f"Parsed {metadata['successfully_parsed']} transactions "
            f"({metadata['parse_errors']} errors, {len(metadata['symbols_found'])} symbols)"
        )
        
        return transactions, metadata
    
    def scrape_from_url(
        self, 
        save_to_db: bool = False
    ) -> Tuple[List[Dict], Dict]:
        """
        Scrape ALL floorsheet data from nepalstock.com using Selenium.
        
        This uses Selenium WebDriver to:
        1. Load the floorsheet page (no filters)
        2. Set items per page to 500
        3. Click the Filter button
        4. Parse all data from the table (all symbols)
        5. Save data to database grouped by symbol (if save_to_db=True)
        
        Args:
            save_to_db: If True, save transactions to database grouped by symbol (default: False)
        
        Returns:
            Tuple of (list of dicts with transaction and symbol, metadata dict)
        """
        print(f"\n{'='*60}")
        print(f"Starting scrape from nepalstock.com")
        print(f"Scraping ALL data (no symbol/date filters)")
        print(f"Browser mode: {'HEADLESS' if self.headless else 'VISIBLE (for debugging)'}")
        print(f"{'='*60}")
        
        metadata = {
            'total_rows_found': 0,
            'successfully_parsed': 0,
            'parse_errors': 0,
            'symbols_found': set(),
            'pages_scraped': 0,
            'errors': [],
            'scrape_method': 'selenium'
        }
        
        all_transactions = []
        
        try:
            # Load the page
            print(f"[1/4] Loading floorsheet page...")
            if not self.load_page():
                print(f"  ✗ Failed to load page")
                metadata['errors'].append("Failed to load floorsheet page")
                return [], metadata
            print(f"  ✓ Page loaded successfully")
            
            # Set items per page to 500
            print(f"[2/4] Setting items per page to 500...")
            if not self.set_items_per_page(500):
                print(f"  ✗ Failed to set items per page")
                metadata['errors'].append("Failed to set items per page")
                # Continue anyway - might still work
            else:
                print(f"  ✓ Items per page set to 500")
            
            # Click filter button
            print(f"[3/4] Clicking filter button...")
            if not self.click_filter_button():
                print(f"  ✗ Failed to click filter button")
                metadata['errors'].append("Failed to click filter button")
                return [], metadata
            print(f"  ✓ Filter button clicked")
            
            # Scrape data from table (all pages)
            print(f"[4/5] Scraping data from table...")
            
            # Get pagination info
            pagination_info = self.get_pagination_info()
            total_pages = pagination_info.get('total_pages', 1)
            has_pagination = pagination_info.get('has_pagination', False)
            
            if has_pagination:
                print(f"  Found pagination: {total_pages} pages")
            else:
                print(f"  No pagination detected (single page)")
            
            # Wait a bit more for table to fully load after filter
            time.sleep(1)
            
            # Check if table has data before scraping
            try:
                table_rows = self.driver.find_elements(By.XPATH, "//table//tbody/tr")
                print(f"  Found {len(table_rows)} rows in table")
                if len(table_rows) == 0:
                    # Try alternative selectors
                    table_rows = self.driver.find_elements(By.CSS_SELECTOR, "table tr")
                    print(f"  Found {len(table_rows)} total rows (including header)")
            except Exception as e:
                logger.warning(f"Could not count table rows: {e}")
            
            # Scrape first page
            html_content = self.get_page_html()
            transactions, parse_metadata = self.scrape_from_html(html_content)
            
            all_transactions = transactions
            metadata.update(parse_metadata)
            metadata['pages_scraped'] = 1
            
            print(f"  Page 1: {len(transactions)} transactions ✓")
            
            # Debug: if no transactions but we have rows, save HTML
            if len(transactions) == 0 and parse_metadata.get('total_rows_found', 0) > 0:
                print(f"  ⚠ Warning: Found {parse_metadata.get('total_rows_found')} rows but parsed 0 transactions")
                try:
                    with open("debug_parsing_issue.html", 'w', encoding='utf-8') as f:
                        f.write(html_content)
                    print(f"  Saved HTML to debug_parsing_issue.html for debugging")
                except:
                    pass
            
            # Scrape remaining pages by continuously clicking "Next" until it's disabled or missing
            # Don't rely on page count - keep going until we can't go further
            consecutive_empty_pages = 0
            max_consecutive_empty = 2  # Stop after 2 consecutive empty pages
            max_pages = 1000  # Safety limit to prevent infinite loops
            page_num = 2
            
            print(f"  Scraping all pages (will continue until no more pages)...")
            
            while page_num <= max_pages:
                # Check if next page button exists and is enabled
                next_button_exists = False
                try:
                    next_selectors = [
                        "//a[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'next')]",
                        "//button[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'next')]",
                        "a[aria-label*='next' i]",
                        "button[aria-label*='next' i]",
                        ".pagination .next",
                        ".pagination a:last-child",
                    ]
                    
                    for selector in next_selectors:
                        try:
                            if selector.startswith("//"):
                                elements = self.driver.find_elements(By.XPATH, selector)
                            else:
                                elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                            
                            for elem in elements:
                                if elem.is_displayed():
                                    # Check if disabled
                                    disabled = (
                                        'disabled' in (elem.get_attribute('class') or '').lower() or
                                        elem.get_attribute('disabled') is not None or
                                        'disabled' in (elem.get_attribute('aria-disabled') or '').lower()
                                    )
                                    if not disabled:
                                        next_button_exists = True
                                        break
                            if next_button_exists:
                                break
                        except Exception:
                            continue
                except Exception:
                    pass
                
                if not next_button_exists:
                    print(f"  No more pages (Next button not found or disabled)")
                    break
                
                print(f"  Page {page_num}: ", end="", flush=True)
                
                if self.click_next_page():
                    # Wait a bit for page to load
                    time.sleep(1)
                    
                    html_content = self.get_page_html()
                    page_transactions, page_metadata = self.scrape_from_html(html_content)
                    
                    if len(page_transactions) == 0:
                        consecutive_empty_pages += 1
                        if consecutive_empty_pages >= max_consecutive_empty:
                            print("✗ Too many empty pages, stopping")
                            break
                    else:
                        consecutive_empty_pages = 0
                    
                    # Add new transactions
                    all_transactions.extend(page_transactions)
                    metadata['pages_scraped'] += 1
                    metadata['total_rows_found'] += page_metadata.get('total_rows_found', 0)
                    metadata['successfully_parsed'] += page_metadata.get('successfully_parsed', 0)
                    metadata['parse_errors'] += page_metadata.get('parse_errors', 0)
                    
                    # Update symbols found - ensure we're working with sets
                    if 'symbols_found' in page_metadata:
                        page_symbols = page_metadata['symbols_found']
                        # Ensure metadata['symbols_found'] is a set
                        if not isinstance(metadata['symbols_found'], set):
                            metadata['symbols_found'] = set(metadata['symbols_found']) if metadata['symbols_found'] else set()
                        
                        # Convert page_symbols to set if needed, then update
                        if isinstance(page_symbols, set):
                            metadata['symbols_found'].update(page_symbols)
                        elif isinstance(page_symbols, list):
                            metadata['symbols_found'].update(set(page_symbols))
                        elif page_symbols:
                            metadata['symbols_found'].add(page_symbols)
                    
                    print(f"{len(page_transactions)} transactions ✓")
                    page_num += 1
                else:
                    print("✗ Failed to navigate to next page")
                    metadata['errors'].append(f"Failed to navigate to page {page_num}")
                    break
            
            metadata['successfully_parsed'] = len(all_transactions)
            print(f"  Total: {len(all_transactions)} transactions from {metadata['pages_scraped']} pages")
            # Convert symbols_found to list for display and JSON serialization
            symbols_list = list(metadata['symbols_found']) if isinstance(metadata['symbols_found'], set) else metadata['symbols_found']
            if symbols_list:
                print(f"  ✓ Found {len(symbols_list)} symbols: {', '.join(symbols_list[:10])}")
                if len(symbols_list) > 10:
                    print(f"    ... and {len(symbols_list) - 10} more")
            
            # Save to database if requested
            if save_to_db and all_transactions:
                print(f"[5/6] Saving to database...")
                # Import the save function from floorsheet_scraper
                from .floorsheet_scraper import save_floorsheet_to_db
                from collections import defaultdict
                
                # Group transactions by symbol
                transactions_by_symbol = defaultdict(list)
                for item in all_transactions:
                    symbol = item.get('symbol')
                    if symbol:
                        transactions_by_symbol[symbol].append(item['transaction'])
                    else:
                        # If no symbol found, skip this transaction
                        metadata['errors'].append(f"Transaction {item['transaction'].transaction_no} has no symbol")
                
                # Save each symbol's transactions
                total_saved = 0
                total_skipped = 0
                for symbol, symbol_transactions in transactions_by_symbol.items():
                    try:
                        save_stats = save_floorsheet_to_db(
                            symbol_transactions,
                            symbol.upper(),
                            skip_existing=True,
                            bulk_insert=True
                        )
                        total_saved += save_stats['created']
                        total_skipped += save_stats['skipped']
                        print(f"  ✓ {symbol}: {save_stats['created']} new, {save_stats['skipped']} skipped")
                    except Exception as e:
                        print(f"  ✗ {symbol}: Error saving - {e}")
                        metadata['errors'].append(f"Error saving {symbol}: {str(e)}")
                
                print(f"  ✓ Total saved: {total_saved} new, {total_skipped} skipped")
            
            # Convert symbols_found set to list for JSON serialization
            if isinstance(metadata.get('symbols_found'), set):
                metadata['symbols_found'] = list(metadata['symbols_found'])
            
            print(f"\n{'='*60}")
            print(f"Scrape complete: {len(all_transactions)} transactions")
            if metadata.get('symbols_found'):
                print(f"Symbols found: {len(metadata['symbols_found'])}")
            print(f"{'='*60}\n")
            
            logger.info(f"Successfully scraped {len(all_transactions)} transactions")
            return all_transactions, metadata
            
        except WebDriverException as e:
            print(f"  ✗ WebDriver error: {e}")
            metadata['errors'].append(f"WebDriver error: {str(e)}")
            logger.error(f"WebDriver error scraping floorsheet: {e}")
            # Convert symbols_found to list for JSON serialization
            if isinstance(metadata.get('symbols_found'), set):
                metadata['symbols_found'] = list(metadata['symbols_found'])
            return all_transactions, metadata
        except Exception as e:
            print(f"  ✗ Unexpected error: {e}")
            metadata['errors'].append(f"Unexpected error: {str(e)}")
            logger.error(f"Failed to fetch floorsheet: {e}")
            # Convert symbols_found to list for JSON serialization
            if isinstance(metadata.get('symbols_found'), set):
                metadata['symbols_found'] = list(metadata['symbols_found'])
            return all_transactions, metadata
