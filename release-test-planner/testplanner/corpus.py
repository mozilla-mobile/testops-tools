# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""Stage 3: build an inventory of the existing UI test automation.

Deterministic. Kotlin (Fenix) and Swift (firefox-ios) are parsed by separate
readers behind one interface, because the two languages declare a test
differently but the *evidence* we want out of them is identical: what the test
is called, whether it actually runs, which TestRail case it claims, and which
app surfaces it drives.

  Android  ui/                  legacy robot-DSL tests
           ui/efficiency/tests/ modernised page-object tests
  iOS      XCUITests/           XCUITest classes

Surfaces are the evidence used to bind a test to a feature when the class name
is ambiguous. They come from `on.<pageObject>` and `robots.*` imports on
Android, and from `navigator.goto/nowAt/performAction` - the MappaMundi screen
graph - on iOS. Same idea, same role in coverage.bind().

**"A test exists" is not "a test runs", on either platform.** Android says so
with `@Ignore`; iOS says it in `.xctestplan` files, which list skipped tests per
plan - and they skip a lot of them. A test present in the repo but skipped by
every plan is not coverage, and counting it as coverage is how a release plan
ends up confidently wrong.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Set

CLASS_RE = re.compile(r"^\s*(?:open\s+|abstract\s+)?class\s+(\w+)", re.MULTILINE)
TEST_FN_RE = re.compile(r"\bfun\s+(\w+)\s*\(")
ANNOTATION_RE = re.compile(r"^\s*@(\w+)")
TESTRAIL_RE = re.compile(r"cases/view/(\d+)")
PAGE_OBJECT_RE = re.compile(r"\bon\.(\w+)")
ROBOT_IMPORT_RE = re.compile(r"import\s+org\.mozilla\.fenix\.ui\.robots\.(\w+)")

# Annotations that mean the test does not run in a normal CI pass.
DISABLING = {"Ignore", "Suppress", "Manual"}

# ---- Swift / XCUITest -----------------------------------------------------

SWIFT_CLASS_RE = re.compile(r"^\s*(?:final\s+|open\s+|public\s+)?class\s+(\w+)",
                            re.MULTILINE)
# XCTest identifies a test by convention, not annotation: an instance method
# whose name begins with `test`.
SWIFT_TEST_FN_RE = re.compile(r"^\s*(?:@\w+\s+)*(?:private\s+|public\s+|final\s+)*"
                              r"func\s+(test\w*)\s*\(")
# MappaMundi screen graph: the iOS equivalent of `on.<pageObject>`.
SWIFT_NAV_RE = re.compile(r"navigator\.(?:goto|nowAt)\(\s*([A-Za-z_][\w.]*)")
SWIFT_ACTION_RE = re.compile(r"navigator\.performAction\(\s*Action\.([A-Za-z_]\w*)")
# Skips decided in code rather than in a test plan. `guard #available ... else
# { return }` is the quietest of them: the test reports success having asserted
# nothing, which is the same failure mode as an all-@Ignore'd Android class.
SWIFT_SKIP_RE = re.compile(r"\bXCTSkip(?:If|Unless)?\b|\bskipPlatform\b")
SWIFT_AVAILABILITY_GUARD_RE = re.compile(r"guard\s+#available[^\n]*else\s*\{\s*return")


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
    # Which .xctestplan files run this test. `None` means the platform does not
    # express selection that way (Android); `[]` means every plan skips it,
    # which is dead automation rather than coverage. Conflating those two would
    # mark every Android test disabled.
    plans: Optional[List[str]] = None
    skipped_in_code: bool = False

    @property
    def is_smoke(self) -> bool:
        if "SmokeTest" in self.annotations:
            return True
        return bool(self.plans) and any(p.startswith("Smoketest")
                                        for p in self.plans)

    @property
    def is_disabled(self) -> bool:
        if any(a in DISABLING for a in self.annotations):
            return True
        if self.skipped_in_code:
            return True
        return self.plans is not None and not self.plans


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


def parse_swift_file(path: str, suite: str, repo_root: str) -> List[TestCase]:
    """Parse one XCUITest source file.

    XCTest has no @Test annotation: a test is an instance method whose name
    starts with `test`. The TestRail link is a `//` comment above the method, in
    the same URL form Fenix uses, so the same regex serves both platforms.
    """
    with open(path, errors="replace") as fh:
        src = fh.read()

    rel = os.path.relpath(path, repo_root)
    class_match = SWIFT_CLASS_RE.search(src)
    class_name = (class_match.group(1) if class_match
                  else os.path.basename(path)[: -len(".swift")])

    # Screens reached in setUp or in helpers apply to every test in the file, the
    # same way a robot import does on Android.
    file_surfaces: Set[str] = set()
    lines = src.splitlines()
    cases: List[TestCase] = []
    pending_testrail = ""

    for idx, line in enumerate(lines):
        rail = TESTRAIL_RE.search(line)
        if rail:
            pending_testrail = rail.group(1)
            continue

        fn = SWIFT_TEST_FN_RE.match(line)
        if not fn:
            continue

        body = _test_body(lines, idx)
        clean = _strip_comments(body)
        surfaces = set(SWIFT_NAV_RE.findall(clean))
        surfaces |= {"Action." + a for a in SWIFT_ACTION_RE.findall(clean)}
        surfaces |= file_surfaces

        cases.append(
            TestCase(
                name=fn.group(1),
                class_name=class_name,
                suite=suite,
                file=rel,
                annotations=[],
                testrail_id=pending_testrail,
                surfaces=sorted(surfaces),
                line=idx + 1,
                plans=[],
                skipped_in_code=bool(SWIFT_SKIP_RE.search(clean)
                                     or SWIFT_AVAILABILITY_GUARD_RE.search(clean)),
            )
        )
        pending_testrail = ""

    return cases


