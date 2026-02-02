"""
Floorsheet data scraper for merolagani.com.

This module provides utilities to scrape floorsheet data from merolagani.com
for individual stock symbols. The floorsheet contains individual trade
transactions executed on the NEPSE floor.

Similar to utils.py NepalStockScraper, this uses Selenium for pages that
require JavaScript interaction (clicking the floorsheet tab).
"""
import logging
import time
from datetime import datetime
from decimal import Decimal
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    WebDriverException, 
    NoSuchElementException,
    TimeoutException
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


class MerolaganiFloorsheetScraper:
    """
    Scraper for floorsheet data from merolagani.com.
    
    Uses Selenium WebDriver for JavaScript-heavy pages (similar to NepalStockScraper).
    
    Usage:
        # Method 1: Scrape directly from website using Selenium
        scraper = MerolaganiFloorsheetScraper()
        transactions, metadata = scraper.scrape_from_url('MBJC')
        scraper.close()
        
        # Method 2: Parse from provided HTML content (no Selenium needed)
        transactions, metadata = MerolaganiFloorsheetScraper.scrape_from_html(html_content, 'MBJC')
    """
    
    BASE_URL = "https://merolagani.com/CompanyDetail.aspx"
    PAGE_LOAD_WAIT_TIME = 2  # Initial page load time
    TAB_CLICK_WAIT_TIME = 4  # Wait after clicking tab/button (floorsheet needs 3-4 secs)
    ELEMENT_WAIT_TIMEOUT = 10  # Max wait for elements to be clickable
    PAGINATION_WAIT_TIME = 1.5  # Wait after pagination navigation
    
    def __init__(self, headless: bool = True):
        """
        Initialize the scraper with Chrome WebDriver.
        
        Args:
            headless: Run browser in headless mode (default: True)
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
                chrome_options.add_argument("--headless=new")  # New headless mode
            
            # Essential options
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-gpu")
            
            # Window size - important for JavaScript rendering
            chrome_options.add_argument("--window-size=1920,1080")
            
            # Allow notifications (blocking them can interfere with page behavior)
            prefs = {
                "profile.default_content_setting_values.notifications": 1,  # Allow (we'll dismiss alerts)
                "profile.default_content_settings.popups": 0,
            }
            chrome_options.add_experimental_option("prefs", prefs)
            
            # Disable automation detection
            chrome_options.add_argument("--disable-blink-features=AutomationControlled")
            chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
            chrome_options.add_experimental_option("useAutomationExtension", False)
            
            # User agent
            chrome_options.add_argument(
                "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            
            self.driver = webdriver.Chrome(options=chrome_options)
            
            # Set shorter implicit wait (we use explicit waits where needed)
            self.driver.implicitly_wait(3)
            
            logger.info("Chrome WebDriver initialized for Merolagani scraper")
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
    
    def load_page(self, symbol: str) -> bool:
        """
        Load the company detail page for a stock symbol.
        
        Args:
            symbol: Stock symbol (e.g., 'MBJC')
            
        Returns:
            bool: True if page loaded successfully
        """
        self._init_driver()
        url = f"{self.BASE_URL}?symbol={symbol}"
        
        try:
            self.driver.get(url)
            
            # Wait for page to be loaded (combined wait)
            WebDriverWait(self.driver, 10).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
            
            # Quick verification - check if symbol appears on page
            time.sleep(self.PAGE_LOAD_WAIT_TIME)
            
            if symbol.upper() in self.driver.page_source:
                logger.info(f"Successfully loaded page for {symbol}")
                return True
            
            logger.warning(f"Page may not have loaded correctly for {symbol}")
            return False
                
        except Exception as e:
            logger.error(f"Error loading page for {symbol}: {e}")
            return False
    
    def click_floorsheet_tab(self) -> bool:
        """
        Click the Floorsheet tab to load floorsheet data.
        
        Tries multiple strategies to handle ASP.NET postback mechanism.
        
        Returns:
            bool: True if tab clicked successfully
        """
        strategies = [
            self._click_floorsheet_via_link,
            self._click_floorsheet_via_button,
            self._click_floorsheet_via_javascript,
            self._click_floorsheet_via_href,
        ]
        
        for i, strategy in enumerate(strategies, 1):
            try:
                logger.info(f"Trying floorsheet click strategy {i}/{len(strategies)}")
                if strategy():
                    logger.info(f"Successfully clicked floorsheet tab using strategy {i}")
                    return True
            except Exception as e:
                logger.warning(f"Strategy {i} failed: {e}")
                continue
        
        logger.error("All floorsheet click strategies failed")
        return False
    
    def _dismiss_alerts(self):
        """Accept/dismiss any browser alerts/popups."""
        try:
            alert = self.driver.switch_to.alert
            alert.accept()  # Accept (clicking OK) works better than dismiss
            logger.debug("Accepted browser alert")
        except Exception:
            pass  # No alert present
    
    def _click_floorsheet_via_link(self) -> bool:
        """Click the floorsheet link element directly."""
        try:
            floorsheet_tab = WebDriverWait(self.driver, 5).until(
                EC.element_to_be_clickable((By.ID, "ctl00_ContentPlaceHolder1_CompanyDetail1_lnkFloorsheetTab"))
            )
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", floorsheet_tab)
            time.sleep(0.3)
            
            # Use JS click to avoid interception issues
            self.driver.execute_script("arguments[0].click();", floorsheet_tab)
            
            # Wait briefly then handle any notification alert
            time.sleep(1)
            self._dismiss_alerts()
            
            # Wait for floorsheet to load
            time.sleep(self.TAB_CLICK_WAIT_TIME)
            
            return self._verify_floorsheet_loaded()
        except Exception as e:
            logger.debug(f"Link click failed: {e}")
            return False
    
    def _click_floorsheet_via_button(self) -> bool:
        """Click the hidden submit button that triggers postback."""
        try:
            btn = self.driver.find_element(
                By.ID, "ctl00_ContentPlaceHolder1_CompanyDetail1_btnFloorsheetTab"
            )
            self.driver.execute_script("arguments[0].click();", btn)
            time.sleep(self.TAB_CLICK_WAIT_TIME)
            return self._verify_floorsheet_loaded()
        except Exception as e:
            logger.debug(f"Button click failed: {e}")
            return False
    
    def _click_floorsheet_via_javascript(self) -> bool:
        """Execute JavaScript to trigger the floorsheet tab click."""
        try:
            # Use ASP.NET postback mechanism
            self.driver.execute_script(
                "__doPostBack('ctl00$ContentPlaceHolder1$CompanyDetail1$lnkFloorsheetTab','');"
            )
            time.sleep(self.TAB_CLICK_WAIT_TIME)
            return self._verify_floorsheet_loaded()
        except Exception as e:
            logger.debug(f"JavaScript click failed: {e}")
            return False
    
    def _click_floorsheet_via_href(self) -> bool:
        """Find the tab by href and click it."""
        try:
            # Find by href attribute
            floorsheet_tab = self.driver.find_element(
                By.CSS_SELECTOR, "a[href='#divFloorsheet']"
            )
            self.driver.execute_script("arguments[0].click();", floorsheet_tab)
            time.sleep(self.TAB_CLICK_WAIT_TIME)
            return self._verify_floorsheet_loaded()
        except Exception as e:
            logger.debug(f"Href click failed: {e}")
            return False
    
    def _verify_floorsheet_loaded(self) -> bool:
        """
        Verify that floorsheet data has loaded.
        
        Returns:
            bool: True if floorsheet table has data rows
        """
        try:
            self._dismiss_alerts()
            
            # Wait for actual data to appear (with short retry)
            for _ in range(3):
                try:
                    floorsheet_div = self.driver.find_element(By.ID, "divFloorsheet")
                    rows = floorsheet_div.find_elements(By.CSS_SELECTOR, "table tbody tr td")
                    
                    if rows and len(rows) > 0:
                        logger.info(f"Floorsheet loaded with data (found {len(rows)} cells)")
                        return True
                    
                    # Wait a bit and retry
                    time.sleep(0.5)
                except Exception:
                    time.sleep(0.5)
            
            # Final check
            floorsheet_div = self.driver.find_element(By.ID, "divFloorsheet")
            rows = floorsheet_div.find_elements(By.CSS_SELECTOR, "table tbody tr td")
            if rows and len(rows) > 0:
                logger.info(f"Floorsheet loaded with data (found {len(rows)} cells)")
                return True
            
            # Even if no data rows, check if the div is now visible
            if floorsheet_div.is_displayed():
                logger.info("Floorsheet div is displayed")
                return True
            
            return False
                    
        except Exception as e:
            logger.debug(f"Floorsheet verification failed: {e}")
            return False
    
    def set_date_filter(self, filter_date: str = None, date_to: str = None) -> bool:
        """
        Set date filter for floorsheet data.
        
        Note: Merolagani has a single date filter field.
        
        Args:
            filter_date: Date in MM/DD/YYYY format (e.g., "01/29/2026")
            date_to: Optional, ignored (kept for backwards compatibility)
            
        Returns:
            bool: True if filter applied successfully
        """
        try:
            # Wait for floorsheet div to be present
            floorsheet_div = WebDriverWait(self.driver, self.ELEMENT_WAIT_TIMEOUT).until(
                EC.presence_of_element_located((By.ID, "divFloorsheet"))
            )
            
            # Additional wait to ensure the form elements are loaded
            time.sleep(2)
            
            # Find the date filter input - Merolagani has a single date field
            # ID: ctl00_ContentPlaceHolder1_CompanyDetail1_txtFloorsheetDateFilter
            date_input = None
            
            try:
                date_input = floorsheet_div.find_element(
                    By.ID, "ctl00_ContentPlaceHolder1_CompanyDetail1_txtFloorsheetDateFilter"
                )
                logger.info("Found date filter input by ID")
            except NoSuchElementException:
                pass
            
            # Fallback: try by class
            if not date_input:
                try:
                    date_input = floorsheet_div.find_element(By.CSS_SELECTOR, "input.hasDatepicker")
                    logger.info("Found date filter input by hasDatepicker class")
                except NoSuchElementException:
                    pass
            
            # Fallback: try by placeholder
            if not date_input:
                try:
                    date_input = floorsheet_div.find_element(
                        By.CSS_SELECTOR, "input[placeholder='MM/DD/YYYY']"
                    )
                    logger.info("Found date filter input by placeholder")
                except NoSuchElementException:
                    pass
            
            if not date_input:
                logger.warning("Date filter input not found")
                return False
            
            if filter_date:
                try:
                    # Scroll into view first
                    self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", date_input)
                    time.sleep(0.5)
                    
                    # Wait for element to be visible and clickable
                    WebDriverWait(self.driver, 10).until(
                        EC.visibility_of(date_input)
                    )
                    
                    # Click to focus and dismiss any existing datepicker
                    date_input.click()
                    time.sleep(0.3)
                    
                    # Clear existing value
                    date_input.clear()
                    
                    # Set value using JavaScript (more reliable for datepicker fields)
                    self.driver.execute_script(
                        f"arguments[0].value = '{filter_date}';"
                        "arguments[0].dispatchEvent(new Event('change', { bubbles: true }));",
                        date_input
                    )
                    
                    # Also send keys for good measure
                    try:
                        from selenium.webdriver.common.keys import Keys
                        date_input.send_keys(Keys.ESCAPE)  # Close any datepicker popup
                    except Exception:
                        pass
                    
                    logger.info(f"Set date filter: {filter_date}")
                    
                except Exception as e:
                    logger.warning(f"Could not set date filter using standard method: {e}")
                    # Pure JavaScript fallback
                    try:
                        self.driver.execute_script(
                            f"document.getElementById('ctl00_ContentPlaceHolder1_CompanyDetail1_txtFloorsheetDateFilter').value = '{filter_date}';"
                        )
                        logger.info(f"Set date filter via JS fallback: {filter_date}")
                    except Exception as e2:
                        logger.warning(f"JS fallback also failed: {e2}")
            
            # Find and click the search/filter button
            search_btn = None
            
            # The floorsheet filter uses a specific button pattern
            button_selectors = [
                "#ctl00_ContentPlaceHolder1_CompanyDetail1_btnFloorsheetFilter",
                "input[id*='btnFloorsheetFilter']",
                "input[value*='Filter'][type='submit']",
                "input[value*='Search'][type='submit']",
                ".btn-primary[type='submit']",
                "#divFloorsheet .btn-primary",
            ]
            
            for selector in button_selectors:
                try:
                    search_btn = self.driver.find_element(By.CSS_SELECTOR, selector)
                    if search_btn and search_btn.is_displayed():
                        logger.info(f"Found search button with selector: {selector}")
                        break
                except NoSuchElementException:
                    continue
            
            # Fallback: find by value text
            if not search_btn:
                try:
                    buttons = floorsheet_div.find_elements(By.CSS_SELECTOR, "input[type='submit'], button")
                    for btn in buttons:
                        value = btn.get_attribute("value") or btn.text
                        if any(x in value.lower() for x in ["filter", "search", "find"]):
                            search_btn = btn
                            break
                except Exception:
                    pass
            
            if search_btn:
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", search_btn)
                time.sleep(0.5)
                
                try:
                    search_btn.click()
                except Exception:
                    # Fallback to JavaScript click
                    self.driver.execute_script("arguments[0].click();", search_btn)
                
                logger.info("Clicked filter button")
            else:
                logger.warning("Filter button not found, trying to submit via Enter key")
                try:
                    from selenium.webdriver.common.keys import Keys
                    date_input.send_keys(Keys.ENTER)
                except Exception:
                    pass
            
            # Wait for results to load (3-4 seconds as user reported)
            time.sleep(self.TAB_CLICK_WAIT_TIME)
            
            # Additional wait for table to update
            try:
                WebDriverWait(self.driver, 10).until(
                    lambda d: len(d.find_elements(By.CSS_SELECTOR, "#divFloorsheet table tbody tr")) > 0
                )
            except TimeoutException:
                logger.warning("Timeout waiting for filtered results")
            
            return True
            
        except Exception as e:
            logger.warning(f"Failed to set date filter: {e}")
            return False
    
    def get_pagination_info(self) -> Dict:
        """
        Get pagination information from the floorsheet table.
        
        Returns:
            Dict with total_records, total_pages, current_page
        """
        import re
        
        info = {
            'total_records': 0,
            'total_pages': 1,
            'current_page': 1,
            'has_pagination': False
        }
        
        try:
            # Wait for floorsheet div to be present
            floorsheet_div = WebDriverWait(self.driver, self.ELEMENT_WAIT_TIMEOUT).until(
                EC.presence_of_element_located((By.ID, "divFloorsheet"))
            )
            
            # Get the inner HTML for parsing
            page_source = floorsheet_div.get_attribute("innerHTML")
            
            # Pattern: "Showing X - Y of Z records"
            records_match = re.search(r'of\s+(\d+)\s+records', page_source, re.IGNORECASE)
            if records_match:
                info['total_records'] = int(records_match.group(1))
                info['has_pagination'] = info['total_records'] > 100
            
            # Pattern: "[Total pages: N]" or "Total pages: N"
            pages_match = re.search(r'Total\s*pages[:\s]*(\d+)', page_source, re.IGNORECASE)
            if pages_match:
                info['total_pages'] = int(pages_match.group(1))
                info['has_pagination'] = info['total_pages'] > 1
            
            # Also try to count pagination links to determine total pages
            pagination_links = floorsheet_div.find_elements(
                By.CSS_SELECTOR, "a[href*='Page'], a[href*='page'], .pagination a, ul.pagination li a"
            )
            
            max_page_num = 1
            for link in pagination_links:
                try:
                    link_text = link.text.strip()
                    if link_text.isdigit():
                        page_num = int(link_text)
                        if page_num > max_page_num:
                            max_page_num = page_num
                except (ValueError, AttributeError):
                    continue
            
            if max_page_num > info['total_pages']:
                info['total_pages'] = max_page_num
                info['has_pagination'] = True
            
            # Find current page from active pagination button or styling
            active_page_selectors = [
                ".pagination .active",
                ".pagination li.active a",
                "ul.pagination li.active a",
                ".pager .active",
                "a.active[href*='page']",
                "span.current-page",
                "a.btn-primary[href*='Page']",  # Sometimes active page has different class
            ]
            
            for selector in active_page_selectors:
                try:
                    active_page = floorsheet_div.find_elements(By.CSS_SELECTOR, selector)
                    if active_page:
                        text = active_page[0].text.strip()
                        if text.isdigit():
                            info['current_page'] = int(text)
                            break
                except Exception:
                    continue
            
            logger.info(f"Pagination info: {info}")
            return info
            
        except Exception as e:
            logger.warning(f"Failed to get pagination info: {e}")
            return info
    
    def click_next_page(self) -> bool:
        """
        Click the next page button in pagination.
        
        Merolagani uses changePageIndex() JavaScript function for pagination.
        
        Returns:
            bool: True if successfully navigated to next page
        """
        try:
            # Wait for floorsheet div
            floorsheet_div = WebDriverWait(self.driver, self.ELEMENT_WAIT_TIMEOUT).until(
                EC.presence_of_element_located((By.ID, "divFloorsheet"))
            )
            
            # Get current first cell text for verification
            current_rows = floorsheet_div.find_elements(By.CSS_SELECTOR, "table tbody tr td")
            first_cell_text = current_rows[0].text if current_rows else ""
            
            next_btn = None
            
            # Find the "Next" link which uses changePageIndex
            try:
                links = floorsheet_div.find_elements(By.TAG_NAME, "a")
                for link in links:
                    link_text = link.text.strip().lower()
                    onclick = link.get_attribute("onclick") or ""
                    
                    if link_text == "next" and "changePageIndex" in onclick:
                        next_btn = link
                        break
            except Exception:
                pass
            
            if next_btn:
                # Scroll into view
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", next_btn)
                time.sleep(0.5)
                
                # Check if clickable (not disabled)
                try:
                    classes = next_btn.get_attribute("class") or ""
                    parent_classes = ""
                    try:
                        parent = next_btn.find_element(By.XPATH, "..")
                        parent_classes = parent.get_attribute("class") or ""
                    except:
                        pass
                    
                    if "disabled" in classes.lower() or "disabled" in parent_classes.lower():
                        logger.info("Next button is disabled - no more pages")
                        return False
                except Exception:
                    pass
                
                # Get the onclick attribute and execute it directly via JavaScript
                onclick = next_btn.get_attribute("onclick")
                if onclick:
                    try:
                        self.driver.execute_script(onclick)
                        logger.info(f"Executed Next onclick: {onclick[:50]}...")
                    except Exception as e:
                        logger.debug(f"Direct onclick failed: {e}, trying click")
                        try:
                            next_btn.click()
                        except Exception:
                            self.driver.execute_script("arguments[0].click();", next_btn)
                else:
                    try:
                        next_btn.click()
                    except Exception:
                        self.driver.execute_script("arguments[0].click();", next_btn)
                
                # Wait for page to load
                time.sleep(self.PAGINATION_WAIT_TIME)
                
                # Quick check if content changed (short timeout - just verification)
                try:
                    WebDriverWait(self.driver, 2).until(
                        lambda d: self._page_content_changed(first_cell_text)
                    )
                except TimeoutException:
                    pass  # Content may have already changed
                
                logger.info("Clicked next page")
                return True
            
            logger.warning("Next page button not found")
            return False
            
        except Exception as e:
            logger.warning(f"Failed to click next page: {e}")
            return False
    
    def _page_content_changed(self, original_first_cell: str) -> bool:
        """Check if page content has changed by comparing first cell text."""
        try:
            floorsheet_div = self.driver.find_element(By.ID, "divFloorsheet")
            rows = floorsheet_div.find_elements(By.CSS_SELECTOR, "table tbody tr td")
            if rows:
                current_first = rows[0].text
                return current_first != original_first_cell
        except Exception:
            pass
        return True  # Assume changed if we can't verify
    
    def click_page_number(self, page_num: int) -> bool:
        """
        Click a specific page number in pagination.
        
        Merolagani uses changePageIndex(pageNum, hiddenInputId, buttonId) JavaScript function
        which sets a hidden input and clicks a submit button to trigger a form postback.
        
        Args:
            page_num: Page number to navigate to
            
        Returns:
            bool: True if successfully navigated
        """
        try:
            self._dismiss_alerts()
            
            # Get current first transaction number for verification
            first_txn = ""
            try:
                rows = self.driver.find_elements(By.CSS_SELECTOR, "#divFloorsheet table tbody tr")
                if len(rows) > 1:  # Skip header row
                    cells = rows[1].find_elements(By.TAG_NAME, "td")
                    if len(cells) > 2:
                        first_txn = cells[2].text  # Transaction number column
            except Exception:
                pass
            
            # Call changePageIndex with exact parameters (triggers form submit/page reload)
            js_cmd = f'''changePageIndex("{page_num}", 
                "ctl00_ContentPlaceHolder1_CompanyDetail1_PagerControlFloorsheet1_hdnCurrentPage", 
                "ctl00_ContentPlaceHolder1_CompanyDetail1_PagerControlFloorsheet1_btnPaging");'''
            
            try:
                self.driver.execute_script(js_cmd)
                logger.info(f"Called changePageIndex for page {page_num}")
                
                # Wait for form postback to complete (page reloads)
                # This needs to be longer than regular AJAX wait since it's a full form submit
                time.sleep(3)  # Postback/page reload time
                
                # Dismiss any alerts that appeared
                self._dismiss_alerts()
                
                # Verify content changed by checking transaction number
                new_first_txn = ""
                try:
                    rows = self.driver.find_elements(By.CSS_SELECTOR, "#divFloorsheet table tbody tr")
                    if len(rows) > 1:
                        cells = rows[1].find_elements(By.TAG_NAME, "td")
                        if len(cells) > 2:
                            new_first_txn = cells[2].text
                except Exception:
                    pass
                
                if new_first_txn and new_first_txn != first_txn:
                    logger.info(f"Successfully navigated to page {page_num}")
                    return True
                elif new_first_txn:
                    # Content exists - navigation likely succeeded
                    logger.info(f"Navigated to page {page_num}")
                    return True
                    
            except Exception as e:
                logger.debug(f"JS pagination failed: {e}")
            
            logger.warning(f"Page {page_num} navigation may have failed")
            return False
            
        except Exception as e:
            logger.warning(f"Failed to click page {page_num}: {e}")
            return False
    
    def scrape_all_pages(self, symbol: str) -> Tuple[List[FloorsheetTransaction], Dict]:
        """
        Scrape floorsheet data from all pages.
        
        Args:
            symbol: Stock symbol
            
        Returns:
            Tuple of (all transactions from all pages, metadata)
        """
        all_transactions = []
        seen_transaction_ids = set()  # Track unique transactions to avoid duplicates
        
        metadata = {
            'symbol': symbol,
            'pages_scraped': 0,
            'total_pages': 1,
            'total_rows_found': 0,
            'successfully_parsed': 0,
            'parse_errors': 0,
            'errors': []
        }
        
        # Wait a bit to ensure page is fully loaded
        time.sleep(1)
        
        # Get pagination info
        pagination = self.get_pagination_info()
        metadata['total_pages'] = pagination['total_pages']
        metadata['total_records_expected'] = pagination['total_records']
        
        print(f"  Pagination: {pagination['total_records']} records, {pagination['total_pages']} pages")
        logger.info(f"Pagination detected: {pagination}")
        
        # Scrape first page (already loaded)
        html_content = self.get_page_html()
        transactions, page_metadata = self.scrape_from_html(html_content, symbol)
        
        for t in transactions:
            if t.transaction_no not in seen_transaction_ids:
                all_transactions.append(t)
                seen_transaction_ids.add(t.transaction_no)
        
        metadata['pages_scraped'] = 1
        metadata['total_rows_found'] += page_metadata['total_rows_found']
        metadata['successfully_parsed'] += page_metadata['successfully_parsed']
        metadata['parse_errors'] += page_metadata['parse_errors']
        
        print(f"  Page 1: {len(transactions)} transactions ✓")
        logger.info(f"Page 1: Scraped {len(transactions)} transactions (unique: {len(all_transactions)})")
        
        # Scrape remaining pages
        if pagination['has_pagination'] and pagination['total_pages'] > 1:
            consecutive_failures = 0
            max_consecutive_failures = 3
            
            for page_num in range(2, pagination['total_pages'] + 1):
                print(f"  Page {page_num}: ", end="", flush=True)
                logger.info(f"Attempting to scrape page {page_num} of {pagination['total_pages']}")
                
                # Try to navigate to the page
                navigated = False
                
                # Strategy 1: Click the page number directly
                if self.click_page_number(page_num):
                    navigated = True
                    logger.info(f"Navigated to page {page_num} via page number")
                
                # Strategy 2: Use "Next" button
                if not navigated and self.click_next_page():
                    navigated = True
                    logger.info(f"Navigated to page {page_num} via Next button")
                
                # Strategy 3: Try JavaScript postback (ASP.NET specific)
                if not navigated:
                    try:
                        # ASP.NET pages often use __doPostBack for pagination
                        postback_commands = [
                            f"__doPostBack('ctl00$ContentPlaceHolder1$CompanyDetail1$gvFloorsheet','Page${page_num}');",
                            f"__doPostBack('ctl00_ContentPlaceHolder1_CompanyDetail1_gvFloorsheet','Page${page_num}');",
                        ]
                        for cmd in postback_commands:
                            try:
                                self.driver.execute_script(cmd)
                                time.sleep(self.PAGINATION_WAIT_TIME)
                                navigated = True
                                logger.info(f"Navigated to page {page_num} via JS postback")
                                break
                            except Exception:
                                continue
                    except Exception as e:
                        logger.debug(f"Postback navigation failed: {e}")
                
                if not navigated:
                    print("✗ navigation failed")
                    logger.warning(f"Could not navigate to page {page_num}")
                    consecutive_failures += 1
                    
                    if consecutive_failures >= max_consecutive_failures:
                        print(f"  Stopping: too many failures")
                        logger.error(f"Too many consecutive navigation failures, stopping at page {page_num - 1}")
                        break
                    continue
                
                # Reset failure counter on success
                consecutive_failures = 0
                
                # Wait for new content to load
                time.sleep(self.PAGINATION_WAIT_TIME)
                
                # Parse the new page
                html_content = self.get_page_html()
                transactions, page_metadata = self.scrape_from_html(html_content, symbol)
                
                if not transactions:
                    print("✗ no data")
                    logger.warning(f"No transactions found on page {page_num}")
                    consecutive_failures += 1
                    
                    if consecutive_failures >= max_consecutive_failures:
                        print(f"  Stopping: too many empty pages")
                        logger.error("Too many empty pages, stopping")
                        break
                    continue
                
                # Add unique transactions
                new_count = 0
                for t in transactions:
                    if t.transaction_no not in seen_transaction_ids:
                        all_transactions.append(t)
                        seen_transaction_ids.add(t.transaction_no)
                        new_count += 1
                
                metadata['pages_scraped'] += 1
                metadata['total_rows_found'] += page_metadata['total_rows_found']
                metadata['successfully_parsed'] += page_metadata['successfully_parsed']
                metadata['parse_errors'] += page_metadata['parse_errors']
                
                print(f"{len(transactions)} transactions ✓")
                logger.info(f"Page {page_num}: Scraped {len(transactions)} transactions ({new_count} new)")
                
                # If no new transactions were found, we might be stuck on the same page
                if new_count == 0:
                    logger.warning(f"Page {page_num} had no new transactions (possible duplicate page)")
                    consecutive_failures += 1
                    
                    if consecutive_failures >= max_consecutive_failures:
                        print(f"  Stopping: duplicate pages detected")
                        logger.error("Too many duplicate pages, stopping")
                        break
        
        print(f"  Total: {len(all_transactions)} unique transactions from {metadata['pages_scraped']} pages")
        logger.info(
            f"Completed scraping {metadata['pages_scraped']} pages, "
            f"total {len(all_transactions)} unique transactions"
        )
        
        return all_transactions, metadata
    
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
        
        Handles formats: YYYY/MM/DD, YYYY-MM-DD
        
        Args:
            date_str: Date string from HTML.
            
        Returns:
            Parsed datetime or None if parsing fails.
        """
        date_str = date_str.strip()
        formats = ['%Y/%m/%d', '%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y']
        
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
            # Remove commas and whitespace
            cleaned = value.strip().replace(',', '')
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
            # Remove commas and whitespace
            cleaned = value.strip().replace(',', '')
            return Decimal(cleaned)
        except Exception:
            return None
    
    @classmethod
    def scrape_from_html(
        cls, 
        html_content: str, 
        symbol: str
    ) -> Tuple[List[FloorsheetTransaction], Dict]:
        """
        Parse floorsheet data from HTML content.
        
        Args:
            html_content: Raw HTML string containing floorsheet data.
            symbol: Stock symbol for logging purposes.
            
        Returns:
            Tuple of (list of FloorsheetTransaction objects, metadata dict)
        """
        soup = BeautifulSoup(html_content, 'html.parser')
        transactions = []
        metadata = {
            'symbol': symbol,
            'total_rows_found': 0,
            'successfully_parsed': 0,
            'parse_errors': 0,
            'errors': []
        }
        
        # Find the floorsheet table
        # The floorsheet is in a div with id="divFloorsheet"
        floorsheet_div = soup.find('div', id='divFloorsheet')
        
        if not floorsheet_div:
            # Try to find it differently - might be in the whole page
            floorsheet_div = soup
            logger.info("divFloorsheet not found, searching entire HTML")
        
        # Find all table rows within the floorsheet section
        # Skip header rows - data rows have td elements with specific classes
        all_rows = floorsheet_div.find_all('tr')
        
        for row in all_rows:
            cells = row.find_all('td')
            
            # Skip rows that don't have the expected number of columns
            # Expected: #, Date, Transaction No, Buyer, Seller, Qty, Rate, Amount (8 columns)
            if len(cells) < 7:
                continue
            
            metadata['total_rows_found'] += 1
            
            try:
                # Parse each cell
                # Cell 0: Row number (skip)
                # Cell 1: Date (or Cell 0 if no row number column)
                
                # Determine the starting index based on whether first column is a row number
                first_cell_text = cells[0].get_text(strip=True)
                
                if first_cell_text.isdigit() and len(cells) >= 8:
                    # Has row number column
                    date_idx = 1
                else:
                    # No row number column
                    date_idx = 0
                
                # Parse fields
                date_str = cells[date_idx].get_text(strip=True)
                transaction_no_str = cells[date_idx + 1].get_text(strip=True)
                buyer_str = cells[date_idx + 2].get_text(strip=True)
                seller_str = cells[date_idx + 3].get_text(strip=True)
                qty_str = cells[date_idx + 4].get_text(strip=True)
                rate_str = cells[date_idx + 5].get_text(strip=True)
                amount_str = cells[date_idx + 6].get_text(strip=True)
                
                # Parse values
                trans_date = cls._parse_date(date_str)
                transaction_no = cls._parse_number(transaction_no_str)
                buyer_broker = cls._parse_number(buyer_str)
                seller_broker = cls._parse_number(seller_str)
                quantity = cls._parse_number(qty_str)
                rate = cls._parse_decimal(rate_str)
                amount = cls._parse_decimal(amount_str)
                
                # Validate required fields
                if not all([trans_date, transaction_no, buyer_broker is not None, 
                           seller_broker is not None, quantity, rate, amount]):
                    metadata['parse_errors'] += 1
                    metadata['errors'].append(f"Missing required field in row with transaction: {transaction_no_str}")
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
                transactions.append(transaction)
                metadata['successfully_parsed'] += 1
                
            except Exception as e:
                metadata['parse_errors'] += 1
                metadata['errors'].append(str(e))
                logger.warning(f"Error parsing row: {e}")
        
        logger.info(
            f"Parsed {metadata['successfully_parsed']} transactions for {symbol} "
            f"({metadata['parse_errors']} errors)"
        )
        
        return transactions, metadata
    
    def scrape_multiple_symbols(
        self,
        symbols: List[str],
        date_from: str = None,
        date_to: str = None,
        scrape_all_pages: bool = True,
        skip_existing_dates: bool = True,
        save_to_db: bool = True
    ) -> Dict:
        """
        Scrape floorsheet data for multiple symbols.
        
        Args:
            symbols: List of stock symbols (e.g., ['MBJC', 'NABIL', 'NICA'])
            date_from: Start date in MM/DD/YYYY format
            date_to: End date in MM/DD/YYYY format
            scrape_all_pages: If True, scrape all pagination pages
            skip_existing_dates: If True, skip dates already in DB
            save_to_db: If True, save transactions to database
            
        Returns:
            Dict with results for each symbol
        """
        print(f"\n{'='*60}")
        print(f"Scraping {len(symbols)} symbols")
        print(f"Symbols: {', '.join(symbols)}")
        print(f"Date range: {date_from} to {date_to}")
        print(f"{'='*60}")
        
        results = {
            'total_symbols': len(symbols),
            'successful': 0,
            'failed': 0,
            'total_transactions': 0,
            'symbols': {}
        }
        
        for i, symbol in enumerate(symbols, 1):
            print(f"\n[{i}/{len(symbols)}] Processing {symbol}...")
            
            try:
                transactions, metadata = self.scrape_from_url(
                    symbol=symbol.upper(),
                    date_from=date_from,
                    date_to=date_to,
                    scrape_all_pages=scrape_all_pages,
                    skip_existing_dates=skip_existing_dates
                )
                
                # Save to database if requested
                save_stats = None
                if save_to_db and transactions:
                    save_stats = save_floorsheet_to_db(transactions, symbol.upper())
                
                results['symbols'][symbol.upper()] = {
                    'success': True,
                    'transactions_count': len(transactions),
                    'metadata': metadata,
                    'save_stats': save_stats
                }
                results['successful'] += 1
                results['total_transactions'] += len(transactions)
                
            except Exception as e:
                print(f"  ✗ Error: {e}")
                results['symbols'][symbol.upper()] = {
                    'success': False,
                    'error': str(e)
                }
                results['failed'] += 1
        
        print(f"\n{'='*60}")
        print(f"Completed: {results['successful']}/{len(symbols)} symbols successful")
        print(f"Total transactions: {results['total_transactions']}")
        print(f"{'='*60}\n")
        
        return results
    
    def scrape_from_url(
        self, 
        symbol: str,
        date_from: str = None,
        date_to: str = None,
        scrape_all_pages: bool = True,
        skip_existing_dates: bool = True
    ) -> Tuple[List[FloorsheetTransaction], Dict]:
        """
        Scrape floorsheet data from merolagani.com for a given symbol using Selenium.
        
        This uses Selenium WebDriver to:
        1. Load the company detail page
        2. Click the Floorsheet tab
        3. Loop through each date in the range and scrape using the website's date filter
        4. Skip dates that already have data in database (if skip_existing_dates=True)
        5. Parse all pages of data for each date
        
        Args:
            symbol: Stock symbol (e.g., 'MBJC', 'AKJCL')
            date_from: Start date in MM/DD/YYYY format (e.g., "01/29/2026")
            date_to: End date in MM/DD/YYYY format (e.g., "02/01/2026")
            scrape_all_pages: If True, scrape all pagination pages (default: True)
            skip_existing_dates: If True, skip dates that already have data in DB (default: True)
            
        Returns:
            Tuple of (list of FloorsheetTransaction objects, metadata dict)
        """
        url = f"{self.BASE_URL}?symbol={symbol}"
        
        print(f"\n{'='*60}")
        print(f"Starting scrape for {symbol}")
        print(f"Date range: {date_from} to {date_to}")
        print(f"{'='*60}")
        
        metadata = {
            'symbol': symbol,
            'url': url,
            'date_from': date_from,
            'date_to': date_to,
            'total_rows_found': 0,
            'successfully_parsed': 0,
            'parse_errors': 0,
            'pages_scraped': 0,
            'dates_scraped': 0,
            'dates_skipped': 0,
            'errors': [],
            'scrape_method': 'selenium'
        }
        
        all_transactions = []
        seen_transaction_ids = set()
        
        # Get existing dates from database if skip_existing_dates is enabled
        existing_dates = set()
        if skip_existing_dates and date_from and date_to:
            existing_dates = self._get_existing_dates_from_db(symbol)
            if existing_dates:
                print(f"  Found {len(existing_dates)} dates already in database")
        
        try:
            # Load the page
            print(f"[1/3] Loading page for {symbol}...")
            if not self.load_page(symbol):
                print(f"  ✗ Failed to load page")
                metadata['errors'].append(f"Failed to load page for {symbol}")
                return [], metadata
            print(f"  ✓ Page loaded successfully")
            
            # Click the floorsheet tab
            print(f"[2/3] Clicking floorsheet tab...")
            if not self.click_floorsheet_tab():
                print(f"  ✗ Failed to click floorsheet tab")
                metadata['errors'].append("Failed to click floorsheet tab")
                return [], metadata
            print(f"  ✓ Floorsheet tab clicked")
            
            # [3/3] Scrape data - loop through dates if range provided
            print(f"[3/3] Scraping floorsheet data...")
            
            if date_from and date_to:
                # Loop through each date in the range
                dates_to_scrape = self._get_dates_in_range(date_from, date_to)
                print(f"  Date range: {len(dates_to_scrape)} dates ({date_from} to {date_to})")
                
                for i, date_str in enumerate(dates_to_scrape, 1):
                    # Convert date to check against existing dates (YYYY-MM-DD format)
                    try:
                        date_obj = datetime.strptime(date_str, '%m/%d/%Y')
                        date_key = date_obj.strftime('%Y-%m-%d')
                    except ValueError:
                        date_key = date_str
                    
                    # Skip if date already exists in database
                    if skip_existing_dates and date_key in existing_dates:
                        print(f"  Date {i}/{len(dates_to_scrape)}: {date_str} - SKIPPED (already in DB)")
                        metadata['dates_skipped'] += 1
                        continue
                    
                    print(f"\n  Date {i}/{len(dates_to_scrape)}: {date_str}")
                    
                    # Set the date filter
                    if self.set_date_filter(date_str):
                        # Scrape all pages for this date
                        if scrape_all_pages:
                            transactions, scrape_meta = self.scrape_all_pages(symbol)
                        else:
                            html_content = self.get_page_html()
                            transactions, scrape_meta = self.scrape_from_html(html_content, symbol)
                        
                        # Add unique transactions only
                        new_count = 0
                        for t in transactions:
                            if t.transaction_no not in seen_transaction_ids:
                                all_transactions.append(t)
                                seen_transaction_ids.add(t.transaction_no)
                                new_count += 1
                        
                        print(f"    Found {len(transactions)} transactions ({new_count} new)")
                        metadata['pages_scraped'] += scrape_meta.get('pages_scraped', 1)
                        metadata['total_rows_found'] += scrape_meta.get('total_rows_found', 0)
                        metadata['dates_scraped'] += 1
                    else:
                        print(f"    ✗ Failed to set date filter")
                        metadata['errors'].append(f"Failed to set filter for {date_str}")
                    
                    # Reload the floorsheet tab for next date
                    if i < len(dates_to_scrape):
                        self.click_floorsheet_tab()
            else:
                # No date range - scrape whatever is currently displayed
                if scrape_all_pages:
                    transactions, scrape_metadata = self.scrape_all_pages(symbol)
                    metadata.update(scrape_metadata)
                else:
                    html_content = self.get_page_html()
                    transactions, parse_metadata = self.scrape_from_html(html_content, symbol)
                    metadata.update(parse_metadata)
                    metadata['pages_scraped'] = 1
                
                for t in transactions:
                    if t.transaction_no not in seen_transaction_ids:
                        all_transactions.append(t)
                        seen_transaction_ids.add(t.transaction_no)
            
            metadata['successfully_parsed'] = len(all_transactions)
            metadata['scrape_method'] = 'selenium'
            
            print(f"\n{'='*60}")
            print(f"Scrape complete: {len(all_transactions)} new transactions")
            print(f"Dates: {metadata['dates_scraped']} scraped, {metadata['dates_skipped']} skipped")
            print(f"{'='*60}\n")
            
            logger.info(f"Successfully scraped {len(all_transactions)} transactions for {symbol}")
            return all_transactions, metadata
            
        except WebDriverException as e:
            print(f"  ✗ WebDriver error: {e}")
            metadata['errors'].append(f"WebDriver error: {str(e)}")
            logger.error(f"WebDriver error scraping floorsheet for {symbol}: {e}")
            return all_transactions, metadata
        except Exception as e:
            print(f"  ✗ Unexpected error: {e}")
            metadata['errors'].append(f"Unexpected error: {str(e)}")
            logger.error(f"Failed to fetch floorsheet for {symbol}: {e}")
            return all_transactions, metadata
    
    def _get_existing_dates_from_db(self, symbol: str) -> set:
        """
        Get set of dates that already have floorsheet data in the database.
        
        Args:
            symbol: Stock symbol
            
        Returns:
            Set of date strings in YYYY-MM-DD format
        """
        try:
            from .models import Stock, FloorsheetData
            
            stock = Stock.objects.get(symbol=symbol.upper())
            existing_dates = FloorsheetData.objects.filter(stock=stock).values_list(
                'transaction_date', flat=True
            ).distinct()
            
            return {d.strftime('%Y-%m-%d') for d in existing_dates}
        except Exception as e:
            logger.warning(f"Could not get existing dates from DB: {e}")
            return set()
    
    def _get_dates_in_range(self, date_from: str, date_to: str) -> List[str]:
        """
        Generate list of dates between date_from and date_to (inclusive).
        
        Args:
            date_from: Start date in MM/DD/YYYY format
            date_to: End date in MM/DD/YYYY format
            
        Returns:
            List of date strings in MM/DD/YYYY format
        """
        from datetime import timedelta
        
        dates = []
        try:
            start = datetime.strptime(date_from, '%m/%d/%Y')
            end = datetime.strptime(date_to, '%m/%d/%Y')
            
            current = start
            while current <= end:
                dates.append(current.strftime('%m/%d/%Y'))
                current += timedelta(days=1)
        except ValueError as e:
            logger.warning(f"Error parsing dates: {e}")
            # Return just the end date as fallback
            if date_to:
                dates.append(date_to)
        
        return dates
    
    def _filter_by_date_range(
        self, 
        transactions: List[FloorsheetTransaction],
        date_from: str = None,
        date_to: str = None
    ) -> List[FloorsheetTransaction]:
        """
        Filter transactions by date range.
        
        Args:
            transactions: List of transactions to filter
            date_from: Start date in MM/DD/YYYY format
            date_to: End date in MM/DD/YYYY format
            
        Returns:
            Filtered list of transactions
        """
        if not date_from and not date_to:
            return transactions
        
        filtered = []
        
        # Parse date strings to datetime objects
        from_date = None
        to_date = None
        
        if date_from:
            try:
                from_date = datetime.strptime(date_from, '%m/%d/%Y').date()
            except ValueError:
                logger.warning(f"Invalid date_from format: {date_from}")
        
        if date_to:
            try:
                to_date = datetime.strptime(date_to, '%m/%d/%Y').date()
            except ValueError:
                logger.warning(f"Invalid date_to format: {date_to}")
        
        for trans in transactions:
            trans_date = trans.transaction_date.date() if hasattr(trans.transaction_date, 'date') else trans.transaction_date
            
            # Check if within range
            if from_date and trans_date < from_date:
                continue
            if to_date and trans_date > to_date:
                continue
            
            filtered.append(trans)
        
        return filtered


