"""
TestRail index for Firefox Android.

Builds the code <-> test-case mapping from two independent sources and
reconciles them:

  1. **The TestRail export** — the `Automated Test Name(s)` column, in
     `ui/OnboardingTest#verifyTheTermsOfUseOnboardingCardTest` form, on
     roughly two cases in five.

  2. **The repo itself** — `// TestRail link: https://mozilla.testrail.io/
     index.php?/cases/view/2833690` comments above the `@Test` methods in
     `mobile/android/fenix/app/src/androidTest/`.

Neither source is trustworthy alone. Together they cover appreciably more
cases than either does, and they cross-check each other: the overlap confirms
both, and the disagreements are the drift signal — reported in `IndexDrift`
rather than silently reconciled. The commonest disagreement is an export entry
whose `Class#method` no longer exists in the repo (stale names such as
`ComposeBookmarksTest`, renamed to `BookmarksTest`).

`python3 -m android.calibrate` prints the current coverage and drift counts.
Do not trust a figure written in a docstring here: the export ages against the
tree between re-exports, and a stale export shows up as false drift.

The export's `Automation` column is the signal iOS never had, and it is almost
perfectly consistent with the mapping — nearly every `Completed` case is
mapped to code and no `Unsuitable` one is — so it partitions the catalogue
directly into:

  Completed / Disabled  -> already automated; deprioritize for manual runs
  Unsuitable            -> manual-only forever; the core manual regression pool
  Suitable              -> automatable but not yet; feeds "automation to add"
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


# =============================================================================
# Constants
# =============================================================================


ANDROID_TEST_ROOT = "mobile/android/fenix/app/src/androidTest"
"""Instrumented (on-device) tests. Unit tests under `src/test/` are not linked
to TestRail cases and are excluded."""

# `// TestRail link: https://mozilla.testrail.io/index.php?/cases/view/2833690`
CASE_LINK_RE = re.compile(r"cases/view/(\d+)")

# `ui/OnboardingTest#verifyTheTermsOfUseOnboardingCardTest`, tolerating the
# `http://` that TestRail's editor prepends and a bare `Class#method`.
# The class segment must start uppercase (Kotlin convention) but must NOT be
# required to end in `Test`: `ui/MainMenuTestCompose#...` is a real value, and
# an earlier `...Test#` anchor silently dropped 52 cells.
QUALIFIED_TEST_RE = re.compile(r"(?:[A-Za-z0-9_.]+/)*([A-Z][A-Za-z0-9_]*)#([A-Za-z0-9_]+)")

# Some cells contain pasted rich text; strip tags before matching.
HTML_TAG_RE = re.compile(r"<[^>]+>")

KOTLIN_FUN_RE = re.compile(r"^\s*fun\s+([A-Za-z0-9_]+)\s*\(", re.MULTILINE)
TEST_ANNOTATION_RE = re.compile(r"^\s*@Test\b", re.MULTILINE)

# Any `fun` declaration, including ones KOTLIN_FUN_RE cannot name. Needed to
# stop a malformed declaration from leaking its pending TestRail links onto the
# next well-formed method: a working tree containing `fun () {` silently moved
# case 2348374 from `verifyFirefoxSuggestNonSponsoredSearchResultsTest` to the
# method below it.
ANY_FUN_RE = re.compile(r"^\s*(?:(?:private|internal|public|protected|suspend|inline|open|override)\s+)*fun\b")

AUTOMATED_STATES = frozenset({"Completed", "Disabled"})
"""`Automation` values meaning the case has a corresponding automated test.
`Disabled` counts: the test exists but is currently skipped, which is itself
worth surfacing when its area changes."""


# =============================================================================
# Data models
# =============================================================================


@dataclass
class TestCase:
    """One TestRail case from the export."""
    case_id: str                       # digits only, no "C" prefix
    title: str
    section_hierarchy: str
    priority: str
    automation: str                    # Completed | Suitable | Unsuitable | ...
    automation_coverage: str           # Full | Partial | None
    case_type: str                     # Functional | Smoke | Other
    labels: str
    # Class#method pairs parsed out of `Automated Test Name(s)`.
    declared_tests: list[tuple[str, str]] = field(default_factory=list)
    # The same cell, cleaned — kept so build_index() can tell "empty" apart
    # from "had content we could not parse".
    declared_raw: str = ""

    @property
    def is_automated(self) -> bool:
        return self.automation in AUTOMATED_STATES

    @property
    def is_manual_only(self) -> bool:
        return self.automation == "Unsuitable"

    @property
    def is_automation_gap(self) -> bool:
        """Suitable for automation but not yet automated — the input to the
        report's "automated regression to add" section."""
        return self.automation == "Suitable"

    @property
    def section_parts(self) -> list[str]:
        """The section hierarchy split into levels.

        Splitting naively on `>` corrupts the two sections whose own name
        contains one: `Accounts & Sync > [Android > 14] Send tabs through
        native share sheet` truncates to `Accounts & Sync > [Android`, and
        `[Android > 14] Native share sheet options` loses its head entirely.
        Bracketed spans are therefore treated as atomic.
        """
        return split_hierarchy(self.section_hierarchy)

    def section_at(self, depth: int) -> str:
        """The section hierarchy truncated to `depth` levels.

        Depth 2 is the useful granularity for Android: at depth 1 `Menus`
        alone holds roughly a third of the catalogue, while depth 2 splits it
        into `Menus > Settings menu` and `Menus > Menu Redesign 2025`. For
        mapping, `build_mapping.assign_section_keys()` goes deeper where a
        bucket is still too coarse.
        """
        return " > ".join(self.section_parts[:depth])


