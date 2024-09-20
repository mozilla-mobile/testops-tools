import unittest
import time
import pandas as pd
from appium import webdriver
from appium.options.gecko import GeckoOptions
import argparse
import os
from datetime import datetime
from selenium.webdriver.support.ui import WebDriverWait
import sys

firefox_options = GeckoOptions()
firefox_options.set_capability("platformName", "mac")
firefox_options.set_capability("automationName", "Gecko")
firefox_options.set_capability("deviceName", "Android")
firefox_options.set_capability("browserName", "firefox")

moz_firefox_options = {
    "androidPackage": "org.mozilla.firefox",
    # "androidActivity": ".GeckoViewActivity",
    # "env": {"MOZ_LOG": "nsHttp:5", "MOZ_LOG_FILE": "/mnt/sdcard/log"},
}
firefox_options.set_capability("moz:firefoxOptions", moz_firefox_options)

appium_server_url = "http://localhost:4723"


# Parse command-line arguments
parser = argparse.ArgumentParser(description="Run Firefox tests with network type.")
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


class TestFirefoxAppium(unittest.TestCase):
    def setUp(self) -> None:
        self.driver = webdriver.Remote(
            appium_server_url,
            options=firefox_options,
        )
        self.wait = WebDriverWait(
            self.driver, 20
        )  # Set maximum wait time to 20 seconds

    def tearDown(self) -> None:
        if self.driver:
            self.driver.quit()

    def test_top_100_websites(self) -> None:
        # Define the directory to save the results
        results_dir = "./results"
        os.makedirs(results_dir, exist_ok=True)

        # Construct the output CSV file name with path
        csv_filename = os.path.join(
            results_dir, f"{network_type}_Page_Load_Times_{timestamp}.csv"
        )

        # Load the existing CSV file
        results_df = pd.read_csv(csv_filename)

        # Extract URLs from the DataFrame
        websites = results_df["website"].tolist()

        firefox_results = []

        for site in websites:
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
                page_load_time = 20  # Set to max time if page doesn't load
                print(f"Error loading {site}: {e}")

            firefox_results.append(page_load_time)

        # Update the DataFrame with Firefox results
        results_df["firefox"] = firefox_results

        # Save updated results to CSV
        results_df.to_csv(csv_filename, index=False)

        for site, load_time in zip(websites, firefox_results):
            print(f"Page load time for {site} (Firefox): {load_time:.2f} seconds")


if __name__ == "__main__":
    # Prevent unittest from processing argparse arguments
    unittest.main(argv=[sys.argv[0]] + unknown)
