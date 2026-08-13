#!/usr/bin/env python3
"""Import reviewed manual test cases into TestRail.

Single action, no modes: it reads the reviewed CSV for a feature, creates a
root section named after the feature, recreates the CSV's section structure
underneath it, and creates every test case inside that structure.

Usage:
    python scripts/testrail_import.py <feature_name>

Example:
    python scripts/testrail_import.py google-lens

Configuration is read from environment variables (a local .env is loaded if
python-dotenv is installed):

    TESTRAIL_URL, TESTRAIL_USER, TESTRAIL_API_KEY,
    TESTRAIL_PROJECT_ID, TESTRAIL_SUITE_ID            (required)

    TESTRAIL_SUITE_ID_LOW                             (required only when the CSV
                                                      has Low-priority cases;
                                                      Low cases import here while
                                                      Critical/High/Medium go to
                                                      TESTRAIL_SUITE_ID)

    TESTRAIL_TEMPLATE_ID                              (optional)
    TESTRAIL_USE_SEPARATED_STEPS = true|false         (optional)
    TESTRAIL_EXTERNAL_ID_FIELD   = custom_external_id (optional)
    TESTRAIL_PRECONDITIONS_FIELD = custom_preconds
    TESTRAIL_STEPS_FIELD         = custom_steps
    TESTRAIL_EXPECTED_FIELD      = custom_expected
    TESTRAIL_SEPARATED_STEPS_FIELD = custom_steps_separated
    TESTRAIL_SUB_TEST_SUITE_FIELD = custom_sub_test_suites  (multi-select; the
                                    CSV 'Sub Test Suite(s)' labels are mapped to
                                    this field's option ids)
    TESTRAIL_REFERENCES_FIELD    = refs
    TESTRAIL_REQUEST_TIMEOUT     = 30
    TESTRAIL_MAX_RETRIES         = 3
"""

from __future__ import annotations

import csv
import os
import re
import sys
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests
from requests.auth import HTTPBasicAuth

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

OUTPUT_ROOT = Path("work/outputs")

REQUIRED_COLUMNS = ("section", "title", "steps", "expected", "priority", "type")

# One logical column -> accepted CSV header aliases.
COLUMN_ALIASES = {
    "section": ["Section (Folder)", "Section", "Folder", "Section Path"],
    "title": ["Title", "Test Case", "Test Case Title", "Name"],
    "preconditions": ["Preconditions", "Precondition", "Pre-conditions"],
    "steps": ["Steps", "Test Steps", "Procedure"],
    "expected": ["Expected Results", "Expected Result", "Expected", "Results"],
    "priority": ["Priority"],
    "type": ["Type", "Test Type"],
    "sub_test_suite": ["Sub Test Suite(s)", "Sub Test Suite", "Sub Test Suites"],
    "references": ["References", "Reference", "Refs", "Jira"],
}

PRIORITY_ALIASES = {"p0": "critical", "p1": "high", "p2": "medium", "p3": "low"}

# Priority categories routed to the LOW suite; everything else goes to the
# default suite.
LOW_PRIORITY_CATEGORIES = {"low"}


def priority_category(priority: str) -> str:
    """Normalize a priority cell to a lowercase category (critical/high/medium/low)."""
    lookup = key(priority)
    return PRIORITY_ALIASES.get(lookup, lookup)

NUMBERED_ITEM = re.compile(
    r"^\s*(?:(?:step\s+)?(?P<number>\d+)\s*[\.\):\-])\s*(?P<text>.*)$",
    re.IGNORECASE,
)

TEMPORARY_HTTP_CODES = {409, 429, 500, 502, 503, 504}


class ImporterError(Exception):
    """Base error for the importer."""


# --------------------------------------------------------------------------- #
# Text helpers
# --------------------------------------------------------------------------- #

def norm(value: str) -> str:
    """Normalize unicode + line endings, strip trailing spaces per line."""
    value = unicodedata.normalize("NFKC", value or "")
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+$", "", line) for line in value.split("\n")]
    return "\n".join(lines).strip()


def key(value: str) -> str:
    """Case-insensitive comparison key."""
    return re.sub(r"\s+", " ", norm(value).lower()).strip()


def field_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", unicodedata.normalize("NFKC", value or "").lower())