def load_test_plans(repo_root: str, plan_root: str,
                    test_target: str = "") -> Dict[str, Dict[str, Set[str]]]:
    """Read .xctestplan files into {plan name: skip/selection sets}.

    Only the target named `test_target` is read. Most plans in firefox-ios do not
    include XCUITests at all - UnitTest.xctestplan lists two dozen unit-test
    targets - and collapsing every target together made those plans look as
    though they ran all 536 UI tests.

    Skip entries take two shapes: `ClassName` skips the whole class, and
    `ClassName/testMethod()` skips one method. Both matter - resolving only the
    method form would silently treat a wholly skipped class as running.
    """
    plans: Dict[str, Dict[str, Set[str]]] = {}
    root = os.path.join(repo_root, plan_root)
    if not os.path.isdir(root):
        return plans

    for entry in sorted(os.listdir(root)):
        if not entry.endswith(".xctestplan"):
            continue
        try:
            with open(os.path.join(root, entry), errors="replace") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue

        targets = [t for t in data.get("testTargets", [])
                   if not test_target
                   or t.get("target", {}).get("name") == test_target]
        if not targets:
            continue        # this plan does not run the UI tests at all

        classes: Set[str] = set()
        tests: Set[str] = set()
        selected: Set[str] = set()
        for target in targets:
            for skipped in target.get("skippedTests", []) or []:
                if "/" in skipped:
                    tests.add(skipped.split("/", 1)[1].rstrip("()"))
                else:
                    classes.add(skipped)
            for chosen in target.get("selectedTests", []) or []:
                selected.add(chosen.split("/", 1)[-1].rstrip("()")
                             if "/" in chosen else chosen)
        plans[entry[: -len(".xctestplan")]] = {
            "skipped_classes": classes,
            "skipped_tests": tests,
            "selected": selected,
        }
    return plans


def _runs_in(plan: Dict[str, Set[str]], case: TestCase) -> bool:
    # A plan with an explicit selection runs only that; otherwise it runs
    # everything except its skip lists.
    if plan["selected"]:
        return case.name in plan["selected"] or case.class_name in plan["selected"]
    if case.class_name in plan["skipped_classes"]:
        return False
    return case.name not in plan["skipped_tests"]


def apply_test_plans(cases: List[TestCase],
                     plans: Dict[str, Dict[str, Set[str]]]) -> None:
    for case in cases:
        if case.plans is None:
            continue
        case.plans = sorted(name for name, plan in plans.items()
                            if _runs_in(plan, case))


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


def build(repo_root: str, platform, tests_root: str = "") -> Dict:
    """Scan the platform's UI suites and return the full test inventory.

    `tests_root` overrides the platform's first test root, for a checkout whose
    layout differs from the current one - firefox-ios moved everything under
    `firefox-ios/` at v106, and old release branches are still flat.
    """
    readers = {".kt": parse_file, ".swift": parse_swift_file}
    reader = readers[platform.extension]

    roots = platform.roots(repo_root)
    if tests_root:
        roots = [(os.path.join(repo_root, tests_root), roots[0][1])] + list(roots[1:])

    cases: List[TestCase] = []
    missing: List[str] = []
    for directory, suite in roots:
        if not os.path.isdir(directory):
            missing.append(os.path.relpath(directory, repo_root))
            continue
        for entry in sorted(os.listdir(directory)):
            if entry.endswith(platform.extension):
                cases += reader(os.path.join(directory, entry), suite, repo_root)

    plans: Dict[str, Dict[str, Set[str]]] = {}
    if platform.test_plan_root:
        plans = load_test_plans(repo_root, platform.test_plan_root,
                                platform.test_target)
        apply_test_plans(cases, plans)

    by_suite: Dict[str, int] = {}
    for c in cases:
        by_suite[c.suite] = by_suite.get(c.suite, 0) + 1

    per_plan = {
        name: sum(1 for c in cases if c.plans and name in c.plans)
        for name in sorted(plans)
    }

    return {
        "platform": platform.id,
        "total_tests": len(cases),
        "by_suite": by_suite,
        "smoke_tests": sum(1 for c in cases if c.is_smoke),
        "disabled_tests": sum(1 for c in cases if c.is_disabled),
        "with_testrail_id": sum(1 for c in cases if c.testrail_id),
        # Empty is the signal that matters: it means the roots below were not
        # found, so "no tests" is a wrong path rather than a bare repo.
        "missing_roots": missing,
        "test_plans": per_plan,
        "tests": [
            dict(
                asdict(c),
                is_smoke=c.is_smoke,
                is_disabled=c.is_disabled,
            )
            for c in cases
        ],
    }
