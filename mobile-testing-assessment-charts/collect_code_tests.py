#!/usr/bin/env python3
"""
Count test methods in the Firefox for iOS and Firefox for Android sources.

These are volume numbers, not coverage: one test method is one count, however
much it exercises. Commented-out tests (// and /* */) are not counted.

Usage:
    python collect_code_tests.py --ios <firefox-ios checkout> \
        --android <firefox checkout> --out site/data/code.json

The Android checkout only needs mobile/android, so a sparse clone is enough.
"""

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

JSON_SCHEMA_VERSION = 1

# ---------------------------------------------------------------------------
# iOS
# ---------------------------------------------------------------------------

IOS_TESTS = "firefox-ios/firefox-ios-tests/Tests"
IOS_BROWSERKIT_TESTS = "BrowserKit/Tests"

SWIFT_TEST = re.compile(
    r"^\s*(?:@\w+\s+)*"
    r"(?:(?:override|final|public|private|internal|nonisolated)\s+)*"
    r"func\s+test\w*\s*\(",
    re.M,
)
SMOKETEST = re.compile(r"//\s*Smoketest")
SNAPSHOT = re.compile(r"\bsnapshot\(")
PYTEST = re.compile(r"^\s*def test_\w+", re.M)

# Storage/Sync/Account targets, grouped as one layer.
IOS_STORAGE_SYNC = [
    "SharedTests", "StorageTests", "SyncTests", "AccountTests",
    "SyncTelemetryTests",
]

# XCUITest file name (regex, first match wins) -> functional feature.
# Files that match nothing land in "Other", so new suites show up instead of
# disappearing.
XCUI_FEATURES = [
    (r"^A11y", "Accessibility (targeted)"),
    (r"Onboarding|OpeningScreen", "Onboarding"),
    (r"Share", "Sharing"),
    (r"Address", "Autofill · Addresses"),
    (r"CreditCard", "Autofill · Credit Cards"),
    (r"Login|Password|Authentication", "Autofill · Passwords"),
    (r"Settings", "Settings"),
    (r"Search|Suggest|DomainAutocomplete", "Search"),
    (r"Bookmark", "Bookmarks"),
    (r"History|ReadingList|Library", "History / ReadingList"),
    (r"Private", "Tabs (private)"),
    (r"Tab|DragAndDrop|MultiWindow", "Tabs (general)"),
    (r"Navigation|URLValidation|SiteLoad", "Navigation"),
    (r"ActivityStream|JumpBackIn|HomeButton|Story|HomePage|PhotonActionSheet",
     "Homepage"),
    (r"Toolbar|UrlBar", "Toolbar / URL bar"),
    (r"TrackingProtection|Security", "Tracking Protection"),
    (r"Download", "Downloads"),
    (r"FindInPage", "Find in Page"),
    (r"DesktopMode", "Desktop Mode"),
    (r"ExperimentIntegration", "Experiment integration"),
    (r"^IntegrationTests", "Legacy server integration"),
    (r"PDF|Reader", "Reader Mode / PDF"),
    (r"Widget", "Widgets"),
    (r"DataManagement|Cookie", "Data Management"),
    (r"Zoom", "Zoom"),
    (r"Sync|Pairing", "Sync / FxA"),
    (r"AIControls", "AI controls"),
    (r"KeyboardShortcut", "Keyboard shortcuts"),
    (r"Print", "Print"),
    (r"Translation", "Translation"),
    (r"Microsurvey", "Microsurvey"),
    (r"ClipBoard|Clipboard|CopiedLinks", "Clipboard"),
    (r"NightMode", "Night Mode"),
    (r"Notification", "Notifications"),
    (r"Performance", "Performance"),
]

# ---------------------------------------------------------------------------
# Android (Fenix only; android-components is not counted)
# ---------------------------------------------------------------------------

FENIX_SRC = "mobile/android/fenix/app/src"
FENIX_ANDROID_TEST_PKG = "androidTest/java/org/mozilla/fenix"

KOTLIN_TEST = re.compile(r"@Test\b")
ROBOLECTRIC = re.compile(
    r"@RunWith\((?:AndroidJUnit4|RobolectricTestRunner|"
    r"ParameterizedRobolectricTestRunner)\b")
COMPOSE_RULE = re.compile(r"\bcreate(?:Android)?ComposeRule\b")
ANDROID_SMOKE = re.compile(r"@SmokeTest\b")

# Test Automation Efficiency (TAE) framework, inside ui/. Its tests/ folder is
# product E2E; everything else in it tests the framework itself.
TAE_DIR = ("ui", "efficiency")
TAE_TESTS = "tests"

