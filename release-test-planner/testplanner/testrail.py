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
# A well-formed display id is exactly `C` followed by digits. Anything else in
# that column means the row's fields have shifted.
CASE_ID_RE = re.compile(r"^[CT]?\d+$")

# ORDER MATTERS, and getting it wrong is silent. A TestRail *run* export has both
# an `ID` column holding the test-instance id (`T9474971`) and a `Case ID` column
# holding the case id (`C2306813`). Only the case id appears in the source tree,
# so preferring `ID` joins nothing, reports 0% automated, and looks entirely
# plausible. Case-id spellings therefore come first.
ID_COLUMNS = ("case id", "case_id", "caseid", "case", "id", "c")
TITLE_COLUMNS = ("title", "case title", "name")
SECTION_COLUMNS = ("section", "section name", "section_id", "test area")
# Present in run exports, absent from plain case exports.
STATUS_COLUMNS = ("status", "result")
PRIORITY_COLUMNS = ("priority", "case priority")
DEPTH_COLUMNS = ("section depth", "section_depth", "depth")
# TestRail's own view of automation, present in a case export. Worth reading
# rather than inferring: it is a human triage decision, and comparing it against
# what the source tree actually references is more useful than either alone.
AUTOMATION_COLUMNS = ("automation", "automation status", "custom_automation_status")
AUTOMATION_COVERAGE_COLUMNS = ("automation coverage", "coverage")
AUTOMATED_NAME_COLUMNS = ("automated test name(s)", "automated test name",
                          "automated test names")
CONVERTED_COLUMNS = ("is_converted", "converted")
SUBSUITE_COLUMNS = ("sub test suite(s)", "sub test suite", "suite")

# `Automation` values that assert automation exists.
CLAIMED_AUTOMATED = {"completed", "automated", "done"}
# ...that it is possible but not done. This is the actionable backlog.
CLAIMED_AUTOMATABLE = {"suitable"}
# ...that it never will be, which makes the case permanently manual and is a
# legitimate answer rather than a gap.
CLAIMED_MANUAL = {"unsuitable", "not suitable", "manual"}
# Statuses that mean the case was not executed in this run.
NOT_RUN_STATUSES = {"untested", "retest", "", "in progress"}
# ...and that it was deliberately excluded rather than left undone.
EXCLUDED_STATUSES = {"not applicable", "n/a"}


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
                # A run export in JSON form carries `case_id` alongside its own
                # `id`; the case id is the one the source tree references.
                "id": normalise_id(c.get("case_id") or c.get("id")),
                "title": str(c.get("title") or ""),
                "section": str(c.get("section") or c.get("section_id") or ""),
                "status": str(c.get("status") or c.get("status_id") or ""),
                "priority": str(c.get("priority") or c.get("priority_id") or ""),
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
            status_col = column(STATUS_COLUMNS)
            priority_col = column(PRIORITY_COLUMNS)
            depth_col = column(DEPTH_COLUMNS)
            automation_col = column(AUTOMATION_COLUMNS)
            coverage_col = column(AUTOMATION_COVERAGE_COLUMNS)
            names_col = column(AUTOMATED_NAME_COLUMNS)
            converted_col = column(CONVERTED_COLUMNS)
            subsuite_col = column(SUBSUITE_COLUMNS)

            # A TestRail CSV carries only the leaf section name, but the rows come
            # out in section-tree order with a depth number - so the ancestors can
            # be recovered with a stack. This matters because a lot of leaves are
            # named "Layout", "Functional" or "Other", which say nothing on their
            # own and everything in context.
            out = []
            malformed = 0
            ancestors: List[str] = []
            for row in reader:
                raw_id = str(row.get(id_col) or "").strip()
                case_id = normalise_id(raw_id)
                if not case_id:
                    continue        # blank trailing row, or nothing to join to
                # Rich-text case fields containing newlines and quotes shift the
                # remaining columns of a row. Detected rather than trusted: the
                # id column still parses, so the wrong values would otherwise be
                # read as real automation statuses.
                if not CASE_ID_RE.match(raw_id):
                    malformed += 1
                section = str(row.get(section_col) or "") if section_col else ""
                path: List[str] = []
                if depth_col:
                    try:
                        depth = int(str(row.get(depth_col) or "0").strip() or 0)
                    except ValueError:
                        depth = 0
                    del ancestors[depth:]
                    while len(ancestors) < depth:
                        ancestors.append("")
                    path = [a for a in ancestors if a]
                    ancestors.append(section)
                def cell(col):
                    return str(row.get(col) or "").strip() if col else ""

                out.append({
                    "id": case_id,
                    "title": str(row.get(title_col) or "") if title_col else "",
                    "section": section,
                    "section_path": path,
                    "status": cell(status_col),
                    "priority": cell(priority_col),
                    "automation_status": cell(automation_col),
                    "automation_coverage": cell(coverage_col),
                    "automated_names": cell(names_col),
                    "is_converted": cell(converted_col),
                    "sub_suite": cell(subsuite_col),
                    "malformed": not CASE_ID_RE.match(raw_id),
                })
            return out

    raise SystemExit(
        "unsupported TestRail export %s - use .json or .csv (xlsx needs a "
        "dependency this tool deliberately does not have)" % path)


