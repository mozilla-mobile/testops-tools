import unittest
import pandas as pd
from appium import webdriver
from appium.options.android import UiAutomator2Options
from appium.webdriver.common.appiumby import AppiumBy
import time
import argparse
import os
import sys  # Import sys to access sys.argv
from datetime import datetime
from selenium.webdriver.support.ui import WebDriverWait

CHROMEDRIVER_PATH = "/Users/jackiejohnson/Desktop/chromedriver-mac-arm64/chromedriver"

capabilities = dict(
    platformName="Android",
    automationName="uiautomator2",
    deviceName="Android",
    browserName="Chrome",
    language="en",
    locale="US",
    # chromedriver_autodownload=True,
    chromedriverExecutable=CHROMEDRIVER_PATH,
)

appium_server_url = "http://localhost:4723"

# 1. Parse command-line arguments before defining the test class
parser = argparse.ArgumentParser(description="Run Chrome tests with network type.")
parser.add_argument(
    "--network",
    type=str,
    default="Unknown",
    help="Network type (e.g., 2G, 3G, 4G, 5G)",
)
parser.add_argument(
    "--timestamp", type=str, required=True, help="Timestamp of the CSV file"
)
args, unknown = parser.parse_known_args()

network_type = args.network
timestamp = args.timestamp


class TestAppium(unittest.TestCase):
    def setUp(self) -> None:
        self.driver = webdriver.Remote(
            appium_server_url,
            options=UiAutomator2Options().load_capabilities(capabilities),
        )
        self.wait = WebDriverWait(
            self.driver, 20
        )  # Set maximum wait time to 20 seconds

    def tearDown(self) -> None:
        if self.driver:
            self.driver.quit()

    def test_open_chrome(self) -> None:
        # Now network_type is available here
        # Load the CSV file
        df = pd.read_csv(
            "android-performance/top_1000_websites.csv",
            usecols=[1],
            nrows=100,
            header=None,
            names=["URL"],
        )

        # Extract URLs from the DataFrame
        websites = df["URL"].tolist()

        results = []

        for site in websites:
            site = f"https://{site}"  # Prepend 'https://' to the URL
            start_time = time.time()

            try:
                self.driver.get(site)
                # Wait for page to load or timeout after 20 seconds
                self.wait.until(
                    lambda d: d.execute_script("return document.readyState")
                    == "complete"
                )
                page_load_time = time.time() - start_time
            except Exception as e:
                page_load_time = (
                    20  # Set to max time if page doesn't load in 20 seconds
                )
                print(f"Error loading {site}: {e}")

            results.append((site, page_load_time))

        # Create a DataFrame to store results
        results_df = pd.DataFrame(results, columns=["website", "google_chrome"])
        results_df["firefox"] = None  # Add a column for Firefox results

        # Store Test CSV Artifacts in ./results for CI
        results_dir = "./results"
        os.makedirs(results_dir, exist_ok=True)  # Corrected os.makedirs

        # Construct the output CSV file name with path
        csv_filename = os.path.join(
            results_dir, f"{network_type}_Page_Load_Times_{timestamp}.csv"
        )

        # Save results to CSV
        results_df.to_csv(csv_filename, index=False)

        for site, load_time in results:
            print(f"Page load time for {site}: {load_time:.2f} seconds")


if __name__ == "__main__":
    # 2. Modify unittest.main() to prevent it from processing custom arguments
    unittest.main(argv=[sys.argv[0]] + unknown)
