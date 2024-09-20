import pandas as pd
import argparse
import os

# Parse command-line arguments
parser = argparse.ArgumentParser(description="Add performance difference to CSV.")
parser.add_argument(
    "--network", type=str, default="Unknown", help="Network type (e.g., 2G, 3G, 4G, 5G)"
)
parser.add_argument(
    "--timestamp", type=str, required=True, help="Timestamp of the CSV file"
)
args, unknown = parser.parse_known_args()

network_type = args.network
timestamp = args.timestamp

# Define the directory to save the results
results_dir = "./results"
os.makedirs(results_dir, exist_ok=True)

# Construct the output CSV file name with path
csv_filename = os.path.join(
    results_dir, f"{network_type}_Page_Load_Times_{timestamp}.csv"
)

# Load the existing CSV file
results_df = pd.read_csv(csv_filename)

# Save results to CSV
results_df.to_csv(csv_filename, index=False)

# Load the existing CSV file
df = pd.read_csv(csv_filename)

# Calculate the percentage difference
df["performance_difference"] = (
    (df["firefox"] - df["google_chrome"]) / df["google_chrome"]
) * 100

# Save the updated DataFrame back to the existing CSV
df.to_csv(csv_filename, index=False)

# Calculate the median performance difference
median_performance_difference = df["performance_difference"].median()

print(df)
print(f"Median performance difference: {median_performance_difference:.2f}%")