def feature_display_name(feature: str) -> str:
    parts = re.split(r"[-_\s]+", feature.strip())
    return " ".join(word.capitalize() for word in parts if word) or feature


def split_section(path: str) -> list[str]:
    """Split a section path on / > :: into its parts."""
    path = re.sub(r"\s*(?:::|>|/)\s*", "/", norm(path))
    return [re.sub(r"\s+", " ", part).strip() for part in path.split("/") if part.strip()]


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

@dataclass
class Config:
    url: str
    user: str
    api_key: str
    project_id: int
    suite_id: int
    suite_id_low: int | None
    template_id: int | None
    default_priority_id: int | None
    default_type_id: int | None
    external_id_field: str
    references_field: str
    preconditions_field: str
    steps_field: str
    expected_field: str
    separated_steps_field: str
    sub_test_suite_field: str
    use_separated_steps: bool
    request_timeout: int
    max_retries: int
    external_id_available: bool = True
    sub_test_suite_available: bool = True


def _int_env(name: str, default: int | None = None, required: bool = False) -> int | None:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        if required:
            raise ImporterError(f"Missing required environment variable: {name}")
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ImporterError(f"Environment variable {name} must be an integer.") from exc


def load_config() -> Config:
    if load_dotenv is not None:
        load_dotenv()

    url = (os.getenv("TESTRAIL_URL") or "").rstrip("/")
    if not url:
        raise ImporterError("Missing required environment variable: TESTRAIL_URL")
    if not url.startswith(("https://", "http://localhost", "http://127.0.0.1")):
        raise ImporterError("TESTRAIL_URL must use HTTPS (or an explicit local instance).")

    user = os.getenv("TESTRAIL_USER")
    api_key = os.getenv("TESTRAIL_API_KEY")
    if not user or not api_key:
        raise ImporterError("Missing TESTRAIL_USER and/or TESTRAIL_API_KEY.")

    return Config(
        url=url,
        user=user,
        api_key=api_key,
        project_id=_int_env("TESTRAIL_PROJECT_ID", required=True),
        suite_id=_int_env("TESTRAIL_SUITE_ID", required=True),
        suite_id_low=_int_env("TESTRAIL_SUITE_ID_LOW"),
        template_id=_int_env("TESTRAIL_TEMPLATE_ID"),
        default_priority_id=_int_env("TESTRAIL_DEFAULT_PRIORITY_ID"),
        default_type_id=_int_env("TESTRAIL_DEFAULT_TYPE_ID"),
        external_id_field=os.getenv("TESTRAIL_EXTERNAL_ID_FIELD", "custom_external_id"),
        references_field=os.getenv("TESTRAIL_REFERENCES_FIELD", "refs"),
        preconditions_field=os.getenv("TESTRAIL_PRECONDITIONS_FIELD", "custom_preconds"),
        steps_field=os.getenv("TESTRAIL_STEPS_FIELD", "custom_steps"),
        expected_field=os.getenv("TESTRAIL_EXPECTED_FIELD", "custom_expected"),
        separated_steps_field=os.getenv(
            "TESTRAIL_SEPARATED_STEPS_FIELD", "custom_steps_separated"
        ),
        sub_test_suite_field=os.getenv(
            "TESTRAIL_SUB_TEST_SUITE_FIELD", "custom_sub_test_suites"
        ),
        use_separated_steps=(os.getenv("TESTRAIL_USE_SEPARATED_STEPS", "") or "")
        .strip()
        .lower()
        in {"1", "true", "yes", "on"},
        request_timeout=_int_env("TESTRAIL_REQUEST_TIMEOUT", 30),
        max_retries=_int_env("TESTRAIL_MAX_RETRIES", 3),
    )


# --------------------------------------------------------------------------- #
# CSV parsing
# --------------------------------------------------------------------------- #

@dataclass
class TestCase:
    csv_row: int
    section_path: str
    title: str
    preconditions: str
    steps: str
    expected: str
    priority: str
    type: str
    sub_test_suite: str
    references: str
    step_pairs: list[tuple[str, str]] = field(default_factory=list)


