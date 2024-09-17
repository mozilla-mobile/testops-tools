import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
from datetime import datetime
import os

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

# Define the test runs and corresponding CSV files
test_runs = {
    "5G": "5G_Page_Load_Times.csv",
    "4G": "4G_Page_Load_Times.csv",
    "3G": "3G_Page_Load_Times.csv",
    "2G": "2G_Page_Load_Times.csv",
}

# Initialize row index for inserting data (starting below the headers)
row_index = 2

# Add headers to the worksheet if they are not already added
headers = ["Test Type", "Website", "Page Load Time"]
if worksheet.cell(1, 1).value is None:
    worksheet.update("A1:C1", [headers])

# Loop through the test runs and append the results to the worksheet
for test_name, csv_file in test_runs.items():
    # Load the CSV file into a pandas DataFrame
    df = pd.read_csv(csv_file)

    # Add a 'Test Type' column to the DataFrame
    df.insert(0, "Test Type", test_name)

    # Post the results starting from the current row
    worksheet.update(f"A{row_index}", [df.columns.values.tolist()] + df.values.tolist())

    # Update the row index to continue appending after the current data
    row_index += len(df) + 1

    print(
        f"Posted results for {test_name} from {csv_file} to Google Sheet tab: {worksheet_title}"
    )