@dataclass
class TestMethod:
    """An `@Test` method found in the repo."""
    class_name: str
    method: str
    path: str                          # repo-relative
    case_ids: list[str] = field(default_factory=list)

    @property
    def qualified(self) -> tuple[str, str]:
        return (self.class_name, self.method)


@dataclass
class IndexDrift:
    """Disagreements between the export and the repo. Each is actionable."""
    # Case IDs referenced by a `// TestRail link:` that are not in the export.
    orphan_links: list[str] = field(default_factory=list)
    # `Class#method` in the export that no longer exists in the repo.
    stale_declared: list[tuple[str, str, str]] = field(default_factory=list)
    # Test methods carrying a TestRail link whose case says it is not automated.
    automation_status_mismatch: list[tuple[str, str]] = field(default_factory=list)
    # `Automated Test Name(s)` cells with content that yields no Class#method.
    # Seen in the current export: preconditions prose pasted into the column.
    unparseable_declared: list[tuple[str, str]] = field(default_factory=list)
    # `(path, line)` for an `@Test` whose declaration could not be parsed. Any
    # TestRail links above it are dropped, so this is a coverage hole — usually
    # a broken working tree rather than a real repo state.
    malformed_methods: list[tuple[str, str]] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return not (self.orphan_links or self.stale_declared
                    or self.automation_status_mismatch
                    or self.unparseable_declared
                    or self.malformed_methods)


@dataclass
class TestRailIndex:
    cases: dict[str, TestCase]
    methods: list[TestMethod]
    drift: IndexDrift
    # case_id -> repo-relative test file paths implementing it.
    case_to_files: dict[str, set[str]] = field(default_factory=dict)
    # repo-relative test file -> case_ids it implements.
    file_to_cases: dict[str, set[str]] = field(default_factory=dict)

    def cases_for_files(self, paths: Iterable[str]) -> set[str]:
        """Exact match: which cases do these changed test files implement?

        This is the Android analogue of iOS step 6 — the highest-confidence
        signal in the pipeline, since it involves no inference at all.
        """
        out: set[str] = set()
        for p in paths:
            out |= self.file_to_cases.get(p, set())
        return out

    def by_section(self, depth: int = 2) -> dict[str, list[TestCase]]:
        grouped: dict[str, list[TestCase]] = {}
        for case in self.cases.values():
            grouped.setdefault(case.section_at(depth), []).append(case)
        return grouped