def resolve_columns(headers: list[str]) -> dict[str, str]:
    """Map each logical column to the matching CSV header."""
    by_norm: dict[str, str] = {}
    for header in headers:
        normalized = field_key(header)
        if normalized in by_norm:
            raise ImporterError(f"Duplicate CSV column: {header}")
        by_norm[normalized] = header

    mapping: dict[str, str] = {}
    for logical, aliases in COLUMN_ALIASES.items():
        # Several aliases can normalize to the same key (e.g. "Preconditions"
        # and "Pre-conditions"); count distinct matched columns only.
        matches = list(dict.fromkeys(by_norm[field_key(a)] for a in aliases if field_key(a) in by_norm))
        if len(matches) > 1:
            raise ImporterError(f"Multiple CSV columns map to '{logical}': {', '.join(matches)}")
        if matches:
            mapping[logical] = matches[0]

    missing = [c for c in REQUIRED_COLUMNS if c not in mapping]
    if missing:
        raise ImporterError("CSV is missing required columns: " + ", ".join(missing))
    return mapping


def parse_numbered(value: str) -> list[tuple[int, str]]:
    """Split a Steps / Expected Results cell into (number, text) items.

    A line that is not numbered is a CONTINUATION of the item above it — most
    often a bullet under a numbered expected result — and is appended to that
    item rather than treated as an item of its own. Only a cell with no
    numbered items at all falls back to one-item-per-line.
    """
    lines = [norm(line) for line in norm(value).splitlines() if norm(line)]
    items: list[list] = []       # [number, [line, ...]]
    preamble: list[str] = []     # unnumbered lines before the first numbered item

    for line in lines:
        match = NUMBERED_ITEM.match(line)
        if match:
            items.append([int(match.group("number")), [norm(match.group("text"))]])
        elif items:
            items[-1][1].append(line)
        else:
            preamble.append(line)

    if not items:
        # No numbering anywhere: each line is its own item, as before.
        return [(i, line) for i, line in enumerate(lines, start=1)]

    if preamble:
        # Keep stray leading text with the first item so the numbering holds.
        items[0][1] = preamble + items[0][1]

    return [(number, norm("\n".join(parts))) for number, parts in items]


def pair_steps(steps: str, expected: str) -> list[tuple[str, str]]:
    step_items = parse_numbered(steps)
    expected_by_num = {n: t for n, t in parse_numbered(expected)}
    exp_list = parse_numbered(expected)
    pairs: list[tuple[str, str]] = []
    for index, (number, text) in enumerate(step_items):
        if number in expected_by_num:
            pairs.append((text, expected_by_num[number]))
        elif index < len(exp_list):
            pairs.append((text, exp_list[index][1]))
        else:
            pairs.append((text, ""))
    return pairs


def find_csv(feature_dir: Path, feature: str) -> Path:
    # Canonical name is "<feature>-testcases.csv"; the underscore form is
    # accepted for older suites. Either way, a single CSV in the folder wins.
    for name in (f"{feature}-testcases.csv", f"{feature}_testcases.csv"):
        exact = feature_dir / name
        if exact.exists():
            return exact
    candidates = [
        p for p in sorted(feature_dir.glob("*.csv"))
        if not p.name.startswith(("~", "."))
    ]
    if not candidates:
        raise ImporterError(f"No CSV file found in {feature_dir}")
    if len(candidates) > 1:
        raise ImporterError(
            "Multiple CSV files found; keep exactly one: "
            + ", ".join(p.name for p in candidates)
        )
    return candidates[0]


def parse_csv(csv_path: Path) -> list[TestCase]:
    cases: list[TestCase] = []
    errors: list[str] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ImporterError("CSV does not contain a header.")
        cols = resolve_columns(reader.fieldnames)

        for row_num, raw in enumerate(reader, start=2):
            if None in raw:
                errors.append(f"Row {row_num}: more values than header columns.")
                continue
            if all(norm(v or "") == "" for v in raw.values()):
                continue

            def cell(logical: str) -> str:
                col = cols.get(logical)
                return norm(raw.get(col, "") or "") if col else ""

            case = TestCase(
                csv_row=row_num,
                section_path=" / ".join(split_section(cell("section"))),
                title=cell("title"),
                preconditions=cell("preconditions"),
                steps=cell("steps"),
                expected=cell("expected"),
                priority=cell("priority"),
                type=cell("type"),
                sub_test_suite=cell("sub_test_suite"),
                references=cell("references"),
            )
            required = {
                "Section": case.section_path, "Title": case.title,
                "Steps": case.steps, "Expected Results": case.expected,
                "Priority": case.priority, "Type": case.type,
            }
            row_errors = [f"{name} is empty" for name, val in required.items() if not val]
            if row_errors:
                errors.append(f"Row {row_num}: " + "; ".join(row_errors))
                continue

            case.step_pairs = pair_steps(case.steps, case.expected)
            if not case.step_pairs:
                errors.append(f"Row {row_num}: no steps/expected results.")
                continue
            cases.append(case)

    if errors:
        raise ImporterError("CSV validation failed:\n  - " + "\n  - ".join(errors))
    if not cases:
        raise ImporterError("CSV contains no test cases.")
    return cases


