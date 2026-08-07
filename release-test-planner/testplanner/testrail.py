# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""An assumed coverage denominator, from the TestRail case set.

## What this is, and what it is not

The factory space (see docs/why-factories.md) is a *derived* denominator: the
generation framework enumerates what is reachable, so the total is computed, not
asserted. It only exists on Android.

The TestRail case set is an *assumed* denominator. Taking it as "full coverage"
is a judgement, and it is worth being explicit about why the judgement is
defensible and where it is not:

  * It is defensible because TestRail is a deliberate artefact. Someone decided
    each case was worth writing for a release. That is a statement of intent
    about what a release needs, which is precisely the question a release plan
    asks - and unlike the automated suite, it was not constrained by what was
    cheap to automate.

  * It is not complete. TestRail is also a pile that accumulated: cases cluster
    where bugs were once found and thin out where nobody wrote them. A
    percentage against it answers "how much of the plan we wrote down is
    automated", never "how much of the app is covered". Reported as
    `automated_ratio`, never as `coverage`.

So the two denominators answer different questions and must not be merged into
one number. Android can have both. iOS can only have this one, which is exactly
why it is worth wiring: it is the only denominator that works on both platforms.

## Why the join is exact

Both codebases already carry the key. Fenix writes

    // TestRail link: https://mozilla.testrail.io/index.php?/cases/view/2283299

above a @Test, and firefox-ios writes the same URL above `func testFoo()`.
`corpus.py` extracts it on both platforms with one regex. So binding automation
to cases is an id join, not a name-similarity heuristic - which matters, because
a heuristic would be one more assumption stacked on the assumed denominator.

## Input formats

Stdlib only, so no xlsx. Accepted:

  * JSON - either the raw TestRail API `get_cases` response (`{"cases": [...]}`)
    or a bare list of case objects. Keys used: `id`, `title`, `section_id`,
    `custom_automation_status`/`custom_automated` when present, plus anything
    matching a feature via section or title.
  * CSV - the export TestRail's UI produces. A column named `ID`/`Case ID` and
    one named `Title` are required; `Section` is used when present.