# =============================================================================
# Export parsing
# =============================================================================


def split_hierarchy(hierarchy: str) -> list[str]:
    """Split a TestRail `Section Hierarchy` on `>`, ignoring separators inside
    brackets.

    TestRail joins levels with ` > ` but does not escape the character, and
    Android section names use it for platform gates (`[Android > 14] ...`).
    Depth tracking keeps those spans intact; `<` needs no handling since it
    never collides with the separator.
    """
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    for char in hierarchy:
        if char in "[(":
            depth += 1
        elif char in "])":
            depth = max(0, depth - 1)
        if char == ">" and depth == 0:
            parts.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    parts.append("".join(current).strip())
    return [p for p in parts if p]


def _clean_cell(value: object) -> str:
    """Normalize an xlsx cell: strip HTML, unescape entities, collapse space."""
    if value is None:
        return ""
    text = HTML_TAG_RE.sub("", str(value))
    text = html.unescape(text).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def parse_declared_tests(cell: object) -> list[tuple[str, str]]:
    """Extract `(ClassName, method)` pairs from an `Automated Test Name(s)` cell.

    Handles the three shapes seen in the current export: a bare
    `ui/OnboardingTest#method`, an `http://`-prefixed variant (39 cells), and
    pasted rich text wrapped in `<span style=...>` (4 cells). Any leading path
    is dropped — the class name alone identifies the file.
    """
    text = _clean_cell(cell)
    pairs: list[tuple[str, str]] = []
    for m in QUALIFIED_TEST_RE.finditer(text):
        pair = (m.group(1), m.group(2))
        if pair not in pairs:
            pairs.append(pair)
    return pairs


def load_export(path: str | Path) -> dict[str, TestCase]:
    """Read a TestRail xlsx export into `{case_id: TestCase}`.

    Column lookup is by header name so added/reordered columns are harmless;
    the Android export currently carries 47 columns, of which 8 are read.
    """
    import openpyxl  # imported lazily: only the export path needs it

    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]
    rows = ws.iter_rows(values_only=True)
    header = [(_clean_cell(h) or None) for h in next(rows)]
    idx = {name: i for i, name in enumerate(header) if name}

    required = ["ID", "Title", "Section Hierarchy"]
    missing = [c for c in required if c not in idx]
    if missing:
        raise ValueError(
            f"TestRail export {path} is missing required column(s): {missing}. "
            f"Re-export with the full column set."
        )

    def cell(row: tuple, name: str) -> str:
        i = idx.get(name)
        if i is None or i >= len(row):
            return ""
        return _clean_cell(row[i])

    cases: dict[str, TestCase] = {}
    for row in rows:
        raw_id = cell(row, "ID")
        m = re.match(r"^C?(\d+)$", raw_id)
        if not m:
            continue
        case_id = m.group(1)
        declared_col = idx.get("Automated Test Name(s)")
        declared_cell = (
            row[declared_col]
            if declared_col is not None and declared_col < len(row) else None
        )
        cases[case_id] = TestCase(
            case_id=case_id,
            title=cell(row, "Title"),
            section_hierarchy=cell(row, "Section Hierarchy"),
            priority=cell(row, "Priority"),
            automation=cell(row, "Automation"),
            automation_coverage=cell(row, "Automation Coverage"),
            case_type=cell(row, "Type"),
            labels=cell(row, "Labels"),
            declared_tests=parse_declared_tests(declared_cell),
            declared_raw=_clean_cell(declared_cell),
        )
    wb.close()
    return cases


# =============================================================================
# Repo scanning
# =============================================================================


