from selenium import webdriver
from selenium.webdriver.common.by import By
import time
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import os
import tempfile
import shutil
import pandas as pd
import math


class NepalStockScraper:
    def __init__(self):
        self.temp_dir = tempfile.mkdtemp()
        chrome_options = webdriver.ChromeOptions()
        prefs = {"download.default_directory": self.temp_dir}
        chrome_options.add_experimental_option("prefs", prefs)
        self.driver = webdriver.Chrome(options=chrome_options)

    def load_page(self, url):
        try:
            self.driver.get(url)
            time.sleep(2)  # Wait for the page to load
            assert "Nepal Stock Exchange" in self.driver.title
        except AssertionError:
            raise Exception("The page title does not contain 'Nepal Stock Exchange'.")
        except Exception as e:
            raise Exception(f"An error occurred: {e}")

    def change_date(self, date):
        try:
            date_input = self.driver.find_element(By.XPATH, "//input[@bsdatepicker='']")
            filter_button = self.driver.find_element(By.CLASS_NAME, "box__filter--search")
            date_input.clear()
            date_input.send_keys(date)
            filter_button.click()
            time.sleep(3)
        except Exception as e:
            raise Exception(f"Error while changing the date: {e}")

    # function to download the csv file 
    def download_CSV(self):
        try:
            download_link = self.driver.find_element(By.CLASS_NAME, "table__file")
           # Click the download link
            download_link.click()
            # Wait for download
            # time.sleep(5)
        except Exception as e:
            print(f"Error clicking button: {e}")


    def check_content(self):
        try:
            tbody = self.driver.find_element(By.XPATH, "//tbody")
            has_children = len(tbody.find_elements(By.XPATH, ".//*")) > 0
            return has_children
        except Exception as e:
            raise Exception(f"Error while checking the inner content: {e}")

    # checks if download has completed or not 
    def download_wait(self):
        seconds = 0
        while seconds < 60:
            time.sleep(1)
            files = os.listdir(self.temp_dir)
            downloading = any(fname.endswith(('.crdownload', '.part', '.tmp')) for fname in files)

            if not downloading and files:
                return seconds  # Downloads completed and at least one file exists

            seconds += 1

        return -1  # Return -1 if the timeout occurred


     # get the latest file from the folder 
    def get_latest_file(self):
        # Get list of all files in the directory
        files = os.listdir(self.temp_dir)
    
        # Get the full paths of the files
        full_paths = [os.path.join(self.temp_dir, f) for f in files]
    
        # Filter only files (ignore directories) and get the latest one by modification time
        latest_file = max(full_paths, key=os.path.getmtime)
    
        return latest_file

    # def loop_through_dates(self, StockData,date_value):
    #     try:
            
    #         start_date = datetime.now().date()
    #         end_date = start_date - relativedelta(days=date_value)
    #         current_date = start_date
    #         while current_date >= end_date:
    #             date = current_date.strftime("%m/%d/%Y")
    #             self.change_date(date)
    #             if self.check_content():
    #                 self.download_CSV()
    #                 if self.download_wait() >= 0:
    #                     download_file = self.get_latest_file()
    #                     self.save_to_database(download_file, StockData)
    #                     os.remove(download_file)
    #             current_date -= timedelta(days=1)
    #     except Exception as e:
    #         raise Exception(f"Error while looping through dates: {e}")
    def loop_through_dates(self,Stock,StockData,date_value):
        try:
        # Define the start date
            date_input = self.driver.find_element(By.XPATH, "//input[@bsdatepicker='']")
            start_date_str = date_input.get_attribute("value")
            start_date = datetime.strptime(start_date_str, "%m/%d/%Y")
             
        # Calculate the end date 
            end_date = start_date - relativedelta(days=date_value)

        # Loop through each date in the range
            current_date = start_date
            print("looping")
            while current_date >= end_date:
                date = current_date.strftime("%m/%d/%Y")
                print(date)
                self.change_date(date)
                if self.check_content():
                    self.download_CSV()
                    if self.download_wait() >= 0:
                        print("Download has completed!!!")
                        files = os.listdir(self.temp_dir)
                        print(f"Files in temp directory: {files}")
                        if files:  # Ensure there are files before calling get_latest_file
                            download_file = self.get_latest_file()
                            self.save_to_database(download_file,Stock, StockData)
                            os.remove(download_file)
                        else:
                            print("No files found in the temporary directory after download.")
                else:
                    print("No content available for the date.")

                current_date -= timedelta(days=1)
        except Exception as e:
            print(f"Error while looping: {e}")

    def save_to_database(self, file, Stock, StockData):
        try:
            df = pd.read_csv(file, on_bad_lines="skip")
        
            for _, row in df.iterrows():
                # Get or create the Stock instance first
                stock, created = Stock.objects.get_or_create(
                    symbol = row['SYMBOL'],
                    security_id = row["SECURITY_ID"],
                    security_name = row["SECURITY_NAME"],
                    defaults={
                        "fifty_two_weeks_high": row["FIFTY_TWO_WEEKS_HIGH"],
                        "fifty_two_weeks_low": row["FIFTY_TWO_WEEKS_LOW"]
                    }
                )
            
                # Now, create or update StockData associated with the Stock
                StockData.objects.update_or_create(
                    stock=stock,  # ForeignKey to Stock
                    date=row['BUSINESS_DATE'],
                    defaults={
                        "open_price": row["OPEN_PRICE"],
                        "high_price": row["HIGH_PRICE"],
                        "low_price": row["LOW_PRICE"],
                        "close_price": row["CLOSE_PRICE"],
                        "total_traded_quantity": row["TOTAL_TRADED_QUANTITY"],
                        "total_traded_value": row["TOTAL_TRADED_VALUE"],
                        "previous_day_close_price": row["PREVIOUS_DAY_CLOSE_PRICE"],
                        "last_updated_price": row["LAST_UPDATED_PRICE"], 
                        "total_trades": row["TOTAL_TRADES"],
                        "average_traded_price": row["AVERAGE_TRADED_PRICE"],
                        "market_capitalization": None if math.isnan(row["MARKET_CAPITALIZATION"]) else row["MARKET_CAPITALIZATION"],
                    }
                )
        except Exception as e:
            raise Exception(f"Error while saving data to the database: {e}")


    def close(self):
        self.driver.close()
        shutil.rmtree(self.temp_dir)
