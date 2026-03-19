import gspread
import json
import os

SPREADSHEET_ID = "1wztmBmuPsRng43u29WLplWd2kq4zhh17eioYEMEgXiE"
TAB_NAME = "iOS Security Rotation"
STATE_FILE = os.path.join(os.path.dirname(__file__), "security_monitor_state.txt")


def get_names_from_sheet():
    credentials = json.loads(os.environ["GCLOUD_AUTH"])
    gc = gspread.service_account_from_dict(credentials)
    spreadsheet = gc.open_by_key(SPREADSHEET_ID)
    worksheet = spreadsheet.worksheet(TAB_NAME)
    col_a = worksheet.col_values(1)
    return [name.strip() for name in col_a if name.strip()]


def get_next_assignee(names):
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            current = f.read().strip()
        if current in names:
            next_index = (names.index(current) + 1) % len(names)
        else:
            next_index = 0
    else:
        next_index = 0

    next_assignee = names[next_index]
    with open(STATE_FILE, "w") as f:
        f.write(next_assignee)
    return next_assignee


if __name__ == "__main__":
    names = get_names_from_sheet()
    if not names:
        raise ValueError("No names found in the sheet")

    picked = get_next_assignee(names)
    print(f"Picked: {picked}")

    github_env = os.environ.get("GITHUB_ENV")
    if github_env:
        with open(github_env, "a") as f:
            f.write(f"security_monitor_name={picked}\n")
