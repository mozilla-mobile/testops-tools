# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""Stage 2: map changed source paths onto user-facing features.

Deterministic where the catalog has a rule. Paths that match nothing are not
silently dropped - they are collected as open questions for an AI agent to
classify, because "we did not recognise this code" is itself a risk signal.
"""

from __future__ import annotations

import fnmatch
import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# Paths that legitimately carry no release risk for the app under test. A
# catalog can replace this with `_ignored_globs`, because what counts as
# "not app code" is platform-specific: on iOS the test targets, asset catalogs
# and Xcode plumbing would otherwise show up as unmapped feature churn, which
# reads as "we did not recognise this code" - a risk signal - when it is really
# just a test file.
IGNORED_GLOBS = [
    "**/test/**",
    "**/androidTest/**",
    "**/*Test.kt",
    "**/*Spec.kt",
    "**/docs/**",
    "**/*.md",
]


@dataclass
class Feature:
    id: str
    name: str
    severity: int
    severity_rationale: str = ""
    iso25010: List[str] = field(default_factory=list)
    source_globs: List[str] = field(default_factory=list)
    page_objects: List[str] = field(default_factory=list)
    test_patterns: List[str] = field(default_factory=list)
    # Vocabulary used in TestRail section and case titles, which is prose written
    # by hand over years and does not line up with the catalog's names by luck.
    # Only used to attribute TestRail cases - never for source attribution.
    testrail_keywords: List[str] = field(default_factory=list)
    # Cross-cutting code that no UI test is named for. It is exercised by the
    # whole suite rather than by a dedicated test, so a zero here means "not
    # directly covered", not "never executed".
    indirect: bool = False


class FeatureCatalog:
    def __init__(self, features: List[Feature],
                 ignored_globs: Optional[List[str]] = None,
                 platform: str = ""):
        self.features = features
        self.platform = platform
        self.ignored_globs = (list(ignored_globs) if ignored_globs
                              else list(IGNORED_GLOBS))
        self._by_id = {f.id: f for f in features}

    @classmethod
    def load(cls, path: str) -> "FeatureCatalog":
        with open(path) as fh:
            data = json.load(fh)
        return cls(
            [Feature(**f) for f in data["features"]],
            ignored_globs=data.get("_ignored_globs"),
            platform=data.get("_platform", ""),
        )

    def get(self, feature_id: str) -> Optional[Feature]:
        return self._by_id.get(feature_id)

    def __iter__(self):
        return iter(self.features)

    def match(self, path: str) -> List[tuple]:
        """Return [(feature, glob_specificity)] for every feature matching path."""
        hits = []
        for feature in self.features:
            best = 0
            for glob in feature.source_globs:
                if _glob_match(path, glob):
                    best = max(best, _specificity(glob))
            if best:
                hits.append((feature, best))
        return sorted(hits, key=lambda h: h[1], reverse=True)


def _glob_match(path: str, glob: str) -> bool:
    if fnmatch.fnmatch(path, glob):
        return True
    # fnmatch does not treat ** as spanning separators, so also try a
    # separator-insensitive form for the common "**/pkg/**" shape.
    if "**/" in glob:
        tail = glob.replace("**/", "", 1)
        return fnmatch.fnmatch(path, "*" + tail) or fnmatch.fnmatch(path, tail)
    return False


def _specificity(glob: str) -> int:
    """Longer, less-wildcarded globs win when several features match."""
    return len(glob.replace("*", ""))


def is_ignored(path: str, globs: Optional[List[str]] = None) -> bool:
    return any(_glob_match(path, g) for g in (globs or IGNORED_GLOBS))


def attribute(catalog: FeatureCatalog, files: List[Dict]) -> Dict:
    """Attribute changed files to features.

    Each file gets one primary feature (longest matching glob) plus any
    secondary features it also touches. Risk is aggregated on the primary so
    that a single change is not counted several times over.
    """
    per_feature: Dict[str, Dict] = {}
    unmapped: List[Dict] = []
    ignored: List[str] = []

    for fc in files:
        path = fc["path"]

        if is_ignored(path, catalog.ignored_globs):
            ignored.append(path)
            continue

        hits = catalog.match(path)
        if not hits:
            unmapped.append(fc)
            continue

        primary = hits[0][0]
        secondary = [f.id for f, _ in hits[1:]]

        bucket = per_feature.setdefault(
            primary.id,
            {
                "feature_id": primary.id,
                "name": primary.name,
                "severity": primary.severity,
                "severity_rationale": primary.severity_rationale,
                "iso25010": primary.iso25010,
                "indirect": primary.indirect,
                "files": [],
                "added": 0,
                "deleted": 0,
                "churned_lines": 0,
                "total_lines": 0,
                "commits": set(),
                "authors": 0,
                "backout_touched": False,
            },
        )
        bucket["files"].append(dict(fc, secondary_features=secondary))
        bucket["added"] += fc["added"]
        bucket["deleted"] += fc["deleted"]
        bucket["churned_lines"] += fc["churned_lines"]
        bucket["total_lines"] += fc["total_lines"]
        bucket["authors"] = max(bucket["authors"], fc["authors"])
        bucket["backout_touched"] = (
            bucket["backout_touched"] or fc["touched_by_backout"]
        )

    for bucket in per_feature.values():
        bucket["file_count"] = len(bucket["files"])
        bucket["commits"] = sum(f["commits"] for f in bucket["files"])
        total = max(bucket["total_lines"], 1)
        bucket["m1_churn_ratio"] = round(bucket["churned_lines"] / total, 4)
        bucket["m2_delete_ratio"] = round(bucket["deleted"] / total, 4)

    return {
        "features_touched": sorted(
            per_feature.values(), key=lambda b: b["churned_lines"], reverse=True
        ),
        "unmapped_files": unmapped,
        "ignored_count": len(ignored),
    }
