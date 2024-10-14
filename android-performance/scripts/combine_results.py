import pandas as pd
import argparse
import os

# Parse command-line arguments
parser = argparse.ArgumentParser(
    description="Combine performance data for both browsers."
)
parser.add_argument(
    "--timestamp", type=str, required=True, help="Timestamp of test run"
)
args = parser.parse_args()
timestamp = args.timestamp
chrome_dir = (
    f"./android-performance/data/chrome/{timestamp}/results/performance_metrics.csv"
)
firefox_dir = (
    f"./android-performance/data/firefox/{timestamp}/results/performance_metrics.csv"
)

# os.makedirs(chrome_dir, exist_ok=True)
# os.makedirs(firefox_dir, exist_ok=True)

# Load data for both browsers
df_chrome = pd.read_csv(chrome_dir)
df_firefox = pd.read_csv(firefox_dir)

# Combine DataFrames
df_combined = pd.concat([df_chrome, df_firefox], ignore_index=True)

combined_dir = f"./android-performance/data/combined_results/{timestamp}/results"
os.makedirs(combined_dir, exist_ok=True)
# Save combined data
df_combined.to_csv(
    f"{combined_dir}/performance_results.csv",
    index=False,
)
