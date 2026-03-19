import gspread
import json
import os
import random

SPREADSHEET_ID = "1wztmBmuPsRng43u29WLplWd2kq4zhh17eioYEMEgXiE"
TAB_NAME = "iOS Security Rotation"


def get_names_from_sheet():
    credentials = json.loads(os.environ["GCLOUD_AUTH"])
    gc = gspread.service_account_from_dict(credentials)
    spreadsheet = gc.open_by_key(SPREADSHEET_ID)
    worksheet = spreadsheet.worksheet(TAB_NAME)
    col_a = worksheet.col_values(1)
    return [name.strip() for name in col_a if name.strip()]


if __name__ == "__main__":
    names = get_names_from_sheet()
    if not names:
        raise ValueError("No names found in the sheet")

    picked = random.choice(names)
    print(f"Picked: {picked}")

    github_env = os.environ.get("GITHUB_ENV")
    if github_env:
        with open(github_env, "a") as f:
            # For testing, let the Slack message to ping me
            picked = "Clare So"
            f.write(f"security_monitor_name={picked}\n")