# --------------------------------------------------------------------------- #
# TestRail client
# --------------------------------------------------------------------------- #

class TestRailClient:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.base_url = f"{config.url}/index.php?/api/v2/"
        self.session = requests.Session()
        self.session.auth = HTTPBasicAuth(config.user, config.api_key)
        self.session.headers.update(
            {"Content-Type": "application/json", "Accept": "application/json"}
        )

    def _request(self, method: str, endpoint: str, payload: dict | None = None) -> Any:
        url = self.base_url + endpoint
        for attempt in range(self.config.max_retries + 1):
            try:
                response = self.session.request(
                    method, url, json=payload, timeout=self.config.request_timeout
                )
            except requests.RequestException as exc:
                if attempt >= self.config.max_retries:
                    raise ImporterError(f"Network error calling TestRail: {exc}") from exc
                time.sleep(min(2 ** attempt, 10))
                continue

            if response.status_code in {200, 201}:
                return response.json() if response.content else {}
            if response.status_code in {401, 403}:
                raise ImporterError(
                    f"TestRail authentication failed (HTTP {response.status_code})."
                )
            if response.status_code in TEMPORARY_HTTP_CODES and attempt < self.config.max_retries:
                retry_after = response.headers.get("Retry-After")
                delay = int(float(retry_after)) if retry_after else min(2 ** attempt, 30)
                time.sleep(max(1, delay))
                continue

            raise ImporterError(
                f"TestRail API error (HTTP {response.status_code}) on {endpoint}: "
                f"{response.text[:500]}"
            )
        raise ImporterError(f"TestRail request failed: {endpoint}")

    def get(self, endpoint: str) -> Any:
        return self._request("GET", endpoint)

    def post(self, endpoint: str, payload: dict) -> Any:
        return self._request("POST", endpoint, payload)

    def _paginated(self, endpoint: str, collection: str) -> list[dict]:
        items: list[dict] = []
        offset = 0
        sep = "&" if ("&" in endpoint or "?" in endpoint) else "?"
        while True:
            page = self.get(f"{endpoint}{sep}{urlencode({'limit': 250, 'offset': offset})}")
            if isinstance(page, list):
                items.extend(page)
                break
            batch = page.get(collection, [])
            items.extend(batch)
            if (page.get("_links") or {}).get("next"):
                offset += len(batch)
                continue
            if page.get("size", len(batch)) < page.get("limit", 250) or not batch:
                break
            offset += len(batch)
        return items

    def get_project(self, pid: int) -> dict:
        return self.get(f"get_project/{pid}")

    def get_suite(self, sid: int) -> dict:
        return self.get(f"get_suite/{sid}")

    def get_sections(self, suite_id: int) -> list[dict]:
        return self._paginated(
            f"get_sections/{self.config.project_id}&suite_id={suite_id}",
            "sections",
        )

    def get_priorities(self) -> list[dict]:
        return self.get("get_priorities")

    def get_case_types(self) -> list[dict]:
        return self.get("get_case_types")

    def get_case_fields(self) -> list[dict]:
        return self.get("get_case_fields")

    def get_templates(self) -> list[dict]:
        return self.get(f"get_templates/{self.config.project_id}")

    def add_section(self, name: str, parent_id: int | None, suite_id: int) -> dict:
        payload: dict[str, Any] = {"suite_id": suite_id, "name": name}
        if parent_id is not None:
            payload["parent_id"] = parent_id
        return self.post(f"add_section/{self.config.project_id}", payload)

    def add_case(self, section_id: int, payload: dict) -> dict:
        return self.post(f"add_case/{section_id}", payload)


