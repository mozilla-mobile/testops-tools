import unittest
import pandas as pd
from appium import webdriver
from appium.options.android import UiAutomator2Options
from appium.webdriver.common.appiumby import AppiumBy
import time
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By

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

    @unittest.skip("Skip this test")
    def test_find_battery(self) -> None:
        el = self.driver.find_element(
            by=AppiumBy.XPATH, value='//*[@text="Connections"]'
        )
        el.click()

    def test_open_chrome(self) -> None:
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
            except:
                page_load_time = (
                    20  # Set to max time if page doesn't load in 20 seconds
                )
                print(f"Error loading {site}")

            results.append((site, page_load_time))

        # Create a DataFrame to store results
        results_df = pd.DataFrame(results, columns=["website", "google_chrome"])
        results_df["firefox"] = None  # Add a column for Firefox results

        # Save results to CSV
        results_df.to_csv("page_load_times.csv", index=False)

        for site, load_time in results:
            print(f"Page load time for {site}: {load_time:.2f} seconds")


if __name__ == "__main__":
    unittest.main()
