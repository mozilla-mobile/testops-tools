# combine_results.py

import pandas as pd

# Load data for both browsers
df_chrome = pd.read_csv(
    "./android-performance/results/chrome/results/performance_metrics.csv"
)
df_firefox = pd.read_csv(
    "./android-performance/results/firefox/results/performance_metrics.csv"
)

# Combine DataFrames
df_combined = pd.concat([df_chrome, df_firefox], ignore_index=True)

# Save combined data
df_combined.to_csv(
    "./android-performance/results/combined_results/performance_metrics_combined.csv",
    index=False,
)
