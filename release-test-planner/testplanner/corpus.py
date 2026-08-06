# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""Stage 3: build an inventory of the existing UI test automation.

Deterministic. Parses the Kotlin androidTest sources for both suites:

  ui/                  legacy robot-DSL tests
  ui/efficiency/tests/ modernised page-object tests

For each @Test we record its annotations, TestRail id, and the app surfaces it
drives. Surfaces come from `on.<pageObject>` in the efficiency suite and from
`org.mozilla.fenix.ui.robots.*` imports in the legacy suite; they are the
evidence used to bind a test to a feature when the class name is ambiguous.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Set

CLASS_RE = re.compile(r"^\s*(?:open\s+|abstract\s+)?class\s+(\w+)", re.MULTILINE)
TEST_FN_RE = re.compile(r"\bfun\s+(\w+)\s*\(")
ANNOTATION_RE = re.compile(r"^\s*@(\w+)")
TESTRAIL_RE = re.compile(r"cases/view/(\d+)")
PAGE_OBJECT_RE = re.compile(r"\bon\.(\w+)")
ROBOT_IMPORT_RE = re.compile(r"import\s+org\.mozilla\.fenix\.ui\.robots\.(\w+)")

# Annotations that mean the test does not run in a normal CI pass.
DISABLING = {"Ignore", "Suppress", "Manual"}


@dataclass
class TestCase:
    name: str
    class_name: str
    suite: str
    file: str
    annotations: List[str] = field(default_factory=list)
    testrail_id: str = ""
    surfaces: List[str] = field(default_factory=list)
    line: int = 0

    @property
    def is_smoke(self) -> bool:
        return "SmokeTest" in self.annotations

    @property
    def is_disabled(self) -> bool:
        return any(a in DISABLING for a in self.annotations)


def _strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", src)


def parse_file(path: str, suite: str, repo_root: str) -> List[TestCase]:
    with open(path, errors="replace") as fh:
        src = fh.read()

    rel = os.path.relpath(path, repo_root)
    class_match = CLASS_RE.search(src)
    class_name = class_match.group(1) if class_match else os.path.basename(path)[:-3]

    file_surfaces: Set[str] = set(ROBOT_IMPORT_RE.findall(src))

    lines = src.splitlines()
    cases: List[TestCase] = []

    pending_annotations: List[str] = []
    pending_testrail = ""

    for idx, line in enumerate(lines):
        stripped = line.strip()

        rail = TESTRAIL_RE.search(stripped)
        if rail:
            pending_testrail = rail.group(1)
            continue

        ann = ANNOTATION_RE.match(line)
        if ann:
            pending_annotations.append(ann.group(1))
            continue

        if "Test" not in pending_annotations:
            # Reset the TestRail hint if we drift past a non-annotated block.
            if stripped and not stripped.startswith("@") and not stripped.startswith("*"):
                if not stripped.startswith("fun "):
                    pending_annotations = []
                    pending_testrail = ""
            continue

        fn = TEST_FN_RE.search(line)
        if not fn:
            continue

        body = _test_body(lines, idx)
        surfaces = set(PAGE_OBJECT_RE.findall(_strip_comments(body)))
        surfaces |= file_surfaces

        cases.append(
            TestCase(
                name=fn.group(1),
                class_name=class_name,
                suite=suite,
                file=rel,
                annotations=sorted(set(pending_annotations)),
                testrail_id=pending_testrail,
                surfaces=sorted(surfaces),
                line=idx + 1,
            )
        )
        pending_annotations = []
        pending_testrail = ""

    return cases


def _test_body(lines: List[str], start: int, max_lines: int = 120) -> str:
    """Grab the body of the test function starting at `start` by brace depth."""
    depth = 0
    seen_open = False
    out = []
    for line in lines[start : start + max_lines]:
        out.append(line)
        depth += line.count("{") - line.count("}")
        if "{" in line:
            seen_open = True
        if seen_open and depth <= 0:
            break
    return "\n".join(out)


def build(repo_root: str, fenix_test_root: str) -> Dict:
    """Scan both UI suites and return the full test inventory."""
    legacy_dir = os.path.join(repo_root, fenix_test_root)
    efficiency_dir = os.path.join(legacy_dir, "efficiency", "tests")

    cases: List[TestCase] = []

    for entry in sorted(os.listdir(legacy_dir)):
        if entry.endswith(".kt"):
            cases += parse_file(os.path.join(legacy_dir, entry), "ui", repo_root)

    if os.path.isdir(efficiency_dir):
        for entry in sorted(os.listdir(efficiency_dir)):
            if entry.endswith(".kt"):
                cases += parse_file(
                    os.path.join(efficiency_dir, entry), "ui.efficiency", repo_root
                )

    by_suite: Dict[str, int] = {}
    for c in cases:
        by_suite[c.suite] = by_suite.get(c.suite, 0) + 1

    return {
        "total_tests": len(cases),
        "by_suite": by_suite,
        "smoke_tests": sum(1 for c in cases if c.is_smoke),
        "disabled_tests": sum(1 for c in cases if c.is_disabled),
        "with_testrail_id": sum(1 for c in cases if c.testrail_id),
        "tests": [
            dict(
                asdict(c),
                is_smoke=c.is_smoke,
                is_disabled=c.is_disabled,
            )
            for c in cases
        ],
    }
