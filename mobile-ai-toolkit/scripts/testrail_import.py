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
    TESTRAIL_TMP_PROJECT_ID, TESTRAIL_TMP_SUITE_ID            (required)

    TESTRAIL_TMP_SUITE_ID_LOW                             (required only when the CSV
                                                      has Low-priority cases;
                                                      Low cases import here while
                                                      Critical/High/Medium go to
                                                      TESTRAIL_TMP_SUITE_ID)

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
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Shared TestRail integration layer: configuration, the authenticated client,
# retries/pagination, text normalisation, numbered-step parsing, custom-field
# mapping and report building all live there, so the import, fetch and triage
# scripts cannot drift apart.
from testrail_client import (  # noqa: E402  (path set above)
    OUTPUT_ROOT,
    Config,
    TestRailClient,
    TestRailError,
    by_name,
    field_key,
    field_options,
    find_case_field,
    key,
    load_config,
    map_id,
    md_fields,
    md_table,
    norm,
    pair_numbered,
    run_cli,
    write_report,
)


# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

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

def feature_display_name(feature: str) -> str:
    parts = re.split(r"[-_\s]+", feature.strip())
    return " ".join(word.capitalize() for word in parts if word) or feature


def split_section(path: str) -> list[str]:
    """Split a section path on / > :: into its parts."""
    path = re.sub(r"\s*(?:::|>|/)\s*", "/", norm(path))
    return [re.sub(r"\s+", " ", part).strip() for part in path.split("/") if part.strip()]


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
            raise TestRailError(f"Duplicate CSV column: {header}")
        by_norm[normalized] = header

    mapping: dict[str, str] = {}
    for logical, aliases in COLUMN_ALIASES.items():
        # Several aliases can normalize to the same key (e.g. "Preconditions"
        # and "Pre-conditions"); count distinct matched columns only.
        matches = list(dict.fromkeys(by_norm[field_key(a)] for a in aliases if field_key(a) in by_norm))
        if len(matches) > 1:
            raise TestRailError(f"Multiple CSV columns map to '{logical}': {', '.join(matches)}")
        if matches:
            mapping[logical] = matches[0]

    missing = [c for c in REQUIRED_COLUMNS if c not in mapping]
    if missing:
        raise TestRailError("CSV is missing required columns: " + ", ".join(missing))
    return mapping


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
        raise TestRailError(f"No CSV file found in {feature_dir}")
    if len(candidates) > 1:
        raise TestRailError(
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
            raise TestRailError("CSV does not contain a header.")
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

            case.step_pairs = pair_numbered(case.steps, case.expected)
            if not case.step_pairs:
                errors.append(f"Row {row_num}: no steps/expected results.")
                continue
            cases.append(case)

    if errors:
        raise TestRailError("CSV validation failed:\n  - " + "\n  - ".join(errors))
    if not cases:
        raise TestRailError("CSV contains no test cases.")
    return cases


# --------------------------------------------------------------------------- #
# Section builder (feature root + nested structure)
# --------------------------------------------------------------------------- #

class SectionBuilder:
    """Creates the sections a path needs, reusing any that already exist.

    The write-side counterpart to the client's read-only ``section_tree``:
    indexed by (parent_id, name) so a path is only created once per run.
    """

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
    """Fail on missing content fields; record which optional ones exist.

    Only `custom_*` names are checked: a built-in field such as `refs` always
    exists and never appears in get_case_fields.
    """
    def exists(field_name: str) -> bool:
        return (not field_name.startswith("custom_")
                or find_case_field(case_fields, field_name) is not None)

    content_fields = {config.preconditions_field, config.expected_field}
    content_fields.add(config.separated_steps_field if config.use_separated_steps
                       else config.steps_field)
    missing = sorted(f for f in content_fields if not exists(f))
    if missing:
        raise TestRailError(
            "Required TestRail custom fields do not exist: " + ", ".join(missing)
        )

    config.external_id_available = exists(config.external_id_field)
    config.sub_test_suite_available = exists(config.sub_test_suite_field)


# --------------------------------------------------------------------------- #
# Import
# --------------------------------------------------------------------------- #

def write_import_report(feature: str, feature_dir: Path, csv_path: Path,
                        config: Config, project: dict, root_name: str,
                        suite_summaries: list[dict], sections_created: int,
                        created: list[dict], failed: list[dict]) -> Path:
    """The import report, built from the shared markdown helpers."""
    suite_line = ", ".join(
        f"{s['label']} = {s['suite_id']}" for s in suite_summaries
    ) or str(config.suite_id)

    lines = ["# TestRail Import Report", ""]
    lines += md_fields([
        ("Feature", feature),
        ("TestRail URL", config.url),
        ("Project", f"{project.get('name')} (ID {config.project_id})"),
        ("Suites", suite_line),
        ("Root section", root_name),
        ("CSV", csv_path),
        ("Import date", datetime.now().astimezone().isoformat(timespec="seconds")),
        ("Status", "COMPLETED" if not failed else "COMPLETED_WITH_ERRORS"),
    ])

    lines += ["", "## Summary", ""]
    lines += md_table(["Result", "Count"], [
        ["Sections created", sections_created],
        ["Cases created", len(created)],
        ["Cases failed", len(failed)],
    ], aligns="lr")

    lines += ["", "## Per-suite breakdown", ""]
    lines += md_table(
        ["Suite", "Suite ID", "Priorities", "Sections created", "Cases created"],
        [[s["label"], s["suite_id"], s["priorities"],
          s["sections_created"], s["cases_created"]] for s in suite_summaries],
        aligns="lrlrr",
    )

    lines += ["", "## Created cases", ""]
    lines += md_table(
        ["TestRail Case ID", "Title", "Priority", "Suite ID", "Section"],
        [[c["id"], c["title"], c.get("priority", ""), c["suite_id"], c["section"]]
         for c in created],
        aligns="rllrl",
    )

    if failed:
        lines += ["", "## Failed cases", ""]
        lines += md_table(["Title", "Error"],
                          [[f["title"], f["error"]] for f in failed])

    return write_report(feature_dir / "testrail_import_report.md", lines)


def run_import(feature: str) -> int:
    config = load_config()

    feature_dir = OUTPUT_ROOT / feature
    if not feature_dir.is_dir():
        raise TestRailError(f"Feature directory not found: {feature_dir}")
    csv_path = find_csv(feature_dir, feature)

    cases = parse_csv(csv_path)
    print(f"Parsed {len(cases)} test cases from {csv_path.name}")

    # Route Low-priority cases to the dedicated LOW suite; everything else to the
    # default suite. Fail early if Low cases exist but no LOW suite is configured.
    low_cases = [c for c in cases if priority_category(c.priority) in LOW_PRIORITY_CATEGORIES]
    if low_cases and config.suite_id_low is None:
        titles = ", ".join(c.title for c in low_cases[:5])
        more = "" if len(low_cases) <= 5 else f" (+{len(low_cases) - 5} more)"
        raise TestRailError(
            f"CSV has {len(low_cases)} Low-priority case(s) but TESTRAIL_TMP_SUITE_ID_LOW "
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
            raise TestRailError(f"Configured template id {config.template_id} does not exist.")
    if not config.external_id_available:
        print(f"Note: External ID field '{config.external_id_field}' not found; skipping it.")

    # Map the 'Sub Test Suite(s)' labels to the multi-select field's option ids.
    sub_suite_map: dict[str, int] = {}
    if config.sub_test_suite_available:
        sub_field = find_case_field(case_fields, config.sub_test_suite_field)
        sub_suite_map = field_options(sub_field)
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

    # One SectionBuilder per target suite, created lazily and cached.
    trees: dict[int, SectionBuilder] = {}

    def tree_for(suite_id: int) -> SectionBuilder:
        if suite_id not in trees:
            trees[suite_id] = SectionBuilder(client, suite_id)
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
        except TestRailError as exc:
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
    report = write_import_report(
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
    return run_cli(run_import, args[0])


if __name__ == "__main__":
    sys.exit(main(sys.argv))
