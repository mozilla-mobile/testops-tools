# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""Stage 4: bind existing tests to features and score coverage depth.

Deterministic. Two independent signals bind a test to a feature:

  name   the test class name matches one of the feature's test_patterns
  surface the test drives one of the feature's page objects / robots

Two signals agreeing is treated as strong evidence; one alone is weaker and is
recorded as such so an agent can review the thin bindings rather than trusting
them silently.
"""

from __future__ import annotations

import math
import re
from typing import Dict, List

# FMEA Detection runs 1-10, higher = LESS likely to catch a defect before
# release. Inverting coverage this way is what makes RPN fall as automation
# improves, per IEC 60812.
#
# Detection is CONTINUOUS rather than tiered. A step function would give the
# second test added to a feature exactly zero marginal gain, and the greedy
# planner would stall on that plateau instead of continuing to select tests.
# The curve below decays from 10 (nothing would catch it) asymptotically toward
# 2 (a defect would have to survive the whole suite), so every added test earns
# a positive but diminishing gain - which is also the honest shape, since
# redundant tests really do buy less than the first one.
DETECTION_FLOOR = 2.0
DETECTION_CEILING = 10.0
DECAY = 0.35

# Weights on what a test is worth as evidence.
#
# The binding weights matter more than they look. Almost every legacy test
# imports homeScreen/navigationToolbar in order to NAVIGATE somewhere else, not
# because it verifies the home screen. Counting those as coverage credited the
# Home Screen feature with 500+ tests and made it look deeply covered when
# nothing was actually asserting on it. Overstated coverage is worse than no
# coverage - it suppresses the RPN that should have triggered a manual test -
# so an incidental binding is worth almost nothing until an agent confirms it.
# An incidental binding is worth zero until an agent confirms it: the planner
# already refuses to schedule those tests, so letting them lower Detection here
# would promise risk reduction the plan cannot deliver. They stay recorded on
# the feature so they can be reviewed and promoted.
SMOKE_WEIGHT = 1.5
BINDING_WEIGHT = {
    "strong": 1.0,
    "name-only": 0.8,
    "incidental": 0.0,
}

TIER_BY_DETECTION = [
    (9.5, "none"),
    (8.0, "minimal"),
    (6.5, "thin"),
    (5.0, "moderate"),
    (3.5, "good"),
    (0.0, "deep"),
]


def effective_tests(tests: List[Dict]) -> float:
    """Weighted count of tests that actually count as evidence."""
    total = 0.0
    for t in tests:
        if t.get("is_disabled"):
            continue
        w = BINDING_WEIGHT.get(t.get("binding", "strong"), 1.0)
        if t.get("is_smoke"):
            w *= SMOKE_WEIGHT
        total += w
    return total


def detection_for(tests: List[Dict]) -> float:
    n = effective_tests(tests)
    if n <= 0:
        return DETECTION_CEILING
    span = DETECTION_CEILING - DETECTION_FLOOR
    return round(DETECTION_CEILING - span * (1 - math.exp(-DECAY * n)), 3)


def tier_for(detection: float) -> str:
    for threshold, label in TIER_BY_DETECTION:
        if detection >= threshold:
            return label
    return "deep"


def _normalise(surface: str) -> str:
    """Reduce a page object or robot name to a comparable stem.

    downloadRobot -> download ; settingsAutofill -> settingsautofill
    """
    s = re.sub(r"(Robot|Screen|Page|Component|Overlay)$", "", surface)
    return s.lower().rstrip("s")


def bind(catalog, inventory: Dict) -> Dict:
    """Attach tests to every feature they plausibly cover."""
    tests = inventory["tests"]

    feature_surface_stems = {
        f.id: {_normalise(p) for p in f.page_objects} for f in catalog
    }
    feature_patterns = {f.id: f.test_patterns for f in catalog}

    per_feature: Dict[str, Dict] = {
        f.id: {
            "feature_id": f.id,
            "name": f.name,
            "tests": [],
        }
        for f in catalog
    }

    unbound: List[Dict] = []

    for test in tests:
        stems = {_normalise(s) for s in test["surfaces"]}
        matched_any = False

        for feature in catalog:
            name_hit = any(
                p.lower() in test["class_name"].lower()
                for p in feature_patterns[feature.id]
                if p
            )
            surface_hit = bool(stems & feature_surface_stems[feature.id])

            if not (name_hit or surface_hit):
                continue

            if name_hit and surface_hit:
                strength = "strong"
            elif name_hit:
                strength = "name-only"
            else:
                # Drives the surface but is not named for it - most often a
                # test navigating through this feature to reach another one.
                strength = "incidental"

            per_feature[feature.id]["tests"].append(
                dict(test, binding=strength)
            )
            matched_any = True

        if not matched_any:
            unbound.append(test)

    for entry in per_feature.values():
        entry.update(_score(entry["tests"]))

    return {
        "per_feature": per_feature,
        "unbound_tests": unbound,
        "unbound_count": len(unbound),
    }


def _score(tests: List[Dict]) -> Dict:
    """Turn a set of bound tests into a coverage tier and Detection factor."""
    total = len(tests)
    active = [t for t in tests if not t["is_disabled"]]
    smoke = [t for t in active if t["is_smoke"]]
    strong = [t for t in active if t["binding"] == "strong"]
    incidental = [t for t in active if t["binding"] == "incidental"]
    modern = [t for t in active if t["suite"] == "ui.efficiency"]

    detection = detection_for(tests)
    # Automation that exists but is switched off is worth calling out by name;
    # numerically it is still no detection at all.
    tier = "disabled-only" if total and not active else tier_for(detection)

    return {
        "test_count": total,
        "active_count": len(active),
        "smoke_count": len(smoke),
        "strong_binding_count": len(strong),
        "incidental_count": len(incidental),
        "direct_count": len(active) - len(incidental),
        "modernised_count": len(modern),
        "disabled_count": total - len(active),
        "effective_tests": round(effective_tests(tests), 2),
        "coverage_tier": tier,
        "detection": detection,
        "modernisation_ratio": round(len(modern) / len(active), 2) if active else 0.0,
    }
