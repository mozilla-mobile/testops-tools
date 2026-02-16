#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

TEST_FUNC_RE = re.compile(r"^\s*func\s+(test[A-Za-z0-9_]+)\s*\(")

# Accept both:
#   // Smoketest TAE
#   // Smoke TAE
SMOKE_RE = re.compile(r"^\s*//\s*smoke(test)?\b.*$", re.IGNORECASE)

# Patterns to ignore (both as directory names and file prefixes)
IGNORED_PATTERNS = {
    "A11y",
    "ExperimentIntegrationTests",
    "PerformanceTests",
}

# Specific file names to ignore
IGNORED_FILES = {
    "SiteLoadTest.swift",
    "ScreenGraphTest.swift",
}


@dataclass(frozen=True)
class MissingLink:
    file: Path
    line_no: int
    test_name: str
    prev1: str
    prev2: str


def is_testrail_url_line(line: str, testrail_domain: str | None) -> bool:
    s = line.strip()
    if not s:
        return False
    if testrail_domain:
        return ("http://" in s or "https://" in s) and (testrail_domain in s)
    return ("http://" in s or "https://" in s) and ("testrail" in s.lower())


def is_linked(lines: list[str], func_idx: int, testrail_domain: str | None) -> bool:
    """
    Rules:
      1) If prev1 is empty => missing
      2) If prev1 is a TestRail URL => linked
      3) If prev1 is // Smoke... or // Smoketest... => linked iff prev2 is TestRail URL
      4) Otherwise => missing
    """
    if func_idx == 0:
        return False

    prev1 = lines[func_idx - 1]

    if prev1.strip() == "":
        return False

    if is_testrail_url_line(prev1, testrail_domain):
        return True

    if SMOKE_RE.match(prev1):
        if func_idx < 2:
            return False
        prev2 = lines[func_idx - 2]
        return is_testrail_url_line(prev2, testrail_domain)

    return False


def should_ignore_file(path: Path) -> bool:
    # Ignore specific file names
    if path.name in IGNORED_FILES:
        return True

    # Ignore files by prefix or directories by name
    for pattern in IGNORED_PATTERNS:
        # Check if filename starts with pattern
        if path.name.startswith(pattern):
            return True
        # Check if any directory in path matches pattern
        if pattern in path.parts:
            return True

    return False


def scan_file(path: Path, testrail_domain: str | None, debug: bool) -> tuple[int, list[MissingLink]]:
    if should_ignore_file(path):
        return 0, []

    missing: list[MissingLink] = []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()

    found_tests = 0

    for i, line in enumerate(lines):
        m = TEST_FUNC_RE.match(line)
        if not m:
            continue

        found_tests += 1
        test_name = m.group(1)

        prev1 = lines[i - 1].rstrip() if i > 0 else "<start of file>"
        prev2 = lines[i - 2].rstrip() if i > 1 else "<start of file>"

        linked = is_linked(lines, i, testrail_domain)

        if debug:
            verdict = "LINKED" if linked else "MISSING"
            print(f"[{verdict}] {path}:{i+1} {test_name}")
            print(f"  prev1: {prev1.strip() or '<empty>'}")
            print(f"  prev2: {prev2.strip() or '<empty>'}")

        if not linked:
            missing.append(
                MissingLink(
                    file=path,
                    line_no=i + 1,
                    test_name=test_name,
                    prev1=prev1,
                    prev2=prev2,
                )
            )

    return found_tests, missing


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Detect Swift XCUITests missing a TestRail URL above the test function."
    )
    ap.add_argument("--root", required=True)
    ap.add_argument("--testrail-domain", default=None)
    ap.add_argument("--fail", action="store_true")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    root = Path(args.root)
    if not root.exists():
        print(f"ERROR: root does not exist: {root}", file=sys.stderr)
        return 2

    swift_files = sorted(root.rglob("*.swift"))

    total_tests = 0
    all_missing: list[MissingLink] = []

    for f in swift_files:
        found, missing = scan_file(f, args.testrail_domain, args.debug)
        total_tests += found
        all_missing.extend(missing)

    print(f"\nScanned {len(swift_files)} Swift files, found {total_tests} tests.")

    if not all_missing:
        print("✅ No missing TestRail URLs found.")
        return 0

    print(f"\n❌ Found {len(all_missing)} tests missing TestRail URLs:\n")
    for item in all_missing:
        p1 = item.prev1.strip() or "<empty>"
        p2 = item.prev2.strip() or "<empty>"
        print(f"- {item.file}:{item.line_no}  {item.test_name}")
        print(f"  prev1: {p1}")
        print(f"  prev2: {p2}")

    return 1 if args.fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
