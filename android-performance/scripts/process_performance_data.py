import os
import json
import pandas as pd
import argparse
from datetime import datetime  # 1. Import datetime module

# Parse command-line arguments
parser = argparse.ArgumentParser(description="Process performance data for a browser.")
parser.add_argument(
    "--browser",
    type=str,
    required=True,
    choices=["chrome", "firefox"],
    help="Browser type (chrome or firefox)",
)
args = parser.parse_args()

browser = args.browser.lower()
events_dir = f"./android-performance/data/{browser}/events"
results_dir = f"./android-performance/data/{browser}/results"
graphs_dir = f"./android-performance/data/{browser}/graphs"

os.makedirs(results_dir, exist_ok=True)
os.makedirs(graphs_dir, exist_ok=True)

network_results = []
dom_results = []
page_load_results = []
master_results = []

# 2. Capture the current date in YYYY-MM-DD format
current_date = datetime.now().strftime("%Y-%m-%d")

for filename in os.listdir(events_dir):
    if filename.endswith(".json"):
        filepath = os.path.join(events_dir, filename)
        with open(filepath, "r") as f:
            data = json.load(f)

        # Extract site name from filename or data
        base_filename = os.path.splitext(filename)[0]
        parts = base_filename.split("_")
        if len(parts) >= 3:
            site = "_".join(parts[1:-1])
        else:
            site = base_filename

        # Check if data contains 'status' indicating an error
        if "status" in data:
            # This is an error file
            status = data["status"]
            # Set all metrics to None
            network_result = {
                "website": site,
                "dns_lookup_time_ms": None,
                "tcp_handshake_time_ms": None,
                "ssl_time_ms": None,
                "ttfb_ms": None,
                "content_download_time_ms": None,
                "total_network_time_ms": None,
                "browser": browser.capitalize(),
                "status": status,
                "measurement_date": current_date,  # 3. Add measurement_date
            }
            dom_result = {
                "website": site,
                "adjusted_dom_parsing_time_ms": None,
                "adjusted_rendering_time_ms": None,
                "adjusted_browser_processing_time_ms": None,
                "browser": browser.capitalize(),
                "status": status,
                "measurement_date": current_date,  # 3. Add measurement_date
            }
            page_load_result = {
                "website": site,
                "total_page_load_time_ms": None,
                "first_paint_ms": None,
                "first_contentful_paint_ms": None,
                "average_resource_processing_time_ms": None,
                "total_transfer_size_bytes": None,
                "browser": browser.capitalize(),
                "status": status,
                "measurement_date": current_date,  # 3. Add measurement_date
            }
            master_result = {**network_result, **dom_result, **page_load_result}
            master_results.append(master_result)
            network_results.append(network_result)
            dom_results.append(dom_result)
            page_load_results.append(page_load_result)
            continue

        # Proceed to process performance data as before
        navigation = data.get("navigation", {})
        timing = data.get("timing", {})
        resources = data.get("resources", [])
        first_paint = data.get("firstPaint")
        first_contentful_paint = data.get("firstContentfulPaint")

        # Network Metrics
        required_nav_keys = [
            "startTime",
            "domainLookupStart",
            "domainLookupEnd",
            "connectStart",
            "connectEnd",
            "secureConnectionStart",
            "requestStart",
            "responseStart",
            "responseEnd",
        ]
        if all(key in navigation for key in required_nav_keys):
            # Network Metrics
            dns_lookup_time = (
                navigation["domainLookupEnd"] - navigation["domainLookupStart"]
            )
            tcp_handshake_time = navigation["connectEnd"] - navigation["connectStart"]
            ssl_time = (
                navigation["connectEnd"] - navigation["secureConnectionStart"]
                if navigation["secureConnectionStart"] > 0
                else 0
            )
            ttfb = navigation["responseStart"] - navigation["requestStart"]
            content_download_time = (
                navigation["responseEnd"] - navigation["responseStart"]
            )
            total_network_time = navigation["responseEnd"] - navigation["startTime"]
        else:
            # Handle missing data
            dns_lookup_time = tcp_handshake_time = ssl_time = ttfb = None
            content_download_time = total_network_time = None

        # DOM Metrics
        required_timing_keys = [
            "domLoading",
            "domInteractive",
            "domComplete",
            "responseEnd",
            "navigationStart",
            "loadEventStart",
            "loadEventEnd",
        ]
        if all(key in timing and timing[key] > 0 for key in required_timing_keys):
            dom_parsing_time = timing["domInteractive"] - timing["domLoading"]
            rendering_time = timing["domComplete"] - timing["domInteractive"]
            load_event_time = timing["loadEventEnd"] - timing["loadEventStart"]
            browser_processing_time = timing["loadEventEnd"] - timing["responseEnd"]
            total_page_load_time = timing["loadEventEnd"] - timing["navigationStart"]
            adjusted_page_load_time = browser_processing_time

            # Adjusted DOM Parsing Time
            overlap_time_parsing = max(0, timing["responseEnd"] - timing["domLoading"])
            adjusted_dom_parsing_time = dom_parsing_time - overlap_time_parsing

            # Adjusted Rendering Time
            # Assuming no network activity after responseEnd
            adjusted_rendering_time = rendering_time

            # Adjusted Browser Processing Time is already calculated
            adjusted_browser_processing_time = browser_processing_time

            # Ensure no negative values
            adjusted_dom_parsing_time = max(adjusted_dom_parsing_time, 0)
            adjusted_rendering_time = max(adjusted_rendering_time, 0)
            adjusted_browser_processing_time = max(adjusted_browser_processing_time, 0)
        else:
            adjusted_dom_parsing_time = adjusted_rendering_time = (
                adjusted_browser_processing_time
            ) = None
            total_page_load_time = None

        # Resource Processing Times
        resource_processing_times = []
        for resource in resources:
            if "responseEnd" in resource and "responseStart" in resource:
                processing_time = resource["responseEnd"] - resource["responseStart"]
                resource_processing_times.append(processing_time)

        # Average Resource Processing Time
        average_resource_processing_time = (
            sum(resource_processing_times) / len(resource_processing_times)
            if resource_processing_times
            else None
        )

        # Total Transfer Size
        total_transfer_size = sum(
            resource.get("transferSize", 0) for resource in resources
        )

        # Compile network results
        network_result = {
            "website": site,
            "dns_lookup_time_ms": dns_lookup_time,
            "tcp_handshake_time_ms": tcp_handshake_time,
            "ssl_time_ms": ssl_time,
            "ttfb_ms": ttfb,
            "content_download_time_ms": content_download_time,
            "total_network_time_ms": total_network_time,
            "browser": browser.capitalize(),
            "status": "SUCCESS",
            "measurement_date": current_date,  # 3. Add measurement_date
        }
        network_results.append(network_result)

        # Compile DOM results
        dom_result = {
            "website": site,
            "adjusted_dom_parsing_time_ms": adjusted_dom_parsing_time,
            "adjusted_rendering_time_ms": adjusted_rendering_time,
            "adjusted_browser_processing_time_ms": adjusted_browser_processing_time,
            "browser": browser.capitalize(),
            "status": "SUCCESS",
            "measurement_date": current_date,  # 3. Add measurement_date
        }
        dom_results.append(dom_result)

        # Compile page load results
        page_load_result = {
            "website": site,
            "total_page_load_time_ms": total_page_load_time,
            "first_paint_ms": first_paint,
            "first_contentful_paint_ms": first_contentful_paint,
            "average_resource_processing_time_ms": average_resource_processing_time,
            "total_transfer_size_bytes": total_transfer_size,
            "browser": browser.capitalize(),
            "status": "SUCCESS",
            "measurement_date": current_date,  # 3. Add measurement_date
        }
        page_load_results.append(page_load_result)

        # Compile master result
        master_result = {**network_result, **dom_result, **page_load_result}
        # Remove duplicate 'website', 'browser', 'status' keys
        master_result = {
            k: v for k, v in master_result.items() if k not in ["browser", "status"]
        }
        master_result["browser"] = browser.capitalize()
        master_result["status"] = "SUCCESS"
        master_result["measurement_date"] = current_date  # 3. Add measurement_date
        master_results.append(master_result)