def load_exports(paths) -> List[Dict]:
    """Merge several exports by case id, earlier files winning per field.

    Two exports from the same project usually carry different columns: a run
    export has the section tree (so a case titled "Verify swipe functionality"
    can be attributed at all) while a case export has TestRail's automation
    triage and every case in the suite rather than the subset one run selected.
    Merging gives both, and neither file alone does.
    """
    if isinstance(paths, str):
        paths = [paths]
    merged: Dict[str, Dict] = {}
    order: List[str] = []
    for path in paths:
        for case in load_export(path):
            cid = case["id"]
            if cid not in merged:
                merged[cid] = dict(case, sources=[os.path.basename(path)])
                order.append(cid)
                continue
            existing = merged[cid]
            existing["sources"].append(os.path.basename(path))
            for key, value in case.items():
                if key in ("id", "sources"):
                    continue
                # Fill blanks only: the first file that had an opinion keeps it.
                if not existing.get(key) and value:
                    existing[key] = value
    return [merged[cid] for cid in order]


def _claim(case: Dict) -> str:
    """TestRail's own automation verdict, normalised to one of four words."""
    status = (case.get("automation_status") or "").strip().lower()
    coverage = (case.get("automation_coverage") or "").strip().lower()
    if status in CLAIMED_AUTOMATED or coverage == "full":
        return "automated"
    if status in CLAIMED_MANUAL:
        return "manual"
    if status in CLAIMED_AUTOMATABLE or coverage == "partial":
        return "automatable"
    return "untriaged"


def _normalise(text: str) -> str:
    """Lowercase, depunctuate, and singularise, so "Update a bookmark" can match
    the `bookmarks` feature. TestRail section names are prose written by hand
    over years; the catalog's vocabulary is not going to line up by luck."""
    text = re.sub(r"[^a-z0-9]+", " ", (text or "").lower())
    words = [w[:-1] if len(w) > 3 and w.endswith("s") else w for w in text.split()]
    return " " + " ".join(words) + " "


def _needles(feature) -> List[str]:
    out = [feature.id.replace("-", " "), feature.name]
    out += list(getattr(feature, "test_patterns", []) or [])
    out += list(getattr(feature, "testrail_keywords", []) or [])
    # Split a compound feature name into its parts: "Logins & Passwords" should
    # be reachable from a section called just "Passwords".
    for part in re.split(r"[&/,]| and ", feature.name):
        part = part.strip()
        if len(part) > 3:
            out.append(part)
    return [_normalise(n).strip() for n in out if n]


def _match_feature(case: Dict, catalog) -> Optional[str]:
    """Bind a case to a feature, scoring every candidate rather than taking the
    first.

    Returning the first match made catalog order decide attribution: a feature
    listed early captured any case whose section merely mentioned one of its
    words. Now the longest match wins, so `Password generator` binds to
    `logins-passwords` on "password" rather than to whichever feature happened to
    come first.

    Section outranks title because it is a curated grouping and title text is
    not. Both are weaker evidence than the id join used for automation, so a case
    matching nothing is reported as unattributed rather than spread around.
    """
    # Weight by how much the text is a statement about what the case covers:
    # the leaf section is the strongest, its ancestors give context to leaves
    # named "Layout" or "Other", and the title is prose.
    haystacks = [
        (_normalise(case.get("section", "")), 3),
        (_normalise(" ".join(case.get("section_path") or [])), 2),
        (_normalise(case.get("title", "")), 1),
    ]

    best_id, best_score = None, 0
    for feature in catalog.features:
        for needle in _needles(feature):
            if not needle:
                continue
            padded = " %s " % needle
            for hay, weight in haystacks:
                if padded in hay:
                    score = len(needle) * weight
                    if score > best_score:
                        best_id, best_score = feature.id, score
                    break
    return best_id


