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
    # initializing the webdriver to open chrome 
    def __init__(self):
        # creating temporary directory to store the csv file 
        self.temp_dir = tempfile.mkdtemp()
        chrome_options = webdriver.ChromeOptions()
        # making the temp_dir default download folder  
        prefs = {"download.default_directory": self.temp_dir}
        chrome_options.add_experimental_option("prefs", prefs)
        self.driver = webdriver.Chrome(options=chrome_options)

    # opening the nepal stock website 
    def load_page(self, url):
        try:
            self.driver.get(url)
            time.sleep(2)  # Wait for the page to load
            assert "Nepal Stock Exchange" in self.driver.title
        except AssertionError:
            raise Exception("The page title does not contain 'Nepal Stock Exchange'.")
        except Exception as e:
            raise Exception(f"An error occurred: {e}")

    # change the date function 
    def change_date(self, date):
        try:
            # get the date input field 
            date_input = self.driver.find_element(By.XPATH, "//input[@bsdatepicker='']")
            # get the filter button 
            filter_button = self.driver.find_element(By.CLASS_NAME, "box__filter--search")
            # clear the date input field
            date_input.clear()
            # change the date input field to incoming date 
            date_input.send_keys(date)
            # click the filter button 
            filter_button.click()
            time.sleep(3) #wait for 3 sec after changing button
        except Exception as e:
            raise Exception(f"Error while changing the date: {e}")

    # function to download the csv file 
    def download_CSV(self):
        try:
            # get the download csv button 
            download_link = self.driver.find_element(By.CLASS_NAME, "table__file")
            # click the download button 
            download_link.click()
          
        except Exception as e:
            print(f"Error clicking button: {e}")

    # function to check wheather the date has data or not 
    def check_content(self):
        try:
            # get the table body 
            tbody = self.driver.find_element(By.XPATH, "//tbody")
            # check if it has inner content or not 
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

    # function to loop on date and update datebase 
    def loop_through_dates(self,Stock,StockData,date_value):
        try:
        # start date 
            date_input = self.driver.find_element(By.XPATH, "//input[@bsdatepicker='']")
            start_date_str = date_input.get_attribute("value")
            start_date = datetime.strptime(start_date_str, "%m/%d/%Y")
             
        # Calculate the end date 
            end_date = start_date - relativedelta(days=date_value)

        # Loop through each date in the range
            current_date = start_date
           
            while current_date >= end_date:
                date = current_date.strftime("%m/%d/%Y")
                # change the date 
                self.change_date(date)
                # check whether the date has content or not 
                if self.check_content():
                    # if present then download the csv file 
                    self.download_CSV()
                    # wait for the download to complete 
                    if self.download_wait() >= 0:
                       
                        files = os.listdir(self.temp_dir)
                        # print(f"Files in temp directory: {files}")
                        if files:  # Ensure there are files before calling get_latest_file
                            download_file = self.get_latest_file()
                            # update the database with new value 
                            self.save_to_database(download_file,Stock, StockData)
                            # remove the csv file after updating the database 
                            os.remove(download_file)
                        else:
                            print("No files found in the temporary directory after download.")
                else:
                    print("No content available for the date.")

                current_date -= timedelta(days=1)
            self.close()
        except Exception as e:
            print(f"Error while looping: {e}")
            
    
    # function to save value to database 
    def save_to_database(self, file, Stock, StockData):
        try:
            # Read the CSV file
            df = pd.read_csv(file, on_bad_lines="skip")
        
            # Normalize column names to lowercase for consistent access
            df.columns = df.columns.str.strip().str.lower()

            for _, row in df.iterrows():
                # Replace NaN values with None for nullable fields
                row = row.where(pd.notna(row), None)
                
                # Get or create the Stock instance first
                stock, created = Stock.objects.get_or_create(
                    symbol=row['symbol'],  
                    security_id=row['security id'],  
                    security_name=row['security name'],  
                    defaults={
                        "fifty_two_weeks_high": row['fifty two week high'] or 0.0,  # Default value for non-nullable fields
                        "fifty_two_weeks_low": row['fifty two week low'] or 0.0,
                    }
                )
            
                # Now, create or update StockData associated with the Stock
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
                        "market_capitalization": row['market capitalization'],  # Already nullable in the model
                    }
                )
        except Exception as e:
            raise Exception(f"Error while saving data to the database: {e}")



    # close the webdriver after completion 
    def close(self):
        try:
            if self.driver:
                self.driver.quit()  # Use quit() instead of close() for safety
                self.driver = None
        except selenium.common.exceptions.InvalidSessionIdException:
            print("Session is already closed.")
