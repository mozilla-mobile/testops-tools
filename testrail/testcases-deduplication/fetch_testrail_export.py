#!/usr/bin/env python3
"""
Fetch test cases from the TestRail API and export as xlsx for deduplication analysis.

Reads credentials from environment variables:
    TESTRAIL_HOST      — e.g. "yourcompany.testrail.io"
    TESTRAIL_USERNAME  — API user email
    TESTRAIL_PASSWORD  — API key or password

Usage:
    python fetch_testrail_export.py --project-id 14 --output export.xlsx
    python fetch_testrail_export.py --project-id 14 --suite-id 123 --output export.xlsx
"""
import argparse
import os
import sys

import pandas as pd
import requests
from requests.auth import HTTPBasicAuth


def testrail_client() -> tuple[str, HTTPBasicAuth]:
    host = os.environ.get("TESTRAIL_HOST", "").rstrip("/").removeprefix("https://").removeprefix("http://")
    username = os.environ.get("TESTRAIL_USERNAME", "")
    password = os.environ.get("TESTRAIL_PASSWORD", "")

    if not all([host, username, password]):
        print("Error: TESTRAIL_HOST, TESTRAIL_USERNAME and TESTRAIL_PASSWORD must be set.")
        sys.exit(1)

    base_url = f"https://{host}/index.php?/api/v2"
    return base_url, HTTPBasicAuth(username, password)


REQUEST_TIMEOUT = 30  # seconds


def api_get(base_url: str, auth: HTTPBasicAuth, endpoint: str, params: dict = None) -> dict:
    url = f"{base_url}/{endpoint}"
    resp = requests.get(url, auth=auth, params=params or {}, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def fetch_cases(base_url: str, auth: HTTPBasicAuth, project_id: str, suite_id: str = None) -> list[dict]:
    """Fetch all test cases for a project (paginated, 250 per page)."""
    cases = []
    offset = 0
    limit = 250

    while True:
        params = {"limit": limit, "offset": offset}
        if suite_id:
            params["suite_id"] = suite_id

        data = api_get(base_url, auth, f"get_cases/{project_id}", params)
        batch = data.get("cases", [])
        cases.extend(batch)

        if len(batch) < limit:
            break
        offset += len(batch)  # advance by page size, not cumulative total

    return cases


def fetch_sections(base_url: str, auth: HTTPBasicAuth, project_id: str, suite_id: str = None) -> dict[int, str]:
    """Return a mapping of section_id → section name (paginated, 250 per page)."""
    sections = []
    offset = 0
    limit = 250

    while True:
        params = {"limit": limit, "offset": offset}
        if suite_id:
            params["suite_id"] = suite_id

        data = api_get(base_url, auth, f"get_sections/{project_id}", params)
        batch = data.get("sections", [])
        sections.extend(batch)

        if len(batch) < limit:
            break
        offset += len(batch)

    return {s["id"]: s["name"] for s in sections}


def format_steps(steps_list: list[dict], field: str) -> str:
    """Convert [{content, expected}, ...] to a numbered string (TestRail xlsx export format)."""
    if not steps_list:
        return ""
    return "\n".join(f"{i}. {step.get(field, '')}" for i, step in enumerate(steps_list, 1))


def build_xlsx(cases: list[dict], sections: dict[int, str], output_path: str) -> None:
    rows = []
    for case in cases:
        steps_raw = case.get("custom_steps_separated") or []
        rows.append({
            "ID": f"C{case['id']}",
            "Title": case.get("title", ""),
            "Section": sections.get(case.get("section_id"), ""),
            "Steps (Step)": format_steps(steps_raw, "content"),
            "Steps (Expected Result)": format_steps(steps_raw, "expected"),
        })

    df = pd.DataFrame(rows)
    df.to_excel(output_path, index=False)
    print(f"Exported {len(df)} test cases to {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Fetch TestRail test cases and export as xlsx for deduplication."
    )
    parser.add_argument("--project-id", required=True, help="TestRail project ID")
    parser.add_argument("--suite-id", default=None, help="TestRail suite ID (optional, fetches all suites if omitted)")
    parser.add_argument("--output", default="testrail_export.xlsx", help="Output xlsx file path")
    args = parser.parse_args()

    base_url, auth = testrail_client()

    print(f"Fetching test cases for project {args.project_id}...")
    cases = fetch_cases(base_url, auth, args.project_id, args.suite_id)
    print(f"Fetched {len(cases)} test cases")

    if not cases:
        print("No test cases found. Check project ID and suite ID.")
        sys.exit(1)

    print("Fetching section names...")
    sections = fetch_sections(base_url, auth, args.project_id, args.suite_id)

    build_xlsx(cases, sections, args.output)


if __name__ == "__main__":
    main()
