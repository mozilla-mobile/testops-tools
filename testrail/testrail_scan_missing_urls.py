#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
import requests
from typing import Iterator

# Swift: func testName()
SWIFT_TEST_FUNC_RE = re.compile(r"^\s*func\s+(test[A-Za-z0-9_]+)\s*\(")

# Kotlin: fun testName() or @Test annotation
KOTLIN_TEST_FUNC_RE = re.compile(r"^\s*fun\s+(test[A-Za-z0-9_]+)\s*\(")
KOTLIN_TEST_ANNOTATION_RE = re.compile(r"^\s*@Test\b")

# Accept both:
#   // Smoketest TAE
#   // Smoke TAE
SMOKE_RE = re.compile(r"^\s*//\s*smoke(test)?\b.*$", re.IGNORECASE)

# Directories to ignore entirely (iOS)
IOS_IGNORED_DIRS = {
    "ExperimentIntegrationTests",
    "PerformanceTests",
}

# Specific files to ignore (iOS)
IOS_IGNORED_FILES = {
    "ScreenGraphTest.swift",
    "SiteLoadTest.swift",
}

# Directories to ignore entirely (Android)
ANDROID_IGNORED_DIRS = set()


@dataclass(frozen=True)
class SearchfoxFile:
    """Represents a file fetched from searchfox"""
    name: str
    url: str
    content: str

    @property
    def path(self) -> Path:
        """Return a Path-like object for compatibility"""
        return Path(self.name)


@dataclass(frozen=True)
class MissingLink:
    file: Path | SearchfoxFile
    line_no: int
    test_name: str
    prev1: str
    prev2: str


# ===============================
# SEARCHFOX HELPERS
# ===============================

def is_searchfox_url(url: str) -> bool:
    """Check if a URL is a searchfox URL"""
    return "searchfox.org" in url


def parse_searchfox_url(url: str) -> tuple[str, str, str]:
    """
    Parse a searchfox URL to extract repo, branch, and path
    Example: https://searchfox.org/firefox-main/source/mobile/android/fenix/...
    Returns: (repo, branch, path)
    """
    parsed = urlparse(url)
    parts = parsed.path.strip("/").split("/")

    if len(parts) < 3:
        raise ValueError(f"Invalid searchfox URL: {url}")

    repo = parts[0]  # e.g., "firefox-main"
    source_or_raw = parts[1]  # "source" or "raw"
    path = "/".join(parts[2:])  # rest of the path

    return repo, source_or_raw, path


def get_searchfox_file_list(base_url: str, file_pattern: str) -> list[str]:
    """
    Fetch list of files from searchfox directory page
    Returns list of filenames matching the pattern
    """
    response = requests.get(base_url, timeout=30)
    response.raise_for_status()

    html = response.text

    # Extract filenames from searchfox HTML
    # Searchfox structure: <a href="/path/to/file.kt">file.kt</a>
    filenames = []

    # Pattern to match file links in searchfox
    # Example: <a href="...CustomTabsTest.kt">CustomTabsTest.kt</a>
    # Capture the filename from the href attribute
    if file_pattern == "*Test.kt":
        # Match any .kt file ending with "Test.kt"
        file_link_re = re.compile(r'<a[^>]*href="[^"]*?/([^/"]+Test\.kt)"')
    elif file_pattern == "*.swift":
        # Match any .swift file
        file_link_re = re.compile(r'<a[^>]*href="[^"]*?/([^/"]+\.swift)"')
    else:
        # Generic pattern
        file_link_re = re.compile(r'<a[^>]*href="[^"]*?/([^/"]+)"')

    for match in file_link_re.finditer(html):
        filename = match.group(1)
        filenames.append(filename)

    # Remove duplicates and sort
    return sorted(set(filenames))


def fetch_searchfox_file(base_url: str, filename: str) -> SearchfoxFile:
    """
    Fetch a single file from searchfox
    Uses GitHub mirror since searchfox doesn't have direct raw file access
    """
    # Extract path from searchfox URL
    # Example: https://searchfox.org/firefox-main/source/mobile/android/fenix/...
    # We need to extract the path after /source/

    if "/source/" in base_url:
        path = base_url.split("/source/", 1)[1]
    else:
        raise ValueError(f"Cannot parse searchfox URL: {base_url}")

    # Construct GitHub raw URL
    # GitHub mirror: https://raw.githubusercontent.com/mozilla-firefox/firefox/main/{path}
    github_raw_base = "https://raw.githubusercontent.com/mozilla-firefox/firefox/main"
    file_url = f"{github_raw_base}/{path}/{filename}"

    response = requests.get(file_url, timeout=30)
    response.raise_for_status()

    return SearchfoxFile(
        name=filename,
        url=file_url,
        content=response.text
    )


