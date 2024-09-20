import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
from datetime import datetime
import os
import json
import glob

# Get the credentials JSON from the environment variable
creds_json = os.getenv("ANDROID_PERFORMANCE_GA_SERVICE_ACCOUNT")

# Check if the environment variable is set correctly
if not creds_json:
    raise ValueError(
        "The environment variable ANDROID_PERFORMANCE_GA_SERVICE_ACCOUNT is not set."
    )

# Convert the JSON string to a Python dictionary
creds_dict = json.loads(creds_json)

# Google Sheets setup
SCOPE = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Create a Credentials object from the service account info
creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPE)

# Authorize the client
client = gspread.authorize(creds)

# Open the Google Sheet by URL or ID
SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1WU-fNMpHXvyuezFrH5JFpDQJ0HflAqyZ-cK_3xgvWG4/edit"
sheet = client.open_by_url(SPREADSHEET_URL)

# Get today's date to use in the sheet title
today = datetime.today().strftime("%Y-%m-%d")

# Create or select a worksheet for today's test results
worksheet_title = f"{today} - Performance Test Results"
try:
    worksheet = sheet.worksheet(worksheet_title)
except gspread.WorksheetNotFound:
    worksheet = sheet.add_worksheet(title=worksheet_title, rows="500", cols="20")

# Initialize row index for inserting data (starting below the headers)
row_index = 2

# Add headers to the worksheet if they are not already added
headers = ["Test Type", "Website", "Google Chrome", "Firefox", "Performance Difference"]
if worksheet.cell(1, 1).value is None:
    worksheet.update("A1:E1", [headers])

# Define the directory where CSV files are stored
results_dir = "./results"

# Find all CSV files in the results directory
csv_files = glob.glob(os.path.join(results_dir, "*_Page_Load_Times_*.csv"))

# Loop through the CSV files and append the results to the worksheet
for csv_file in csv_files:
    # Extract the network type from the file name
    filename = os.path.basename(csv_file)
    network_type = filename.split("_")[0]

    # Load the CSV file into a pandas DataFrame
    df = pd.read_csv(csv_file)

    # Add a 'Test Type' column to the DataFrame
    df.insert(0, "Test Type", network_type)

    # Prepare data for uploading
    data = df.values.tolist()
    data.insert(0, df.columns.values.tolist())  # Include headers

    # Post the results starting from the current row
    cell_range = f"A{row_index}:E{row_index + len(df)}"
    worksheet.update(cell_range, data)

    # Update the row index to continue appending after the current data
    row_index += len(df) + 2  # Adding 2 to leave a blank row between tests

    print(
        f"Posted results for {network_type} from {csv_file} to Google Sheet tab: {worksheet_title}"
    )
