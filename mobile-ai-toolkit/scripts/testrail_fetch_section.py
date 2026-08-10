#!/usr/bin/env python3
"""Print the test cases inside a TestRail section, for analysis.

Read-only companion to ``testrail_import.py``. Resolves a section by id or by
name, walks the sub-sections under it, downloads every case, and prints them as
compact plain text on stdout. Nothing is written to disk and nothing in TestRail
is modified.

The output is the input for the ``feature-documenter`` agent.

Usage:
    python3 scripts/testrail_fetch_section.py <section> [--project-id N] [--suite-id N]

    <section>   Section id (e.g. 654483) or section/folder name
                (e.g. "Pull to refresh").

Search target (fixed defaults, overridable per run):

    TESTRAIL_iOS_PROJECT_ID   default 14     — Firefox for iOS
    TESTRAIL_FULL_SUITE_ID    default 45443  — Full Functional Tests Suite

Kept separate from the importer's TESTRAIL_PROJECT_ID / TESTRAIL_SUITE_ID, so
documenting a shipped feature never depends on wherever the last import ran.

Credentials come from the same environment variables as the importer; a local
.env is loaded automatically. The API key is never printed.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from html import unescape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from testrail_import import (  # noqa: E402  (path set above)
    ImporterError,
    TestRailClient,
    key,
    load_config,
    norm,
)

DEFAULT_PROJECT_ID = 14      # Firefox for iOS
DEFAULT_SUITE_ID = 45443     # Full Functional Tests Suite
PROJECT_ENV = "TESTRAIL_iOS_PROJECT_ID"
SUITE_ENV = "TESTRAIL_FULL_SUITE_ID"


def env_int(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    return int(raw) if raw else default


# --------------------------------------------------------------------------- #
# Client
# --------------------------------------------------------------------------- #

class ReaderClient(TestRailClient):
    """TestRailClient plus the two read endpoints the importer does not need."""

    def get_sections_in(self, suite_id: int) -> list[dict]:
        return self._paginated(
            f"get_sections/{self.config.project_id}&suite_id={suite_id}", "sections"
        )

    def get_cases_in(self, suite_id: int, section_id: int) -> list[dict]:
        return self._paginated(
            f"get_cases/{self.config.project_id}&suite_id={suite_id}"
            f"&section_id={section_id}",
            "cases",
        )


# --------------------------------------------------------------------------- #
# Text
# --------------------------------------------------------------------------- #

_LIST_ITEM = re.compile(r"<\s*li[^>]*>", re.IGNORECASE)
_BLOCK = re.compile(r"<\s*/?\s*(?:br|p|div|ul|ol|tr|li)[^>]*>", re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")


def html_to_text(value: str) -> str:
    """Flatten TestRail rich text to plain text; a no-op on plain text.

    Some suites author cases as HTML lists. Left raw, the markup gets quoted as
    if it were UI copy. List items become '- ' bullets, other block tags become
    line breaks, entities are unescaped.
    """
    if not value or "<" not in value:
        return norm(value or "")
    text = _TAG.sub("", _BLOCK.sub("\n", _LIST_ITEM.sub("\n- ", value)))
    text = unescape(text).replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.split("\n")]
    return norm("\n".join(ln for ln in lines if ln and ln != "-"))


def steps_of(case: dict, config) -> list[tuple[str, str]]:
    """Return [(action, expected)] from either the separated or plain format."""
    separated = case.get(config.separated_steps_field)
    if isinstance(separated, list) and separated:
        return [
            (html_to_text(str(s.get("content") or "")),
             html_to_text(str(s.get("expected") or "")))
            for s in separated
        ]

    actions = html_to_text(str(case.get(config.steps_field) or ""))
    expected = html_to_text(str(case.get(config.expected_field) or ""))
    if not actions and not expected:
        return []

    def numbered(text: str) -> dict[int, str]:
        out: dict[int, str] = {}
        current = None
        for line in text.split("\n"):
            match = re.match(r"^\s*(\d+)\s*[\.\):\-]\s*(.*)$", line)
            if match:
                current = int(match.group(1))
                out[current] = match.group(2).strip()
            elif current is not None and line.strip():
                out[current] = f"{out[current]}\n{line.strip()}".strip()
        return out

    acts, exps = numbered(actions), numbered(expected)
    if not acts:
        return [(actions, expected)]
    return [(acts.get(i, ""), exps.get(i, "")) for i in sorted(set(acts) | set(exps))]


# --------------------------------------------------------------------------- #
# Sections
# --------------------------------------------------------------------------- #

def section_tree(sections: list[dict]) -> dict[int, dict]:
    """Index sections by id, attaching a full '/'-joined path to each."""
    index = {int(s["id"]): dict(s) for s in sections}
    for section in index.values():
        parts, cursor, guard = [], section, 0
        while cursor is not None and guard < 50:
            parts.append(cursor.get("name", ""))
            parent = cursor.get("parent_id")
            cursor = index.get(int(parent)) if parent else None
            guard += 1
        section["path"] = " / ".join(reversed(parts))
    return index


def resolve(index: dict[int, dict], wanted: str) -> dict:
    """Find the requested section: by id, then exact name, then substring."""
    wanted = wanted.strip()
    if wanted.isdigit() and int(wanted) in index:
        return index[int(wanted)]

    target = key(wanted)
    exact = [s for s in index.values() if key(s.get("name", "")) == target]
    found = exact or [s for s in index.values() if target in key(s.get("name", ""))]

    if not found:
        raise ImporterError(f"Section '{wanted}' was not found.")
    if len(found) > 1:
        names = ", ".join(f"{s['name']} (id {s['id']})" for s in found)
        raise ImporterError(
            f"Section '{wanted}' is ambiguous: {names}. Re-run with the section id."
        )
    return found[0]


def descendants(index: dict[int, dict], root_id: int) -> list[dict]:
    """The root plus every section beneath it, parents before children."""
    children: dict[int, list[dict]] = {}
    for section in index.values():
        if section.get("parent_id") is not None:
            children.setdefault(int(section["parent_id"]), []).append(section)
    ordered, stack = [], [index[root_id]]
    while stack:
        current = stack.pop(0)
        ordered.append(current)
        kids = sorted(children.get(int(current["id"]), []),
                      key=lambda s: (s.get("display_order") or 0, s.get("name") or ""))
        stack = kids + stack
    return ordered


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def run(args) -> int:
    config = load_config()
    config.project_id = args.project_id or env_int(PROJECT_ENV, DEFAULT_PROJECT_ID)
    suite_id = args.suite_id or env_int(SUITE_ENV, DEFAULT_SUITE_ID)

    client = ReaderClient(config)
    project = client.get_project(config.project_id)
    suite = client.get_suite(suite_id)
    if suite.get("project_id") not in (None, config.project_id):
        raise ImporterError(
            f"Suite {suite_id} belongs to project {suite.get('project_id')}, "
            f"not {config.project_id}. Check {PROJECT_ENV} / {SUITE_ENV}."
        )

    index = section_tree(client.get_sections_in(suite_id))
    root = resolve(index, args.section)
    tree = descendants(index, int(root["id"]))
    root_path = root.get("path") or root["name"]

    priorities = {int(p["id"]): p["name"] for p in client.get_priorities()}
    types = {int(t["id"]): t["name"] for t in client.get_case_types()}

    out: list[str] = []
    total = 0
    for section in tree:
        cases = client.get_cases_in(suite_id, int(section["id"]))
        if not cases:
            continue
        full = section.get("path") or section["name"]
        rel = full[len(root_path):].strip(" /") if full.startswith(root_path) else full
        out.append(f"\n## {rel or root['name']}  ({len(cases)} cases)")
        for case in cases:
            total += 1
            head = (f"\n### C{case['id']} | {priorities.get(case.get('priority_id'), '?')}"
                    f" | {types.get(case.get('type_id'), '?')}"
                    f" | {html_to_text(str(case.get('title') or ''))}")
            out.append(head)
            pre = html_to_text(str(case.get(config.preconditions_field) or ""))
            if pre:
                out.append(f"Preconditions: {pre}")
            refs = norm(str(case.get(config.references_field) or ""))
            if refs:
                out.append(f"Refs: {refs}")
            for i, (action, expected) in enumerate(steps_of(case, config), start=1):
                out.append(f"{i}. {action or '(empty)'}")
                out.append(f"   -> {expected or '(NO EXPECTED RESULT)'}")

    print(f"# {root['name']} (section {root['id']})")
    print(f"# project {config.project_id} \"{project.get('name')}\" / "
          f"suite {suite_id} \"{suite.get('name')}\"")
    print(f"# {total} cases in {len(tree)} sections")
    print("\n".join(out))
    if not total:
        print("\n! The section resolved but contains no test cases.", file=sys.stderr)
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Print a TestRail section's test cases as plain text (read-only)."
    )
    parser.add_argument("section", help="Section id or section/folder name.")
    parser.add_argument("--project-id", type=int,
                        help=f"Override {PROJECT_ENV} (default {DEFAULT_PROJECT_ID}).")
    parser.add_argument("--suite-id", type=int,
                        help=f"Override {SUITE_ENV} (default {DEFAULT_SUITE_ID}).")
    args = parser.parse_args(argv)
    try:
        return run(args)
    except ImporterError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
