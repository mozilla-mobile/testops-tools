# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""Platform descriptors: everything the pipeline needs to know about a repo.

The risk model, churn measures, plan builder and matrix generator carry no
platform knowledge and move between platforms unchanged. What differs is only
where the tests live, what language they are written in, how a test declares
itself, and whether the platform has a factory-generated candidate space.

Collecting that into one object is what lets `cli.py` stop holding Android path
constants, and makes adding a third platform a data change.

**Read `has_factories` before trusting a coverage percentage.** On Android the
generation framework enumerates the candidate space, so coverage has a derived
denominator. iOS has no equivalent, so a percentage there would be a fraction of
a number nobody computed. See docs/why-factories.md.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Tuple


@dataclass(frozen=True)
class Platform:
    id: str
    label: str
    language: str
    extension: str
    # (path relative to the repo root, suite label). Scanned in order, each
    # non-recursively, so a parent suite does not swallow a nested one.
    test_roots: Tuple[Tuple[str, str], ...]
    source_root: str
    default_catalog: str
    # Whether a factory-generated candidate space exists to divide by.
    has_factories: bool
    factory_root: str = ""
    # Directory holding .xctestplan files, if the platform expresses test
    # selection that way. Android has no analogue.
    test_plan_root: str = ""
    # The Xcode target the UI tests belong to. A plan is only relevant if it
    # includes this target: UnitTest.xctestplan lists two dozen unit-test targets
    # and no XCUITests, so reading its skip lists made every UI test look like it
    # ran there.
    test_target: str = ""
    # Heading for the HTML report. Spelled out per platform rather than derived
    # from `label`, because the products have names people recognise and
    # "Firefox iOS Release Test Plan" is not one of them.
    report_title: str = "Release Test Plan"
    # Paths a sparse worktree needs in order to analyse this platform. Used only
    # to print correct remediation when the checkout does not contain the range -
    # advice naming the wrong product's directories is worse than none.
    sparse_paths: Tuple[str, ...] = ()
    notes: str = ""

    def roots(self, repo_root: str) -> List[Tuple[str, str]]:
        return [(os.path.join(repo_root, p), suite) for p, suite in self.test_roots]


_FENIX_APP = "mobile/android/fenix/app"
_FENIX_UI = _FENIX_APP + "/src/androidTest/java/org/mozilla/fenix/ui"

ANDROID = Platform(
    id="android",
    label="Fenix (Android)",
    language="kotlin",
    extension=".kt",
    test_roots=(
        (_FENIX_UI, "ui"),
        (_FENIX_UI + "/efficiency/tests", "ui.efficiency"),
    ),
    source_root="mobile/android/fenix/app/src/main/java/org/mozilla/fenix",
    default_catalog="config/features.json",
    report_title="Fenix Release Test Plan",
    sparse_paths=("mobile/android/fenix",),
    has_factories=True,
    factory_root=_FENIX_UI + "/efficiency",
    notes="Coverage has a derived denominator: the generation factories "
          "enumerate the candidate space.",
)

# firefox-ios, current layout (release/v106 onwards). Earlier release branches
# are flat - `Client/` at the repo root rather than under `firefox-ios/` - and
# the bare vNNN.N branch names belong to that older scheme. Check the layout
# before pointing this at an old branch.
IOS = Platform(
    id="ios",
    label="Firefox for iOS",
    language="swift",
    extension=".swift",
    test_roots=(
        ("firefox-ios/firefox-ios-tests/Tests/XCUITests", "xcuitest"),
    ),
    source_root="firefox-ios/Client",
    default_catalog="config/features-ios.json",
    report_title="Firefox for iOS Release Test Plan",
    sparse_paths=("firefox-ios", "BrowserKit"),
    has_factories=False,
    test_plan_root="firefox-ios/firefox-ios-tests/Tests",
    test_target="XCUITests",
    notes="No factory candidate space. Coverage is reported against the "
          "TestRail case set when one is supplied, and otherwise as counts "
          "rather than percentages.",
)

PLATFORMS: Dict[str, Platform] = {p.id: p for p in (ANDROID, IOS)}
DEFAULT = ANDROID.id


def get(platform_id: str) -> Platform:
    try:
        return PLATFORMS[platform_id]
    except KeyError:
        raise SystemExit(
            "unknown platform %r (known: %s)"
            % (platform_id, ", ".join(sorted(PLATFORMS)))
        )