def parse_floorsheet_html(html_content: str, symbol: str = 'UNKNOWN') -> List[Dict]:
    """
    Convenience function to parse floorsheet HTML and return dictionaries.
    
    Args:
        html_content: Raw HTML string
        symbol: Stock symbol
        
    Returns:
        List of dictionaries with transaction data
    """
    # Use classmethod directly - no need to instantiate
    transactions, metadata = MerolaganiFloorsheetScraper.scrape_from_html(html_content, symbol)
    
    return [
        {
            'transaction_date': t.transaction_date.date(),
            'transaction_no': t.transaction_no,
            'buyer_broker': t.buyer_broker,
            'seller_broker': t.seller_broker,
            'quantity': t.quantity,
            'rate': float(t.rate),
            'amount': float(t.amount),
        }
        for t in transactions
    ]


def save_floorsheet_to_db(
    transactions: List[FloorsheetTransaction],
    stock_symbol: str,
    skip_existing: bool = True
) -> Dict:
    """
    Save scraped floorsheet transactions to the database.
    
    Args:
        transactions: List of FloorsheetTransaction objects
        stock_symbol: Stock symbol to link transactions to
        skip_existing: If True, skip transactions that already exist (default: True)
        
    Returns:
        Dict with save statistics
    """
    from .models import Stock, FloorsheetData
    
    stats = {
        'symbol': stock_symbol,
        'total': len(transactions),
        'created': 0,
        'skipped': 0,
        'updated': 0,
        'errors': 0,
        'error_messages': []
    }
    
    try:
        stock = Stock.objects.get(symbol=stock_symbol)
    except Stock.DoesNotExist:
        stats['errors'] = len(transactions)
        stats['error_messages'].append(f"Stock with symbol '{stock_symbol}' not found")
        return stats
    
    # Get existing transaction numbers for this stock to skip duplicates
    if skip_existing:
        existing_txn_nos = set(
            FloorsheetData.objects.filter(stock=stock)
            .values_list('transaction_no', flat=True)
        )
        print(f"  Found {len(existing_txn_nos)} existing transactions in DB")
    else:
        existing_txn_nos = set()
    
    for trans in transactions:
        try:
            # Skip if transaction already exists
            if skip_existing and trans.transaction_no in existing_txn_nos:
                stats['skipped'] += 1
                continue
            
            # Create new record (or update if not skipping)
            if skip_existing:
                # Just create, we already checked it doesn't exist
                FloorsheetData.objects.create(
                    stock=stock,
                    transaction_no=trans.transaction_no,
                    transaction_date=trans.transaction_date.date(),
                    buyer_broker=trans.buyer_broker,
                    seller_broker=trans.seller_broker,
                    quantity=trans.quantity,
                    rate=trans.rate,
                    amount=trans.amount,
                )
                stats['created'] += 1
            else:
                # Update or create
                floorsheet, created = FloorsheetData.objects.update_or_create(
                    stock=stock,
                    transaction_no=trans.transaction_no,
                    defaults={
                        'transaction_date': trans.transaction_date.date(),
                        'buyer_broker': trans.buyer_broker,
                        'seller_broker': trans.seller_broker,
                        'quantity': trans.quantity,
                        'rate': trans.rate,
                        'amount': trans.amount,
                    }
                )
                if created:
                    stats['created'] += 1
                else:
                    stats['updated'] += 1
                
        except Exception as e:
            stats['errors'] += 1
            stats['error_messages'].append(f"Transaction {trans.transaction_no}: {str(e)}")
            logger.error(f"Failed to save transaction {trans.transaction_no}: {e}")
    
    print(f"  Saved: {stats['created']} new, {stats['skipped']} skipped, {stats['errors']} errors")
    logger.info(
        f"Saved floorsheet for {stock_symbol}: "
        f"{stats['created']} created, {stats['skipped']} skipped, {stats['errors']} errors"
    )
    
    return stats
    
    return stats
