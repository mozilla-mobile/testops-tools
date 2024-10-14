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
import json
from selenium.common.exceptions import TimeoutException, WebDriverException

# Set up Firefox options and capabilities
firefox_options = GeckoOptions()
firefox_options.set_capability("platformName", "mac")
firefox_options.set_capability("automationName", "Gecko")
firefox_options.set_capability("deviceName", "Android")
firefox_options.set_capability("browserName", "firefox")

moz_firefox_options = {
    "androidPackage": "org.mozilla.firefox",
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

    def test_open_firefox(self) -> None:
        # Load the CSV file with top 100 websites
        df = pd.read_csv(
            "android-performance/data/top_1000_websites.csv",
            usecols=[1],
            nrows=10,
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

                # Capture performance metrics using JavaScript
                performance_data = self.driver.execute_script(
                    """
                    var timing = window.performance.timing || {};
                    var navigation = window.performance.getEntriesByType('navigation')[0] || {};
                    var resources = window.performance.getEntriesByType('resource') || [];

                    // Clean entries to avoid cross-origin issues
                    function cleanEntry(entry) {
                        return {
                            name: entry.name,
                            entryType: entry.entryType,
                            startTime: entry.startTime,
                            duration: entry.duration,
                            initiatorType: entry.initiatorType,
                            nextHopProtocol: entry.nextHopProtocol,
                            workerStart: entry.workerStart,
                            redirectStart: entry.redirectStart,
                            redirectEnd: entry.redirectEnd,
                            fetchStart: entry.fetchStart,
                            domainLookupStart: entry.domainLookupStart,
                            domainLookupEnd: entry.domainLookupEnd,
                            connectStart: entry.connectStart,
                            connectEnd: entry.connectEnd,
                            secureConnectionStart: entry.secureConnectionStart,
                            requestStart: entry.requestStart,
                            responseStart: entry.responseStart,
                            responseEnd: entry.responseEnd,
                            transferSize: entry.transferSize,
                            encodedBodySize: entry.encodedBodySize,
                            decodedBodySize: entry.decodedBodySize,
                            serverTiming: entry.serverTiming
                        };
                    }

                    // Clean navigation and resource entries
                    var cleanedNavigation = cleanEntry(navigation);
                    var cleanedResources = resources.map(cleanEntry);

                    // Collect paint timings
                    var paintEntries = performance.getEntriesByType('paint');
                    var firstPaint = null;
                    var firstContentfulPaint = null;
                    for (var i = 0; i < paintEntries.length; i++) {
                        if (paintEntries[i].name === 'first-paint') {
                            firstPaint = paintEntries[i].startTime;
                        } else if (paintEntries[i].name === 'first-contentful-paint') {
                            firstContentfulPaint = paintEntries[i].startTime;
                        }
                    }

                    // Collect long tasks (if available)
                    var longTasks = performance.getEntriesByType('longtask') || [];

                    var data = {
                        navigation: cleanedNavigation,
                        timing: timing,
                        resources: cleanedResources,
                        firstPaint: firstPaint,
                        firstContentfulPaint: firstContentfulPaint,
                        longTasks: longTasks
                    };

                    return data;
                """
                )

                # Save events to a JSON file in Firefox-specific directory
                events_dir = "./android-performance/data/firefox/events"
                os.makedirs(events_dir, exist_ok=True)
                safe_site_name = site.replace("https://", "").replace("/", "_")
                events_filename = os.path.join(
                    events_dir, f"{network_type}_{safe_site_name}_{timestamp}.json"
                )
                with open(events_filename, "w") as f:
                    json.dump(performance_data, f, indent=4)

                status = "SUCCESS"

            except TimeoutException as e:
                page_load_time = 20  # Max time
                status = "TIMEOUT"
                print(f"Timeout loading {site}: {e}")
                performance_data = None

            except WebDriverException as e:
                if "SSL" in str(e).lower() or "certificate" in str(e).lower():
                    status = "SSL_ERROR"
                else:
                    status = "WEBDRIVER_ERROR"
                page_load_time = 20
                print(f"WebDriverException loading {site}: {e}")
                performance_data = None

            except Exception as e:
                status = "OTHER_ERROR"
                page_load_time = 20
                print(f"Error loading {site}: {e}")
                performance_data = None

            # Save an error JSON file if there was an error
            if performance_data is None:
                events_dir = "./android-performance/results/firefox/events"
                os.makedirs(events_dir, exist_ok=True)
                safe_site_name = site.replace("https://", "").replace("/", "_")
                events_filename = os.path.join(
                    events_dir,
                    f"{network_type}_{safe_site_name}_{timestamp}_error.json",
                )
                error_data = {"status": status}
                with open(events_filename, "w") as f:
                    json.dump(error_data, f, indent=4)

            results.append((site, page_load_time, status))

        # Create a DataFrame to store results
        results_df = pd.DataFrame(
            results, columns=["website", "page_load_time", "status"]
        )

        # Store Test CSV Artifacts in ./firefox/results
        results_dir = "./android-performance/results/firefox/results"
        os.makedirs(results_dir, exist_ok=True)

        # Construct the output CSV file name with path
        csv_filename = os.path.join(
            results_dir, f"{network_type}_Page_Load_Times_{timestamp}.csv"
        )

        # Save results to CSV
        results_df.to_csv(csv_filename, index=False)

        for site, load_time, status in results:
            print(
                f"Page load time for {site} (Firefox): {load_time:.2f} seconds (Status: {status})"
            )


if __name__ == "__main__":
    # Prevent unittest from processing argparse arguments
    unittest.main(argv=[sys.argv[0]] + unknown)