# --------------------------------------------------------------------------- #
# Section tree (feature root + nested structure)
# --------------------------------------------------------------------------- #

class SectionTree:
    """Resolves/creates sections, caching by (parent_id, name) so a path is
    only created once and existing sections are reused."""

    def __init__(self, client: TestRailClient, suite_id: int) -> None:
        self.client = client
        self.suite_id = suite_id
        # (parent_id or 0, name_key) -> section_id
        self.index: dict[tuple[int, str], int] = {}
        for section in client.get_sections(suite_id):
            parent = int(section.get("parent_id") or 0)
            self.index[(parent, key(section["name"]))] = int(section["id"])
        self.created = 0

    def resolve(self, parts: list[str]) -> int:
        """Return the section id for a path, creating missing sections."""
        parent_id = 0
        for name in parts:
            cache_key = (parent_id, key(name))
            section_id = self.index.get(cache_key)
            if section_id is None:
                created = self.client.add_section(name, parent_id or None, self.suite_id)
                section_id = int(created["id"])
                self.index[cache_key] = section_id
                self.created += 1
            parent_id = section_id
        return parent_id


# --------------------------------------------------------------------------- #
# Mapping + payload
# --------------------------------------------------------------------------- #

def by_name(values: list[dict]) -> dict[str, dict]:
    return {key(str(v.get("name", ""))): v for v in values if v.get("name")}


def map_id(value: str, available: dict[str, dict], default_id: int | None,
           aliases: dict[str, str] | None = None) -> int:
    lookup = key(value)
    if aliases and lookup in aliases:
        lookup = key(aliases[lookup])
    if lookup in available:
        return int(available[lookup]["id"])
    if default_id is not None:
        return default_id
    raise ImporterError(f"Cannot map '{value}' to a TestRail id.")


def multiselect_option_map(field: dict | None) -> dict[str, int]:
    """label_key -> option id for a TestRail multi-select/dropdown case field.

    Options come back as an "items" string like "9, Special Case\n10, Regression".
    """
    result: dict[str, int] = {}
    if not field:
        return result
    for cfg in field.get("configs", []):
        items = ((cfg.get("options") or {}).get("items") or "")
        for line in items.splitlines():
            line = line.strip()
            if not line:
                continue
            match = re.match(r"^(\d+)\s*,\s*(.+)$", line)
            if match:
                result[key(match.group(2))] = int(match.group(1))
    return result


def map_sub_test_suites(raw: str, label_to_id: dict[str, int]) -> tuple[list[int], list[str]]:
    """Map a comma-separated 'Sub Test Suite(s)' cell to option ids + unknown labels."""
    ids: list[int] = []
    unknown: list[str] = []
    for part in raw.split(","):
        label = part.strip()
        if not label:
            continue
        option_id = label_to_id.get(key(label))
        if option_id is None:
            unknown.append(label)
        elif option_id not in ids:
            ids.append(option_id)
    return ids, unknown


def build_payload(case: TestCase, config: Config, priority_id: int, type_id: int,
                  sub_test_suite_ids: list[int] | None = None) -> dict:
    payload: dict[str, Any] = {
        "title": case.title,
        "priority_id": priority_id,
        "type_id": type_id,
    }
    if config.template_id is not None:
        payload["template_id"] = config.template_id
    if case.references:
        payload[config.references_field] = case.references
    if case.preconditions:
        payload[config.preconditions_field] = case.preconditions
    if sub_test_suite_ids:
        payload[config.sub_test_suite_field] = sub_test_suite_ids

    if config.use_separated_steps and config.separated_steps_field:
        payload[config.separated_steps_field] = [
            {"content": step, "expected": exp} for step, exp in case.step_pairs
        ]
    else:
        payload[config.steps_field] = case.steps
        payload[config.expected_field] = case.expected
    return payload