# Create DataFrames and save to CSV
network_df = pd.DataFrame(network_results)
dom_df = pd.DataFrame(dom_results)
page_load_df = pd.DataFrame(page_load_results)
master_df = pd.DataFrame(master_results)

# Save the results DataFrames
network_df.to_csv(os.path.join(results_dir, "network_metrics.csv"), index=False)
dom_df.to_csv(os.path.join(results_dir, "dom_metrics.csv"), index=False)
page_load_df.to_csv(os.path.join(results_dir, "page_load_metrics.csv"), index=False)
master_df.to_csv(os.path.join(results_dir, "performance_metrics.csv"), index=False)

# 4. Append to the Master Historical CSV
# Define the path to the master historical CSV
master_historical_dir = "./android-performance/data/historical"
master_historical_csv = os.path.join(
    master_historical_dir, "historical_performance_metrics.csv"
)

# Create the directory if it doesn't exist
os.makedirs(master_historical_dir, exist_ok=True)

# Append master_df to the master historical CSV
if not os.path.isfile(master_historical_csv):
    # If master historical CSV doesn't exist, create it with headers
    master_df.to_csv(master_historical_csv, mode="w", header=True, index=False)
    print(f"Created master historical CSV at {master_historical_csv}")
else:
    # Append without headers
    master_df.to_csv(master_historical_csv, mode="a", header=False, index=False)
    print(f"Appended new data to master historical CSV at {master_historical_csv}")
