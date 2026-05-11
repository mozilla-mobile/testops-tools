import json
import os
from datetime import date

JSON_FILE = os.path.join(os.path.dirname(__file__), "ios_sec_triage.json")


def load_data():
    with open(JSON_FILE) as f:
        return json.load(f)


def get_assignee_for_today():
    data = load_data()
    today = date.today().isoformat()
    return data["duty-start-dates"].get(today)


def get_current_assignee():
    data = load_data()
    today = date.today().isoformat()
    past_dates = [d for d in data["duty-start-dates"] if d <= today]
    if not past_dates:
        return None
    return data["duty-start-dates"][max(past_dates)]


if __name__ == "__main__":
    import sys
    if "--current" in sys.argv:
        print(get_current_assignee() or "")
    else:
        print(get_assignee_for_today() or "")