def check_custom_fields(config: Config, case_fields: list[dict]) -> None:
    available = {str(f.get("system_name", "")).strip() for f in case_fields if f.get("system_name")}

    content_fields = {config.preconditions_field, config.expected_field}
    content_fields.add(config.separated_steps_field if config.use_separated_steps else config.steps_field)
    missing = sorted(f for f in content_fields if f.startswith("custom_") and f not in available)
    if missing:
        raise ImporterError(
            "Required TestRail custom fields do not exist: " + ", ".join(missing)
        )

    config.external_id_available = not (
        config.external_id_field.startswith("custom_")
        and config.external_id_field not in available
    )

    config.sub_test_suite_available = not (
        config.sub_test_suite_field.startswith("custom_")
        and config.sub_test_suite_field not in available
    )


# --------------------------------------------------------------------------- #
# Import
# --------------------------------------------------------------------------- #

def write_report(feature: str, feature_dir: Path, csv_path: Path, config: Config,
                 project: dict, root_name: str, suite_summaries: list[dict],
                 sections_created: int, created: list[dict], failed: list[dict]) -> Path:
    report_path = feature_dir / "testrail_import_report.md"
    suite_line = ", ".join(
        f"{s['label']} = {s['suite_id']}" for s in suite_summaries
    ) or str(config.suite_id)
    lines = [
        "# TestRail Import Report",
        "",
        f"- Feature: {feature}",
        f"- TestRail URL: {config.url}",
        f"- Project: {project.get('name')} (ID {config.project_id})",
        f"- Suites: {suite_line}",
        f"- Root section: {root_name}",
        f"- CSV: {csv_path}",
        f"- Import date: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"- Status: {'COMPLETED' if not failed else 'COMPLETED_WITH_ERRORS'}",
        "",
        "## Summary",
        "",
        "| Result | Count |",
        "|---|---:|",
        f"| Sections created | {sections_created} |",
        f"| Cases created | {len(created)} |",
        f"| Cases failed | {len(failed)} |",
        "",
        "## Per-suite breakdown",
        "",
        "| Suite | Suite ID | Priorities | Sections created | Cases created |",
        "|---|---:|---|---:|---:|",
    ]
    lines += [
        f"| {s['label']} | {s['suite_id']} | {s['priorities']} | "
        f"{s['sections_created']} | {s['cases_created']} |"
        for s in suite_summaries
    ]
    lines += [
        "",
        "## Created cases",
        "",
        "| TestRail Case ID | Title | Priority | Suite ID | Section |",
        "|---:|---|---|---:|---|",
    ]
    lines += [
        f"| {c['id']} | {c['title']} | {c.get('priority', '')} | "
        f"{c['suite_id']} | {c['section']} |"
        for c in created
    ]
    if failed:
        lines += ["", "## Failed cases", "", "| Title | Error |", "|---|---|"]
        lines += [f"| {f['title']} | {f['error']} |" for f in failed]
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path