# E2E test file name (regex, first match wins) -> functional feature. Same
# labels as XCUI_FEATURES where the feature exists on both platforms.
ANDROID_E2E_FEATURES = [
    (r"^AddressBar|Toolbar", "Toolbar / URL bar"),
    (r"Address", "Autofill · Addresses"),
    (r"CreditCard", "Autofill · Credit Cards"),
    (r"Login|Password", "Autofill · Passwords"),
    (r"Settings", "Settings"),
    (r"Search|Suggest|GoogleLens", "Search"),
    (r"Bookmark", "Bookmarks"),
    (r"History|RecentlyClosed", "History / ReadingList"),
    (r"Private", "Tabs (private)"),
    (r"CustomTab|Pwa|PWA", "Custom tabs / PWA"),
    (r"Tab|Collection", "Tabs (general)"),
    (r"Home|TopSites|Shortcuts|Pocket", "Homepage"),
    (r"MainMenu", "Main menu"),
    (r"Onboarding", "Onboarding"),
    (r"Download", "Downloads"),
    (r"FindInPage", "Find in Page"),
    (r"PDF|ReaderView", "Reader Mode / PDF"),
    (r"Translation", "Translation"),
    (r"Microsurvey", "Microsurvey"),
    (r"Nimbus", "Nimbus / Messaging"),
    (r"Crash|ErrorPage|Wayback|NoNetwork", "Crashes / Error pages"),
    (r"DeepLink|AboutURI", "Deep links"),
    (r"Permission|Prompt|FilePicker", "Site permissions"),
    (r"UnifiedTrust|Protection|GlobalPrivacy|HTTPSOnly", "Tracking Protection"),
    (r"WebCompat|ReportBrokenSite", "Web compat / Reporting"),
    (r"Text|WebControls|ContextMenu|Modifier", "Web content / Text"),
    (r"Extension|Addon", "Extensions / Add-ons"),
    (r"Media", "Media"),
    (r"Browser", "Navigation"),
]

# ---------------------------------------------------------------------------


def strip_comments(source):
    """Drop /* */ blocks and whole-line // comments."""
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return re.sub(r"^\s*//.*$", "", source, flags=re.M)


def read(path):
    return path.read_text(encoding="utf-8", errors="ignore")


def count_in(directory, pattern, glob, keep_comments=False):
    total = 0
    for f in sorted(Path(directory).rglob(glob)):
        text = read(f)
        total += len(pattern.findall(text if keep_comments else strip_comments(text)))
    return total


def git_info(repo):
    """Commit and date of the checkout, or None outside a git checkout."""
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "log", "-1", "--format=%H %cI"],
            capture_output=True, text=True, check=True).stdout.split()
        return {"commit": out[0], "date": out[1]}
    except (subprocess.CalledProcessError, FileNotFoundError, IndexError):
        return None


def require(path):
    if not path.is_dir():
        sys.exit(f"Not found: {path}. Is the checkout complete?")
    return path


def collect_ios(root):
    tests = require(root / IOS_TESTS)
    browserkit = require(root / IOS_BROWSERKIT_TESTS)

    def swift(*dirs):
        return sum(count_in(d, SWIFT_TEST, "*.swift") for d in dirs)

    xcui_total = swift(tests / "XCUITests")
    # The marker is a comment, so this one looks at comments on purpose.
    smoke = count_in(tests / "XCUITests", SMOKETEST, "*.swift", keep_comments=True)
    # PerformanceTests run as XCUITests but are their own layer here, so
    # they are not counted twice.
    perf_xcui = sum(count_in(f.parent, SWIFT_TEST, f.name)
                    for f in (tests / "XCUITests").rglob("PerformanceTests.swift"))
    integration = sum(
        count_in(tests / d, PYTEST, "test_*.py")
        for d in ("ExperimentIntegrationTests", "SyncIntegrationTests"))

    layers = {
        "unit_client": swift(tests / "ClientTests"),
        "unit_browserkit": swift(browserkit),
        "xcui_smoke": smoke,
        "xcui_other": xcui_total - smoke - perf_xcui,
        "legacy_kif": swift(tests / "UITests"),
        "storage_sync_account": swift(*[tests / d for d in IOS_STORAGE_SYNC]),
        "l10n_snapshot_calls": count_in(tests / "L10nSnapshotTests", SNAPSHOT, "*.swift"),
        "performance": perf_xcui + swift(tests / "StoragePerfTests"),
        "integration_py": integration,
    }

    # ClientTests by top-level folder; files directly in ClientTests are "(root)".
    modules = Counter()
    client = tests / "ClientTests"
    for f in client.rglob("*.swift"):
        rel = f.relative_to(client)
        name = rel.parts[0] if len(rel.parts) > 1 else "(root)"
        modules[name] += len(SWIFT_TEST.findall(strip_comments(read(f))))

    bk_modules = Counter()
    for d in sorted(p for p in browserkit.iterdir() if p.is_dir()):
        bk_modules[d.name] = swift(d)

    features = Counter()
    for f in (tests / "XCUITests").rglob("*.swift"):
        n = len(SWIFT_TEST.findall(strip_comments(read(f))))
        if not n:
            continue
        feature = next((label for pattern, label in XCUI_FEATURES
                        if re.search(pattern, f.name)), "Other")
        features[feature] += n

    return {
        "source": git_info(root),
        "layers": layers,
        "xcui_total": xcui_total,
        "client_modules": dict(modules.most_common()),
        "browserkit_modules": dict(bk_modules.most_common()),
        "xcui_features": dict(features.most_common()),
    }