def get_searchfox_files(base_url: str, file_pattern: str) -> Iterator[SearchfoxFile]:
    """
    Generator that yields SearchfoxFile objects from a searchfox directory
    """
    print(f"Fetching file list from searchfox: {base_url}")
    filenames = get_searchfox_file_list(base_url, file_pattern)
    print(f"Found {len(filenames)} files matching pattern '{file_pattern}'")

    for filename in filenames:
        try:
            print(f"Downloading: {filename}")
            yield fetch_searchfox_file(base_url, filename)
        except Exception as e:
            print(f"Warning: Failed to fetch {filename}: {e}", file=sys.stderr)
            continue


# ===============================
# TESTRAIL DETECTION
# ===============================

def is_testrail_url_line(line: str, testrail_domain: str | None) -> bool:
    """
    Check if a line contains a TestRail URL.
    Accepts formats like:
      - // https://testrail...
      - // TestRail link: https://testrail...
    """
    s = line.strip()
    if not s:
        return False

    # Check if line contains a URL
    has_url = "http://" in s or "https://" in s
    if not has_url:
        return False

    # Check domain match
    if testrail_domain:
        return testrail_domain in s
    return "testrail" in s.lower()


def is_linked(lines: list[str], func_idx: int, testrail_domain: str | None, platform: str) -> bool:
    """
    Check if a test function has a TestRail link above it.

    iOS/Swift pattern:
      // https://testrail...
      // Smoke TAE (optional)
      func testName()

    Android/Kotlin pattern:
      // TestRail link: https://mozilla.testrail.io/...
      @SmokeTest (optional)
      @Test
      fun testName()
    """
    if func_idx == 0:
        return False

    if platform == "android":
        # For Android/Kotlin, skip back over annotations (@Test, @SmokeTest, etc.)
        idx = func_idx - 1
        while idx >= 0:
            line = lines[idx].strip()
            if not line:
                idx -= 1
                continue
            # If we hit an annotation, keep going up
            if line.startswith("@"):
                idx -= 1
                continue
            # Found a non-annotation, non-empty line
            # This should be the TestRail comment
            return is_testrail_url_line(lines[idx], testrail_domain)

        return False

    else:  # iOS/Swift
        prev1 = lines[func_idx - 1]

        if prev1.strip() == "":
            return False

        if is_testrail_url_line(prev1, testrail_domain):
            return True

        # If prev1 is a Smoke marker, skip over any intermediate comments
        # to find the TestRail URL
        if SMOKE_RE.match(prev1):
            idx = func_idx - 2  # Start from line before Smoke marker
            while idx >= 0:
                line = lines[idx].strip()
                # Skip empty lines
                if not line:
                    idx -= 1
                    continue
                # If we find a TestRail URL, we're linked
                if is_testrail_url_line(lines[idx], testrail_domain):
                    return True
                # If we hit a non-comment line (not starting with //), stop
                if not line.startswith("//"):
                    return False
                # Skip over regular comments and keep looking
                idx -= 1
            return False

        return False


def should_ignore_file(path: Path, ignored_dirs: set, platform: str) -> bool:
    # Platform-specific ignore patterns
    if platform == "ios":
        # Ignore specific files by name
        if path.name in IOS_IGNORED_FILES:
            return True

        # Ignore accessibility tests
        if path.name.startswith("A11y"):
            return True

        # Ignore performance test files by name (e.g. PerformanceTests.swift)
        if path.name.startswith("PerformanceTests"):
            return True

        # Ignore experiment integration test files
        if path.name.startswith("ExperimentIntegrationTests"):
            return True

    # Ignore specific directories anywhere in the path
    for part in path.parts:
        if part in ignored_dirs:
            return True

    return False