`testops-tools/testrail/testcases-deduplication/fetch_testrail_export.py` writes
xlsx; convert it, or point this at the API response directly.
"""

from __future__ import annotations

import csv
import json
import os
import re
from typing import Dict, List, Optional, Set

# TestRail ids appear as bare integers, as C-prefixed display ids, and inside
# case URLs. Normalised to the bare integer so all three join.
ID_RE = re.compile(r"(\d+)")

ID_COLUMNS = ("id", "case id", "case_id", "caseid", "c")
TITLE_COLUMNS = ("title", "case title", "name")
SECTION_COLUMNS = ("section", "section name", "section_id", "suite")


def normalise_id(value) -> str:
    """`C2283299`, `2283299`, `.../cases/view/2283299` -> `2283299`."""
    if value is None:
        return ""
    m = ID_RE.search(str(value))
    return m.group(1) if m else ""


def load_export(path: str) -> List[Dict]:
    """Read a TestRail export into a list of {id, title, section} dicts."""
    if not os.path.isfile(path):
        raise SystemExit("no such TestRail export: %s" % path)

    if path.lower().endswith(".json"):
        with open(path, errors="replace") as fh:
            data = json.load(fh)
        raw = data.get("cases", data) if isinstance(data, dict) else data
        if not isinstance(raw, list):
            raise SystemExit(
                "unexpected JSON shape in %s: expected a list of cases or "
                "{\"cases\": [...]}" % path)
        return [
            {
                "id": normalise_id(c.get("id")),
                "title": str(c.get("title") or ""),
                "section": str(c.get("section") or c.get("section_id") or ""),
                "automation_status": c.get("custom_automation_status",
                                           c.get("custom_automated", "")),
            }
            for c in raw if isinstance(c, dict)
        ]

    if path.lower().endswith((".csv", ".tsv")):
        delimiter = "\t" if path.lower().endswith(".tsv") else ","
        with open(path, newline="", errors="replace") as fh:
            reader = csv.DictReader(fh, delimiter=delimiter)
            if not reader.fieldnames:
                raise SystemExit("empty CSV: %s" % path)
            lookup = {(name or "").strip().lower(): name
                      for name in reader.fieldnames}

            def column(candidates):
                for cand in candidates:
                    if cand in lookup:
                        return lookup[cand]
                return None

            id_col = column(ID_COLUMNS)
            title_col = column(TITLE_COLUMNS)
            if not id_col:
                raise SystemExit(
                    "no id column in %s (looked for %s; found %s)"
                    % (path, "/".join(ID_COLUMNS), ", ".join(reader.fieldnames)))
            section_col = column(SECTION_COLUMNS)
            return [
                {
                    "id": normalise_id(row.get(id_col)),
                    "title": str(row.get(title_col) or "") if title_col else "",
                    "section": str(row.get(section_col) or "") if section_col else "",
                    "automation_status": "",
                }
                for row in reader
            ]

    raise SystemExit(
        "unsupported TestRail export %s - use .json or .csv (xlsx needs a "
        "dependency this tool deliberately does not have)" % path)


def _match_feature(case: Dict, catalog) -> Optional[str]:
    """Bind a case to a feature by section name, then by title keywords.

    Section first because it is a curated grouping and title text is not. Both
    are weaker evidence than the id join used for automation, so a case that
    matches nothing is reported as unattributed rather than spread around.
    """
    haystacks = [case.get("section", ""), case.get("title", "")]
    for feature in catalog.features:
        needles = [feature.id.replace("-", " "), feature.name.lower()]
        needles += [p.lower() for p in getattr(feature, "test_patterns", [])]
        for level, hay in enumerate(haystacks):
            hay_l = hay.lower()
            if not hay_l:
                continue
            for needle in needles:
                if needle and needle in hay_l:
                    return feature.id
    return None


def build(path: str, catalog, inventory: Dict, cov: Dict) -> Dict:
    """Join a TestRail export to the automated corpus.

    Returns per-feature automated/manual counts plus the totals a release
    manager reads first: how much of the written-down plan a machine will run,
    and therefore what has to be covered by hand.
    """
    cases = load_export(path)
    by_id: Dict[str, Dict] = {c["id"]: c for c in cases if c["id"]}

    # Which case ids the automation claims, and which test claims each.
    automated: Dict[str, List[str]] = {}
    for test in inventory.get("tests", []):
        case_id = normalise_id(test.get("testrail_id"))
        if not case_id:
            continue
        automated.setdefault(case_id, []).append(
            "%s.%s" % (test.get("class_name"), test.get("name")))

    # A test can reference a case that is not in the export - a different
    # project or suite, or a deleted case. Counting those as automated coverage
    # of this export would inflate the ratio, so they are reported separately.
    unmatched = sorted(set(automated) - set(by_id))

    # Automation that exists but never runs is not automated coverage. This is
    # the same rule as the @Ignore / xctestplan-skip handling in corpus.py, and
    # the reason it matters here is that these cases must fall back to manual.
    disabled_ids: Set[str] = set()
    for test in inventory.get("tests", []):
        case_id = normalise_id(test.get("testrail_id"))
        if case_id and test.get("is_disabled"):
            disabled_ids.add(case_id)
    live_automated = {cid for cid in automated
                      if cid in by_id and cid not in disabled_ids}
    skipped_automated = {cid for cid in automated
                         if cid in by_id and cid in disabled_ids}

    per_feature: Dict[str, Dict] = {
        f.id: {"feature_id": f.id, "feature": f.name, "cases": 0,
               "automated": 0, "skipped_automation": 0, "manual_only": 0,
               "case_ids_manual": []}
        for f in catalog.features
    }
    unattributed = 0
    for case_id, case in sorted(by_id.items()):
        fid = _match_feature(case, catalog)
        if fid is None:
            unattributed += 1
            continue
        entry = per_feature[fid]
        entry["cases"] += 1
        if case_id in live_automated:
            entry["automated"] += 1
        elif case_id in skipped_automated:
            entry["skipped_automation"] += 1
            entry["manual_only"] += 1
            entry["case_ids_manual"].append(case_id)
        else:
            entry["manual_only"] += 1
            entry["case_ids_manual"].append(case_id)

    for entry in per_feature.values():
        entry["automated_ratio"] = (
            round(entry["automated"] / entry["cases"], 4) if entry["cases"] else None
        )
        # Keep the list useful rather than enormous.
        del entry["case_ids_manual"][40:]

    total_cases = len(by_id)
    return {
        "source": os.path.abspath(path),
        "denominator": "assumed",
        "denominator_note": (
            "The TestRail case set is taken as the intended release-test plan. "
            "It measures how much of that plan is automated, not how much of "
            "the app is covered."
        ),
        "totals": {
            "cases": total_cases,
            "automated": len(live_automated),
            "skipped_automation": len(skipped_automated),
            "manual_only": total_cases - len(live_automated),
            "automated_ratio": (round(len(live_automated) / total_cases, 4)
                                if total_cases else 0.0),
            "unattributed_cases": unattributed,
            "unmatched_ids": len(unmatched),
            "tests_without_case_id": sum(
                1 for t in inventory.get("tests", []) if not t.get("testrail_id")),
        },
        "unmatched_ids": unmatched[:50],
        "per_feature": sorted(per_feature.values(),
                              key=lambda e: e["cases"], reverse=True),
    }
