from selenium import webdriver
from selenium.webdriver.common.by import By
import time
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import os
import tempfile
import shutil
import pandas as pd
from RawData.models import RawDatapp

class NepalStockScraper:
    def __init__(self):
        # create a temporary directory
        self.temp_dir=tempfile.mkdtemp()
        # chrome option to set the download path to download_folder 
        chrome_options = webdriver.ChromeOptions()
        prefs = {"download.default_directory": self.temp_dir}
        chrome_options.add_experimental_option("prefs", prefs)
        # chrome driver 
        self.driver = webdriver.Chrome(options=chrome_options)


    # function to load page 
    def load_page(self, url):
        try:
            self.driver.get(url)
            time.sleep(2)  # Wait for the page to load
            assert "Nepal Stock Exchange" in self.driver.title  
        except AssertionError:
            print("The page title does not contain 'Nepal Stock Exchange'.")
        except Exception as e:
            print(f"An error occurred: {e}")

      # function to change the date 
    def change_date(self,date):
        try:
            date_input = self.driver.find_element(By.XPATH, "//input[@bsdatepicker='']")
            filter_button=self.driver.find_element(By.CLASS_NAME, "box__filter--search")
            date_input.clear()
            date_input.send_keys(date)
            filter_button.click()
            time.sleep(3)


        except Exception as e:
            print(f"Error while changing the date:{e}")
        

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



    # function to check if a particular date has data or not 
    def check_content(self):
        try:
            tbody = self.driver.find_element(By.XPATH, "//tbody")
            has_children = len(tbody.find_elements(By.XPATH, ".//*")) > 0
            if has_children:
                return True
            else:
                return False
        except Exception as e:
            print(f"Error while checking the inner content:{e}")



      # checks if download has completed or not 
    def download_wait(self):
        seconds = 0
        while seconds < 60:
            time.sleep(1)
            files = os.listdir(self.temp_dir)
            # Check if any file is still being downloaded (by checking for temp extensions)
            downloading = any(fname.endswith(('.crdownload', '.part', '.tmp')) for fname in files)
        
            if not downloading:
                return seconds  #  downloads completed

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
    

    # function to loop on dates 
    def loop_through_dates(self):
        try:
            # Define the start date
            start_date = datetime(2024, 3, 1)

            # Calculate the end date 
            end_date = start_date + relativedelta(day=20)

            # Loop through each date in the range
            current_date = start_date
            while current_date <= end_date:
                date=current_date.strftime("%m/%d/%Y")
                print(date)
                self.change_date(date)
                if(self.check_content()):
                    self.download_CSV()
                    if(self.download_wait()>=0):
                        print("download has completed!!!")
                        download_file=self.get_latest_file()
                        self.save_to_database(download_file)
                        os.remove(download_file)



                current_date += timedelta(days=1)
        except Exception as e:
            print(f"Error while looping:{e}")
 
    

    def save_to_database(self,file):
        df =pd.read_csv(file,on_bad_lines="skip")
        for _,row in df.iterrows():
            RawData.objects.update_or_create(
                date=row['BUSINESS_Date'],
                symbol=row['SYMBOL'],
                defaults={
                    "close_price":row["CLOSE_PRICE"],
                    "open_price":row["OPEN_PRICE"],
                    "high_price":row["HIGH_PRICE"],
                    "low_price":row["LOW_PRICE"],
                    "total_traded_quantity":row["TOTAL_TRADED_QUANTITY"],
                    "total_taded_value":row["TOTAL_TRADED_VALUE"],
                    "total_trades":row["TOTAL_TRADES"],
                    "ltp":row["LAST_UPDATED_PRICE"],
                    "previous_day_close_price":row["PREVIOUS_DAY_CLOSE_PRICE"],
                    "average_traded_price ":row["AVERAGE_TRADED_PRICE"],
                    "fifty_two_week_high":row["FIFTY_TWO_WEEKS_HIGH"],
                    "fifty_two_week_low ":row["FIFTY_TWO_WEEKS_LOW"],
                    "market_capitalization":row["MARKET_CAPITALIZATION"],
                    
                }

            ) 

  

   


    def close(self):
        self.driver.close()
        shutil.rmtree(self.tempdir) 

# Usage
scraper = NepalStockScraper()
scraper.load_page("https://www.nepalstock.com/today-price")
scraper.loop_through_dates()
scraper.close()