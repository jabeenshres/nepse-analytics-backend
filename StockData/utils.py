from selenium import webdriver
from selenium.webdriver.common.by import By
import time
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import os
import tempfile
import pandas as pd
import math


class NepalStockScraper:
    # initilize the selenium 
    def __init__(self):
        self.temp_dir = tempfile.mkdtemp() #create temp dir to save the downloaded csv file
        # chrome options 
        chrome_options = webdriver.ChromeOptions()
        prefs = {"download.default_directory": self.temp_dir}
        chrome_options.add_experimental_option("prefs", prefs)
        self.driver = webdriver.Chrome(options=chrome_options)

    # load the NepalStockExchange website 
    def load_page(self, url):
        try:
            self.driver.get(url)
            # wait for 2 time for website to load 
            time.sleep(2)
            assert "Nepal Stock Exchange" in self.driver.title
        except AssertionError:
            raise Exception("The page title does not contain 'Nepal Stock Exchange'.")
        except Exception as e:
            raise Exception(f"An error occurred: {e}")

    def change_date(self, date):
        try:
            # get the date element 
            date_input = self.driver.find_element(By.XPATH, "//input[@bsdatepicker='']")
            # get the filter button 
            filter_button = self.driver.find_element(By.CLASS_NAME, "box__filter--search")
            # clear the date element 
            date_input.clear()
            # set the date element with the given argument 
            date_input.send_keys(date)
            # click on the filter button 
            filter_button.click()
            # wait for time 3 
            time.sleep(3)
        except Exception as e:
            raise Exception(f"Error while changing the date: {e}")

    def download_CSV(self):
        try:
            # get the download button 
            download_link = self.driver.find_element(By.CLASS_NAME, "table__file")
            # click the download_link 
            download_link.click()
        except Exception as e:
            print(f"Error clicking download button: {e}")

    def check_content(self):
        try:
            # get the table body 
            tbody = self.driver.find_element(By.XPATH, "//tbody")
            # check if the table contain data or not 
            has_children = len(tbody.find_elements(By.XPATH, ".//*")) > 0
            return has_children
        except Exception as e:
            raise Exception(f"Error while checking content: {e}")

    def download_wait(self):
        seconds = 0
        while seconds < 60:
            time.sleep(1)
            # get file from the temp dir 
            files = os.listdir(self.temp_dir)
            # check if download completed or not 
            downloading = any(fname.endswith(('.crdownload', '.part', '.tmp')) for fname in files)
            if not downloading and files:
                return seconds
            seconds += 1
        return -1

    def get_latest_file(self):
        # get file form the temp dir 
        files = os.listdir(self.temp_dir)
        # get the file path 
        full_paths = [os.path.join(self.temp_dir, f) for f in files]
        # get the latest file 
        latest_file = max(full_paths, key=os.path.getmtime)
        return latest_file

    def loop_through_dates(self, Stock, StockData, date_value):
        try:
            # get the date element 
            date_input = self.driver.find_element(By.XPATH, "//input[@bsdatepicker='']")
            # set the start date with the initial date of the date element 
            start_date_str = date_input.get_attribute("value")
            # convert the date into appropriate format 
            start_date = datetime.strptime(start_date_str, "%m/%d/%Y")
            # set the end date with the with given arguement 
            end_date = start_date - relativedelta(days=int(date_value))
            current_date = start_date
            # loop through date 
            while current_date >= end_date:
                date = current_date.strftime("%m/%d/%Y")
                print(f"Processing data for date: {date}")
                try:
                    # change the date to current date 
                    self.change_date(date)
                    # check for content 
                    if self.check_content():
                        print("Content found. Attempting to download CSV.")
                        # download csv 
                        self.download_CSV()
                        # wait for csv to download 
                        if self.download_wait() >= 0:
                            files = os.listdir(self.temp_dir)
                            if files:
                                # get the latest file 
                                download_file = self.get_latest_file()
                                # save the file to db 
                                self.save_to_database(download_file, Stock, StockData)
                                # delete the file 
                                os.remove(download_file)
                            else:
                                print(f"No files found for date {date}.")
                    else:
                        print(f"No content available for date: {date}.")
                except Exception as e:
                    print(f"Error processing date {date}: {e}")
                # decrease the date     
                current_date -= timedelta(days=1)

            self.close()
        except Exception as e:
            print(f"Error while looping through dates: {e}")

    def save_to_database(self, file, Stock, StockData):
        try:
            # read the file 
            df = pd.read_csv(file, on_bad_lines="skip")
            # conver the header to lowercase 
            df.columns = df.columns.str.strip().str.lower()
            # loop through each row 
            for _, row in df.iterrows():
                row = row.where(pd.notna(row), None)
                # create new stock if not exist 
                stock, created = Stock.objects.get_or_create(
                    symbol=row['symbol'],
                    security_id=row['security id'],
                    security_name=row['security name'],
                    defaults={
                        "fifty_two_weeks_high": row['fifty two week high'] or 0.0,
                        "fifty_two_weeks_low": row['fifty two week low'] or 0.0,
                    }
                )
                # update stock values 
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
                        "market_capitalization": None if pd.isna(row['market capitalization']) else row['market capitalization'],
                    }
                )
        except Exception as e:
            raise Exception(f"Error while saving data to the database: {e}")

    def close(self):
        try:
            # close driver 
            if self.driver:
                self.driver.quit()
                self.driver = None
        except Exception as e:
            print(f"Error closing the driver: {e}")
