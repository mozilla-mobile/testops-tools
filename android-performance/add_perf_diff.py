# import pandas as pd

# # Load the existing CSV file
# df = pd.read_csv("page_load_times.csv")

# # Calculate the percentage difference
# df["performance_difference"] = (
#     (df["firefox"] - df["google_chrome"]) / df["google_chrome"]
# ) * 100

# # Save the updated DataFrame back to the existing CSV
# df.to_csv("page_load_times.csv", index=False)

# print(df)

import pandas as pd

# Load the existing CSV file
df = pd.read_csv("page_load_times.csv")

# Calculate the percentage difference
df["performance_difference"] = (
    (df["firefox"] - df["google_chrome"]) / df["google_chrome"]
) * 100

# Save the updated DataFrame back to the existing CSV
df.to_csv("page_load_times.csv", index=False)

# Calculate the median performance difference
median_performance_difference = df["performance_difference"].median()

print(df)
print(f"Median performance difference: {median_performance_difference:.2f}%")