def build(path: str, catalog, inventory: Dict, cov: Dict) -> Dict:
    """Join a TestRail export to the automated corpus.

    Returns per-feature automated/manual counts plus the totals a release
    manager reads first: how much of the written-down plan a machine will run,
    and therefore what has to be covered by hand.
    """
    cases = load_exports(path)
    by_id: Dict[str, Dict] = {c["id"]: c for c in cases if c["id"]}
    malformed_rows = sum(1 for c in cases if c.get("malformed"))

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

    # Execution status, present in a run export and absent from a case export.
    # A release run that left a third of its plan untested is worth surfacing
    # next to the automation ratio, since both feed the same decision.
    status_counts: Dict[str, int] = {}
    for case in by_id.values():
        label = (case.get("status") or "").strip() or "unknown"
        status_counts[label] = status_counts.get(label, 0) + 1
    not_run = sum(n for s, n in status_counts.items()
                  if s.lower() in NOT_RUN_STATUSES)
    excluded = sum(n for s, n in status_counts.items()
                   if s.lower() in EXCLUDED_STATUSES)

    # How much the two populations actually overlap. This decides whether the
    # ratio above means anything at all: if the automation references 440 cases
    # and only 25 are in this export, then the export is a different population -
    # a manual run, most likely - and 3.4% is not an automation rate. Saying
    # "3.4% automated" without this check would be the most misleading number the
    # tool could print.
    referenced = len(automated)
    overlap = len(live_automated) + len(skipped_automated)
    overlap_ratio = round(overlap / referenced, 4) if referenced else 0.0
    disjoint = referenced > 20 and overlap_ratio < 0.5

    # TestRail's own triage vs what the source tree actually references. Neither
    # is authoritative on its own, and the disagreements are the useful part:
    #   claimed_not_in_code  TestRail believes this is automated but no test
    #                        links to it - a stale status, or a lost link
    #   in_code_not_claimed  a test links to a case TestRail has not triaged as
    #                        automated - the status is behind the code
    #   automatable          triaged as automatable and still not done: the
    #                        actionable backlog, distinct from "manual forever"
    claims = {cid: _claim(case) for cid, case in by_id.items()}
    claim_counts: Dict[str, int] = {}
    for verdict in claims.values():
        claim_counts[verdict] = claim_counts.get(verdict, 0) + 1
    claimed_ids = {cid for cid, v in claims.items() if v == "automated"}
    in_code = set(automated) & set(by_id)
    claimed_not_in_code = sorted(claimed_ids - in_code)
    in_code_not_claimed = sorted(in_code - claimed_ids)

    return {
        "sources": [os.path.abspath(p)
                    for p in ([path] if isinstance(path, str) else path)],
        "denominator": "assumed",
        "denominator_note": (
            "The TestRail case set is taken as the intended release-test plan. "
            "It measures how much of that plan is automated, not how much of "
            "the app is covered."
        ),
        "populations_disjoint": disjoint,
        "disjoint_note": (
            "The automated tests reference %d case ids; only %d of them are in "
            "this export. These are largely different case sets, so the "
            "automated share below is 'how much of THIS set is automated', not "
            "an automation rate for the project. A run export is usually a "
            "manual plan; cross-check against a case export covering the ids "
            "the tests reference." % (referenced, overlap)
        ) if disjoint else "",
        "totals": {
            "cases": total_cases,
            "automated": len(live_automated),
            "skipped_automation": len(skipped_automated),
            "manual_only": total_cases - len(live_automated),
            "automated_ratio": (round(len(live_automated) / total_cases, 4)
                                if total_cases else 0.0),
            "unattributed_cases": unattributed,
            "unmatched_ids": len(unmatched),
            "ids_referenced_by_automation": referenced,
            "overlap_with_automation": overlap,
            "overlap_ratio": overlap_ratio,
            "tests_without_case_id": sum(
                1 for t in inventory.get("tests", []) if not t.get("testrail_id")),
            "status_counts": status_counts,
            "not_run": not_run,
            "excluded": excluded,
            "executed": total_cases - not_run - excluded,
            "malformed_rows": malformed_rows,
            # TestRail's own triage, and where it disagrees with the tree.
            "claims": claim_counts,
            "claimed_automated": len(claimed_ids),
            "claimed_not_in_code": len(claimed_not_in_code),
            "in_code_not_claimed": len(in_code_not_claimed),
            # A case triaged "Unsuitable" is deliberately manual forever, so
            # counting it as an automation gap makes the gap look worse than it
            # is and never shrinks. The addressable denominator excludes them.
            "deliberately_manual": claim_counts.get("manual", 0),
            "addressable_cases": total_cases - claim_counts.get("manual", 0),
            "automated_ratio_addressable": (
                round(len(live_automated)
                      / (total_cases - claim_counts.get("manual", 0)), 4)
                if total_cases - claim_counts.get("manual", 0) else 0.0),
        },
        "claimed_not_in_code": claimed_not_in_code[:50],
        "in_code_not_claimed": in_code_not_claimed[:50],
        "unmatched_ids": unmatched[:50],
        "per_feature": sorted(per_feature.values(),
                              key=lambda e: e["cases"], reverse=True),
    }