def scan_file(
    path: Path | SearchfoxFile,
    testrail_domain: str | None,
    debug: bool,
    test_func_re: re.Pattern,
    ignored_dirs: set[str],
    platform: str,
) -> tuple[int, list[MissingLink]]:
    # Handle both local files and searchfox files
    if isinstance(path, Path):
        if should_ignore_file(path, ignored_dirs, platform):
            return 0, []
        content = path.read_text(encoding="utf-8", errors="replace")
    else:  # SearchfoxFile
        # For searchfox files, use the name as a Path for ignore check
        if should_ignore_file(Path(path.name), ignored_dirs, platform):
            return 0, []
        content = path.content

    missing: list[MissingLink] = []
    lines = content.splitlines()

    found_tests = 0

    # For Kotlin, track if we're after a @Test annotation
    pending_test_annotation = False

    for i, line in enumerate(lines):
        # Check for Kotlin @Test annotation
        if platform == "android" and KOTLIN_TEST_ANNOTATION_RE.match(line):
            pending_test_annotation = True
            continue

        m = test_func_re.match(line)
        if not m:
            # If we were expecting a test function after @Test, reset
            if pending_test_annotation and line.strip() and not line.strip().startswith("//"):
                pending_test_annotation = False
            continue

        found_tests += 1
        test_name = m.group(1)

        prev1 = lines[i - 1].rstrip() if i > 0 else "<start of file>"
        prev2 = lines[i - 2].rstrip() if i > 1 else "<start of file>"

        linked = is_linked(lines, i, testrail_domain, platform)

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

        pending_test_annotation = False

    return found_tests, missing


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Detect test functions missing a TestRail URL above them."
    )
    ap.add_argument(
        "--root",
        required=True,
        help="Root directory to scan (local path or searchfox URL)",
    )
    ap.add_argument(
        "--platform",
        choices=["ios", "android"],
        required=True,
        help="Platform to scan (ios for Swift, android for Kotlin)",
    )
    ap.add_argument(
        "--testrail-domain",
        default=None,
        help="TestRail domain to check for (default: mozilla.testrail.io for Android, any for iOS)",
    )
    ap.add_argument("--fail", action="store_true", help="Exit with error code if missing URLs found")
    ap.add_argument("--debug", action="store_true", help="Print debug information")
    args = ap.parse_args()

    # Configure platform-specific settings
    if args.platform == "ios":
        file_pattern = "*.swift"
        test_func_re = SWIFT_TEST_FUNC_RE
        ignored_dirs = IOS_IGNORED_DIRS
        platform_name = "Swift"
        # Use user-provided domain or None (will match any URL with "testrail")
        testrail_domain = args.testrail_domain
    else:  # android
        file_pattern = "*Test.kt"
        test_func_re = KOTLIN_TEST_FUNC_RE
        ignored_dirs = ANDROID_IGNORED_DIRS
        platform_name = "Kotlin"
        # Use user-provided domain or default to mozilla.testrail.io for Android
        testrail_domain = args.testrail_domain or "mozilla.testrail.io"

    # Check if root is a searchfox URL or local path
    is_searchfox = is_searchfox_url(args.root)

    total_tests = 0
    all_missing: list[MissingLink] = []
    file_count = 0

    if is_searchfox:
        # Fetch files from searchfox
        try:
            for sf_file in get_searchfox_files(args.root, file_pattern):
                file_count += 1
                found, missing = scan_file(
                    sf_file,
                    testrail_domain,
                    args.debug,
                    test_func_re,
                    ignored_dirs,
                    args.platform,
                )
                total_tests += found
                all_missing.extend(missing)
        except Exception as e:
            print(f"ERROR: Failed to fetch from searchfox: {e}", file=sys.stderr)
            return 2
    else:
        # Scan local directory
        root = Path(args.root)
        if not root.exists():
            print(f"ERROR: root does not exist: {root}", file=sys.stderr)
            return 2

        test_files = sorted(root.rglob(file_pattern))
        file_count = len(test_files)

        for f in test_files:
            found, missing = scan_file(
                f, testrail_domain, args.debug, test_func_re, ignored_dirs, args.platform
            )
            total_tests += found
            all_missing.extend(missing)

    source_type = "searchfox" if is_searchfox else "local"
    print(f"\nScanned {file_count} {platform_name} files from {source_type}, found {total_tests} tests.")

    if not all_missing:
        print("✅ No missing TestRail URLs found.")
        return 0

    print(f"\n❌ Found {len(all_missing)} tests missing TestRail URLs:\n")
    for item in all_missing:
        p1 = item.prev1.strip() or "<empty>"
        p2 = item.prev2.strip() or "<empty>"
        # Handle both Path and SearchfoxFile display
        if isinstance(item.file, SearchfoxFile):
            file_display = item.file.name
        else:
            file_display = str(item.file)
        print(f"- {file_display}:{item.line_no}  {item.test_name}")
        print(f"  prev1: {p1}")
        print(f"  prev2: {p2}")

    return 1 if args.fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
