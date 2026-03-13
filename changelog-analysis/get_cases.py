import os
import requests
from datetime import datetime
from typing import List, Dict, Any, Set, Optional


TESTRAIL_HOST = os.environ["TESTRAIL_HOST"]
TESTRAIL_USERNAME = os.environ["TESTRAIL_USERNAME"]
TESTRAIL_PASSWORD = os.environ["TESTRAIL_PASSWORD"]

PROJECT_ID = 75
SUITE_ID = 40281
MILESTONE_ID = 6652

PAGE_LIMIT = 250  # TestRail max page size

API_BASE = f"{TESTRAIL_HOST}/index.php?/api/v2"


# ===============================
# HELPERS
# ===============================

def tr_get(url: str) -> Dict[str, Any]:
    r = requests.get(url, auth=(TESTRAIL_USERNAME, TESTRAIL_PASSWORD))
    if r.status_code >= 400:
        try:
            print("TestRail error:", r.json())
        except Exception:
            print("TestRail error text:", r.text[:2000])
        r.raise_for_status()
    return r.json()

def tr_post(url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    r = requests.post(url, json=payload, auth=(TESTRAIL_USERNAME, TESTRAIL_PASSWORD))
    if r.status_code >= 400:
        try:
            print("TestRail error:", r.json())
        except Exception:
            print("TestRail error text:", r.text[:2000])
        r.raise_for_status()
    return r.json()


def case_label_titles(case):
    labels = case.get("labels") or []
    return {
        l.get("title")
        for l in labels
        if isinstance(l, dict) and l.get("title")
    }

# ===============================
# FETCH + FILTER CASES
# ===============================

def get_all_cases_in_suite(project_id: int, suite_id: int) -> List[Dict[str, Any]]:
    all_cases = []
    offset = 0

    while True:
        url = (
            f"{API_BASE}/get_cases/{project_id}"
            f"&suite_id={suite_id}"
            f"&limit={PAGE_LIMIT}&offset={offset}"
        )

        data = tr_get(url)
        cases = data.get("cases", [])
        all_cases.extend(cases)

        if len(cases) < PAGE_LIMIT:
            break
        offset += PAGE_LIMIT

    return all_cases

def get_cases_by_labels(labels: List[str],
                        project_id: int = PROJECT_ID,
                        suite_id: int = SUITE_ID) -> List[Dict[str, Any]]:
    all_cases = get_all_cases_in_suite(project_id, suite_id)
    return filter_cases_by_labels(all_cases, labels)


def filter_cases_by_labels(cases: List[Dict[str, Any]], labels: List[str]) -> List[Dict[str, Any]]:
    wanted = set(labels)
    matched = []
    for c in cases:
        if case_label_titles(c) & wanted:
            matched.append(c)
    return matched

# ===============================
# CREATE RUN
# ===============================

def create_test_run(case_ids, name=None, description=None, milestone_id=None):
    if not case_ids:
        raise ValueError("case_ids is empty — refusing to create an empty run.")

    if name is None:
        from datetime import datetime
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        name = f"RTS Smart Run ({ts})"

    payload = {
        "suite_id": SUITE_ID,
        "name": name,
        "include_all": False,
        "case_ids": sorted(set(case_ids)),
    }

    if description:
        payload["description"] = description

    if milestone_id:
        payload["milestone_id"] = milestone_id

    url = f"{API_BASE}/add_run/{PROJECT_ID}"
    return tr_post(url, payload)
