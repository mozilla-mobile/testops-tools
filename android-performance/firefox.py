import unittest
import time
import pandas as pd
from appium import webdriver
from appium.options.gecko import GeckoOptions

from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By


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

appium_server_url = "http://127.0.0.1:4723"


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
        # Load the existing CSV file
        results_df = pd.read_csv("page_load_times.csv")

        # Extract URLs from the DataFrame
        websites = results_df["website"].tolist()

        firefox_results = []

        for site in websites:
            # since we are reading from the already created csv from the chrome.py tests,
            # we don't need to add the https:// prefix
            # site = f"https://{site}"  # Ensure the URL is complete
            start_time = time.time()

            try:
                self.driver.get(site)
                # Wait for page to load or timeout after 20 seconds
                self.wait.until(
                    lambda d: d.execute_script("return document.readyState")
                    == "complete"
                )
                page_load_time = time.time() - start_time
            except:
                page_load_time = (
                    20  # Set to max time if page doesn't load in 20 seconds
                )
                print(f"Error loading {site}")

            firefox_results.append(page_load_time)

        # Update the DataFrame with Firefox results
        results_df["firefox"] = firefox_results

        # Save updated results to CSV
        results_df.to_csv("page_load_times.csv", index=False)

        for site, load_time in zip(websites, firefox_results):
            print(f"Page load time for {site} (Firefox): {load_time:.2f} seconds")


if __name__ == "__main__":
    unittest.main()