def scan_test_methods(
    repo: str | Path,
    test_root: str = ANDROID_TEST_ROOT,
    malformed: list[tuple[str, str]] | None = None,
) -> list[TestMethod]:
    """Find every `@Test` method under `test_root` and the case IDs linked to it.

    A `// TestRail link:` comment applies to the next `@Test` method below it,
    so the file is walked top-to-bottom accumulating pending case IDs. A case
    can legitimately be linked from several methods, and a method can carry
    several links.

    `malformed`, if given, collects `(path, line)` for every `@Test` whose
    declaration could not be read. Those are reported rather than skipped
    quietly, because the links they carried are dropped.
    """
    root = Path(repo) / test_root
    methods: list[TestMethod] = []
    if malformed is None:
        malformed = []
    if not root.is_dir():
        return methods

    for file in sorted(root.rglob("*.kt")):
        text = file.read_text(encoding="utf-8", errors="ignore")
        if not TEST_ANNOTATION_RE.search(text):
            continue
        rel = str(file.relative_to(Path(repo)))
        class_name = file.stem
        pending: list[str] = []
        saw_test_annotation = False

        for line in text.splitlines():
            stripped = line.strip()
            link = CASE_LINK_RE.search(stripped)
            if link and stripped.startswith(("//", "*", "/*")):
                pending.append(link.group(1))
                continue
            if stripped.startswith("@Test"):
                saw_test_annotation = True
                continue
            fun = KOTLIN_FUN_RE.match(line)
            if fun and saw_test_annotation:
                methods.append(TestMethod(
                    class_name=class_name,
                    method=fun.group(1),
                    path=rel,
                    case_ids=list(dict.fromkeys(pending)),
                ))
                pending = []
                saw_test_annotation = False
            elif fun:
                # A helper function between the link comment and its @Test
                # would otherwise swallow the pending IDs; keep them.
                continue
            elif saw_test_annotation and ANY_FUN_RE.match(line):
                # An `@Test` whose declaration we cannot read — malformed
                # source, or a Kotlin form this parser does not know. Drop the
                # pending links instead of letting them land on the next
                # readable method, which would silently mis-attribute them.
                malformed.append((rel, line.strip()[:80]))
                pending = []
                saw_test_annotation = False
    return methods


# =============================================================================
# Index construction
# =============================================================================


def build_index(
    export_path: str | Path,
    repo: str | Path,
    test_root: str = ANDROID_TEST_ROOT,
) -> TestRailIndex:
    """Load both sources, join them, and report their disagreements."""
    cases = load_export(export_path)
    malformed: list[tuple[str, str]] = []
    methods = scan_test_methods(repo, test_root, malformed=malformed)

    by_qualified: dict[tuple[str, str], TestMethod] = {
        m.qualified: m for m in methods
    }
    class_to_paths: dict[str, set[str]] = {}
    for m in methods:
        class_to_paths.setdefault(m.class_name, set()).add(m.path)

    case_to_files: dict[str, set[str]] = {}
    file_to_cases: dict[str, set[str]] = {}
    drift = IndexDrift(malformed_methods=malformed)

    def link(case_id: str, path: str) -> None:
        case_to_files.setdefault(case_id, set()).add(path)
        file_to_cases.setdefault(path, set()).add(case_id)

    # Source 1: `// TestRail link:` comments in the repo.
    for m in methods:
        for case_id in m.case_ids:
            if case_id not in cases:
                if case_id not in drift.orphan_links:
                    drift.orphan_links.append(case_id)
                continue
            link(case_id, m.path)
            if not cases[case_id].is_automated:
                entry = (case_id, cases[case_id].automation)
                if entry not in drift.automation_status_mismatch:
                    drift.automation_status_mismatch.append(entry)

    # Source 2: the export's `Automated Test Name(s)` column.
    for case in cases.values():
        if case.declared_raw and not case.declared_tests:
            drift.unparseable_declared.append((case.case_id, case.declared_raw[:120]))
        for class_name, method in case.declared_tests:
            found = by_qualified.get((class_name, method))
            if found:
                link(case.case_id, found.path)
                continue
            # The method is gone. Still map to the class file if it survives,
            # so a renamed method does not lose the whole case.
            paths = class_to_paths.get(class_name)
            if paths:
                for p in paths:
                    link(case.case_id, p)
            drift.stale_declared.append((case.case_id, class_name, method))

    return TestRailIndex(
        cases=cases,
        methods=methods,
        drift=drift,
        case_to_files=case_to_files,
        file_to_cases=file_to_cases,
    )