def run_import(feature: str) -> int:
    config = load_config()

    feature_dir = OUTPUT_ROOT / feature
    if not feature_dir.is_dir():
        raise ImporterError(f"Feature directory not found: {feature_dir}")
    csv_path = find_csv(feature_dir, feature)

    cases = parse_csv(csv_path)
    print(f"Parsed {len(cases)} test cases from {csv_path.name}")

    # Route Low-priority cases to the dedicated LOW suite; everything else to the
    # default suite. Fail early if Low cases exist but no LOW suite is configured.
    low_cases = [c for c in cases if priority_category(c.priority) in LOW_PRIORITY_CATEGORIES]
    if low_cases and config.suite_id_low is None:
        titles = ", ".join(c.title for c in low_cases[:5])
        more = "" if len(low_cases) <= 5 else f" (+{len(low_cases) - 5} more)"
        raise ImporterError(
            f"CSV has {len(low_cases)} Low-priority case(s) but TESTRAIL_SUITE_ID_LOW "
            f"is not set: {titles}{more}"
        )

    client = TestRailClient(config)
    project = client.get_project(config.project_id)
    priorities = by_name(client.get_priorities())
    types = by_name(client.get_case_types())
    case_fields = client.get_case_fields()
    check_custom_fields(config, case_fields)
    if config.template_id is not None:
        template_ids = {int(t["id"]) for t in client.get_templates()}
        if config.template_id not in template_ids:
            raise ImporterError(f"Configured template id {config.template_id} does not exist.")
    if not config.external_id_available:
        print(f"Note: External ID field '{config.external_id_field}' not found; skipping it.")

    # Map the 'Sub Test Suite(s)' labels to the multi-select field's option ids.
    sub_suite_map: dict[str, int] = {}
    if config.sub_test_suite_available:
        sub_field = next(
            (f for f in case_fields if f.get("system_name") == config.sub_test_suite_field),
            None,
        )
        sub_suite_map = multiselect_option_map(sub_field)
        if not sub_suite_map:
            print(f"Note: Sub Test Suite field '{config.sub_test_suite_field}' has no "
                  "selectable options; its values will be skipped.")
    else:
        print(f"Note: Sub Test Suite field '{config.sub_test_suite_field}' not found; skipping it.")
    unknown_sub_labels: set[str] = set()

    root_name = feature_display_name(feature)
    suites_line = f"default suite {config.suite_id}"
    if low_cases:
        suites_line += f", low-priority suite {config.suite_id_low}"
    print(f"Connected to '{project.get('name')}'. Importing under root section: "
          f"{root_name} ({suites_line})")

    # One SectionTree per target suite, created lazily and cached.
    trees: dict[int, SectionTree] = {}

    def tree_for(suite_id: int) -> SectionTree:
        if suite_id not in trees:
            trees[suite_id] = SectionTree(client, suite_id)
        return trees[suite_id]

    created: list[dict] = []
    failed: list[dict] = []
    cases_by_suite: dict[int, int] = {}

    for case in cases:
        target_suite = (
            config.suite_id_low
            if priority_category(case.priority) in LOW_PRIORITY_CATEGORIES
            else config.suite_id
        )
        try:
            priority_id = map_id(case.priority, priorities, config.default_priority_id, PRIORITY_ALIASES)
            type_id = map_id(case.type, types, config.default_type_id)
            sub_ids: list[int] = []
            if sub_suite_map and case.sub_test_suite:
                sub_ids, unknown = map_sub_test_suites(case.sub_test_suite, sub_suite_map)
                unknown_sub_labels.update(unknown)
            tree = tree_for(target_suite)
            # Everything nests under the feature root section (per suite).
            section_id = tree.resolve([root_name] + split_section(case.section_path))
            payload = build_payload(case, config, priority_id, type_id, sub_ids)
            result = client.add_case(section_id, payload)
            created.append({
                "id": result["id"],
                "title": case.title,
                "priority": case.priority,
                "suite_id": target_suite,
                "section": f"{root_name} / {case.section_path}",
            })
            cases_by_suite[target_suite] = cases_by_suite.get(target_suite, 0) + 1
            print(f"  [created {result['id']} | suite {target_suite}] {case.title}")
        except ImporterError as exc:
            failed.append({"title": case.title, "error": str(exc)})
            print(f"  [FAILED] {case.title}: {exc}", file=sys.stderr)

    if unknown_sub_labels:
        print(
            "Note: unmapped Sub Test Suite label(s) skipped (not options in "
            f"'{config.sub_test_suite_field}'): " + ", ".join(sorted(unknown_sub_labels)),
            file=sys.stderr,
        )

    # Build per-suite summaries in a stable order (default first, then low).
    suite_summaries: list[dict] = []
    for suite_id, label, priorities_label in (
        (config.suite_id, "Default", "Critical, High, Medium"),
        (config.suite_id_low, "Low", "Low"),
    ):
        if suite_id is None or suite_id not in trees and suite_id not in cases_by_suite:
            continue
        suite_summaries.append({
            "label": label,
            "suite_id": suite_id,
            "priorities": priorities_label,
            "sections_created": trees[suite_id].created if suite_id in trees else 0,
            "cases_created": cases_by_suite.get(suite_id, 0),
        })

    total_sections = sum(t.created for t in trees.values())
    report = write_report(
        feature, feature_dir, csv_path, config, project,
        root_name, suite_summaries, total_sections, created, failed,
    )

    print()
    print("TestRail import " + ("completed." if not failed else "completed with errors."))
    print(f"  Sections created: {total_sections}")
    print(f"  Cases created: {len(created)}")
    print(f"  Cases failed: {len(failed)}")
    print(f"  Report: {report}")
    return 0 if not failed else 1


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("-")]
    if len(args) != 1:
        print("Usage: python scripts/testrail_import.py <feature_name>", file=sys.stderr)
        return 2
    try:
        return run_import(args[0])
    except ImporterError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
