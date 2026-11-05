#!/usr/bin/env python3
"""
Count TestRail cases per feature and automation status, for Android and iOS.

Only aggregate counts are written. Titles, steps, section names and case IDs
are read to classify each case, then dropped: they never reach the output
file or the log. This repo and its Actions logs are public.

Usage:
    python collect_testrail.py --out site/data/testrail.json
"""

import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests

from feature_taxonomy import FEATURE_NAMES, UNCATEGORISED, classify

JSON_SCHEMA_VERSION = 1

# Full Functional Tests Suite per platform (same suites as tr-critical).
SUITES = {
    "android": 3192,
    "ios": 45443,
}

AUTOMATION_FIELD = "custom_automation_status"

# TestRail automation label -> status bucket. Anything else, including a
# blank field, "Untriaged" and "Disabled", counts as untriaged.
AUTOMATION_BUCKETS = {
    "Completed": "automated",
    "Suitable": "to_automate",
    "Unsuitable": "manual_only",
}
UNTRIAGED = "untriaged"
STATUSES = ["automated", "to_automate", "manual_only", UNTRIAGED]

CREDENTIALS = {
    "url": ("TESTRAIL_URL", "TESTRAIL_HOST"),
    "user": ("TESTRAIL_USER", "TESTRAIL_USERNAME"),
    "key": ("TESTRAIL_KEY", "TESTRAIL_PASSWORD"),
}


class TestRail:
    def __init__(self, base_url, user, key):
        self.base = base_url.rstrip("/") + "/index.php?/api/v2/"
        self.session = requests.Session()
        self.session.auth = (user, key)
        self.session.headers.update({"Content-Type": "application/json"})

    def get(self, endpoint):
        """GET with retry on TestRail's 429 rate limit."""
        for _ in range(5):
            resp = self.session.get(self.base + endpoint, timeout=60)
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", 10))
                print(f"  rate limited, waiting {wait}s", file=sys.stderr)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        raise RuntimeError(f"gave up after rate limits on {endpoint}")

    def get_paged(self, endpoint, key):
        """Page through a list endpoint. Handles both the paginated response
        (TestRail 6.7+) and the older bare-list response."""
        items, offset, limit = [], 0, 250
        while True:
            payload = self.get(f"{endpoint}&limit={limit}&offset={offset}")
            if isinstance(payload, list):
                return payload
            batch = payload.get(key, [])
            items.extend(batch)
            if len(batch) < limit:
                return items
            offset += limit


def option_map(field):
    """Build {id: label} from a dropdown field's "1, Completed" option lines."""
    out = {}
    for config in field.get("configs", []):
        items = config.get("options", {}).get("items", "")
        for line in items.splitlines():
            raw_id, sep, label = line.partition(",")
            if not sep:
                continue
            try:
                out[int(raw_id.strip())] = label.strip()
            except ValueError:
                continue
    return out


def resolve_credentials():
    """Read credentials from the environment without ever printing a value."""
    found, missing = {}, []
    for setting, names in CREDENTIALS.items():
        value = next((os.environ[n].strip() for n in names
                      if os.environ.get(n, "").strip()), None)
        if value is None:
            missing.append(" or ".join(names))
        found[setting] = value
    if missing:
        sys.exit("Missing TestRail credentials: " + "; ".join(missing))
    url = found["url"]
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url, found["user"], found["key"]


def collect(api, suite_id, automation_labels):
    project_id = api.get(f"get_suite/{suite_id}")["project_id"]
    # Leaf section names, as in the TestRail CSV export the taxonomy was
    # built against.
    sections = {
        s["id"]: s["name"]
        for s in api.get_paged(f"get_sections/{project_id}&suite_id={suite_id}",
                               "sections")
    }
    cases = api.get_paged(f"get_cases/{project_id}&suite_id={suite_id}", "cases")

    features = defaultdict(Counter)
    for case in cases:
        feature = classify(sections.get(case.get("section_id"), ""),
                           case.get("title") or "")
        label = automation_labels.get(case.get(AUTOMATION_FIELD))
        status = AUTOMATION_BUCKETS.get(label, UNTRIAGED)
        features[feature]["total"] += 1
        features[feature][status] += 1

    totals = Counter()
    for counts in features.values():
        totals.update(counts)

    # Taxonomy order, then Uncategorised. Only taxonomy names can appear.
    ordered = [f for f in FEATURE_NAMES + [UNCATEGORISED] if f in features]
    return {
        "suite_id": suite_id,
        "totals": {k: totals[k] for k in ["total"] + STATUSES},
        "features": {
            f: {k: features[f][k] for k in ["total"] + STATUSES}
            for f in ordered
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[1])
    parser.add_argument("--out", type=Path, default=Path("site/data/testrail.json"))
    args = parser.parse_args()

    api = TestRail(*resolve_credentials())
    field = next((f for f in api.get("get_case_fields")
                  if f.get("system_name") == AUTOMATION_FIELD), None)
    if field is None:
        sys.exit(f"TestRail has no case field named {AUTOMATION_FIELD}")
    automation_labels = option_map(field)

    data = {
        "schema_version": JSON_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "statuses": STATUSES,
    }
    for platform, suite_id in SUITES.items():
        print(f"Fetching {platform} (suite {suite_id})...", file=sys.stderr)
        data[platform] = collect(api, suite_id, automation_labels)
        t = data[platform]["totals"]
        print(f"{platform}: " + ", ".join(f"{k}={v}" for k, v in t.items())
              + f", uncategorised="
              f"{data[platform]['features'].get(UNCATEGORISED, {}).get('total', 0)}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
