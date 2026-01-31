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

    def save_to_database(self, file_path, Stock, StockData):
        """
        Save CSV data to database.
        
        Args:
            file_path: Path to CSV file
            Stock: Stock model class
            StockData: StockData model class
        
        Raises:
            Exception: If saving to database fails
        """
        try:
            dataframe = pd.read_csv(file_path, on_bad_lines="skip")
            dataframe.columns = dataframe.columns.str.strip().str.lower()

            records_processed = 0
            for _, row in dataframe.iterrows():
                row = row.where(pd.notna(row), None)

                stock, created = Stock.objects.get_or_create(
                    symbol=row['symbol'],
                    security_id=row['security id'],
                    security_name=row['security name'],
                    defaults={
                        "fifty_two_weeks_high": row['fifty two week high'] or 0.0,
                        "fifty_two_weeks_low": row['fifty two week low'] or 0.0,
                    }
                )

                StockData.objects.update_or_create(
                    stock=stock,
                    date=row['business date'],
                    defaults={
                        "open_price": row['open price'] or 0.0,
                        "high_price": row['high price'] or 0.0,
                        "low_price": row['low price'] or 0.0,
                        "close_price": row['close price'] or 0.0,
                        "total_traded_quantity": row['total traded quantity'] or 0,
                        "total_traded_value": row['total traded value'] or 0.0,
                        "previous_day_close_price": row['previous day close price'] or 0.0,
                        "last_updated_price": row['last updated price'] or 0.0,
                        "total_trades": row['total trades'] or 0,
                        "average_traded_price": row['average traded price'] or 0.0,
                        "market_capitalization": (
                            None if pd.isna(row['market capitalization'])
                            else row['market capitalization']
                        ),
                    }
                )
                records_processed += 1

            logger.info(f"Processed {records_processed} records from {file_path}")
        except Exception as e:
            logger.error(f"Error while saving data to the database: {e}")
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