def collect_android(root):
    src = require(root / FENIX_SRC)
    unit_dir = require(src / "test")
    instrumented = require(src / FENIX_ANDROID_TEST_PKG)

    # Unit tests (JUnit + Robolectric) by top-level package under
    # org.mozilla.fenix; files directly in it are "(root)".
    unit_pkg = unit_dir / "java/org/mozilla/fenix"
    junit = robolectric = 0
    modules = Counter()
    for f in unit_dir.rglob("*.kt"):
        text = strip_comments(read(f))
        n = len(KOTLIN_TEST.findall(text))
        if ROBOLECTRIC.search(text):
            robolectric += n
        else:
            junit += n
        if n and unit_pkg in f.parents:
            rel = f.relative_to(unit_pkg)
            modules[rel.parts[0] if len(rel.parts) > 1 else "(root)"] += n

    # androidTest by top-level package under org.mozilla.fenix:
    #   ui/efficiency/tests/     -> E2E UI, TAE framework
    #   ui/efficiency/ (rest)    -> TAE framework self-tests
    #   ui/ (rest)               -> E2E UI, Espresso + UIAutomator
    #   experimentintegration/,
    #   syncintegration/         -> integration
    #   perf/                    -> performance
    #   anything with a Compose
    #   test rule                -> component (Compose UI)
    #   the rest                 -> other instrumented
    e2e = tae = tae_framework = compose = integration = perf = other = smoke = 0
    features = Counter()
    for f in instrumented.rglob("*.kt"):
        text = strip_comments(read(f))
        n = len(KOTLIN_TEST.findall(text))
        if not n:
            continue
        parts = f.relative_to(instrumented).parts
        if parts[:2] == TAE_DIR:
            if len(parts) > 3 and parts[2] == TAE_TESTS:
                tae += n
            else:
                tae_framework += n
                continue
        elif parts[0] == "ui":
            e2e += n
        elif parts[0] in ("experimentintegration", "syncintegration"):
            integration += n
            continue
        elif parts[0] == "perf":
            perf += n
            continue
        elif COMPOSE_RULE.search(text):
            compose += n
            continue
        else:
            other += n
            continue
        # Only E2E tests (Espresso/UIAutomator and TAE) get here.
        smoke += len(ANDROID_SMOKE.findall(text))
        feature = next((label for pattern, label in ANDROID_E2E_FEATURES
                        if re.search(pattern, f.name)), "Other")
        features[feature] += n

    return {
        "source": git_info(root),
        "layers": {
            "unit_junit": junit,
            "unit_robolectric": robolectric,
            "component_compose": compose,
            "e2e_ui": e2e,
            "e2e_ui_tae": tae,
            "e2e_ui_smoke": smoke,
            "integration": integration,
            "performance": perf,
            "tae_framework": tae_framework,
            "other_instrumented": other,
        },
        "unit_modules": dict(modules.most_common()),
        "e2e_features": dict(features.most_common()),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[1])
    parser.add_argument("--ios", type=Path, required=True,
                        help="firefox-ios checkout")
    parser.add_argument("--android", type=Path, required=True,
                        help="firefox (gecko) checkout with mobile/android")
    parser.add_argument("--out", type=Path, default=Path("site/data/code.json"))
    args = parser.parse_args()

    data = {
        "schema_version": JSON_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ios": collect_ios(args.ios),
        "android": collect_android(args.android),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")

    for platform in ("ios", "android"):
        layers = data[platform]["layers"]
        print(f"{platform}: " + ", ".join(f"{k}={v}" for k, v in layers.items()))
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
