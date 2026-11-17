#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml", "requests", "openpyxl"]
# ///
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""Attribute TestRail cases to the feature taxonomy, using the feature ID in each section's description.

Each section in the Full Functional suite carries its L2 ID (e.g. `LIB.BMK`) or L1 ID (e.g. `CRED`) as the
first word of its description. A case belongs to the ID of its own section or, when that section has none,
of the nearest ancestor that has one. IDs are checked against features.yml.

Commands:
    check     sections with an unknown ID, cases that reach no ID, cases that only reach an L1 area.
              Exit 1 when anything is unmapped or unknown.
    counts    cases per L1/L2: total, Automation = Completed, % automated (CSV with --csv).
    compare   counts and per-case differences against a feature-mapping workbook (Orla's
              firefox_ios_feature_mapping_with_L1.xlsx: Case ID, Automation, Proposed Feature ID, L1 ID).
    suggest   which ID to write in which section description so TestRail matches such a workbook, grouped by
              feature, for a person to copy in by hand. It never writes to TestRail.

Credentials come from TESTRAIL_HOST/TESTRAIL_URL, TESTRAIL_USERNAME/TESTRAIL_USER and
TESTRAIL_PASSWORD/TESTRAIL_KEY.

`check` and `compare` print section names: run them locally, not in a public CI log. `counts` only prints
aggregates. `--cache FILE` stores the fetched sections and cases (IDs, section names, automation status; no
titles or steps) so later runs don't hit TestRail; don't commit that file.

Usage:
    uv run testrail_map.py ios check
    uv run testrail_map.py ios counts --csv > ios_testrail_by_feature.csv
    uv run testrail_map.py ios --cache /tmp/ios.json compare --sheet firefox_ios_feature_mapping_with_L1.xlsx
    uv run testrail_map.py android suggest --sheet firefox_android_feature_mapping_with_L1_and_bugs.xlsx
"""

import argparse
import csv
import html
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from feature_map import load_taxonomy  # noqa: E402

# Full Functional Tests Suite per platform (same as mobile-testing-assessment-charts).
SUITES = {"ios": 45443, "android": 3192}
AUTOMATION_FIELD = "custom_automation_status"
COMPLETED = "Completed"
CREDENTIALS = {
    "url": ("TESTRAIL_URL", "TESTRAIL_HOST"),
    "user": ("TESTRAIL_USER", "TESTRAIL_USERNAME"),
    "key": ("TESTRAIL_KEY", "TESTRAIL_PASSWORD"),
}

TAG_RE = re.compile(r"<[^>]+>")
FIRST_WORD_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9]*(?:\.[A-Za-z0-9]+)?)\b")
# Looks like a feature ID (dotted, upper case) but isn't in the taxonomy: a typo to report.
DOTTED_ID_RE = re.compile(r"^[A-Z]{2,8}\.[A-Z0-9]{2,10}$")
NO_FEATURE = ""


# ---- taxonomy ------------------------------------------------------------------------------------------------

def valid_ids(taxonomy):
    """L2 feature IDs and L1 area IDs. SHARED.* and EXCLUDED are code-only buckets."""
    return {k for k, v in taxonomy.items() if v["group"] in ("features", "area")}


def feature_order(taxonomy):
    """[L1, its L2s..., next L1, ...] in features.yml order."""
    out = []
    for k, v in taxonomy.items():
        if v["group"] != "features":
            continue
        l1 = k.split(".")[0]
        if l1 not in out:
            out.append(l1)
        out.append(k)
    return out


# ---- section descriptions -> features ------------------------------------------------------------------------

def description_id(description, ids):
    """(feature_id, unknown_id) from a section description.

    The ID is the first word of the description once HTML is removed. A first word that isn't an ID (free
    text such as "Make middle navigation…") means no ID; a dotted upper-case word that isn't in the taxonomy
    (e.g. a typo `APP.UDP`) is returned as unknown.
    """
    text = html.unescape(TAG_RE.sub(" ", description or ""))
    m = FIRST_WORD_RE.match(text)
    if not m:
        return None, None
    word = m.group(1)
    if word in ids:
        return word, None
    if DOTTED_ID_RE.match(word):
        return None, word
    return None, None


class SectionTree:
    def __init__(self, sections, ids):
        self.sections = {s["id"]: s for s in sections}
        self.own, self.unknown = {}, {}
        for s in sections:
            fid, bad = description_id(s.get("description"), ids)
            if fid:
                self.own[s["id"]] = fid
            elif bad:
                self.unknown[s["id"]] = bad
        self._resolved = {}

    def path(self, section_id):
        names = []
        while section_id in self.sections:
            names.append(self.sections[section_id]["name"])
            section_id = self.sections[section_id].get("parent_id")
        return " > ".join(reversed(names))

    def feature(self, section_id):
        """ID of the section or its nearest ancestor with one, else NO_FEATURE."""
        if section_id not in self._resolved:
            sid, found = section_id, NO_FEATURE
            while sid in self.sections:
                if sid in self.own:
                    found = self.own[sid]
                    break
                sid = self.sections[sid].get("parent_id")
            self._resolved[section_id] = found
        return self._resolved[section_id]


def attribute(sections, cases, ids):
    """{case_id: (feature_id, automated)} plus the SectionTree used."""
    tree = SectionTree(sections, ids)
    out = {}
    for c in cases:
        out[c["id"]] = (tree.feature(c["section_id"]), c.get("automation") == COMPLETED)
    return out, tree


def count(attributed):
    """{key: Counter(total, automated)} for every L2 ID, every L1 ("L1:CRED") and NO_FEATURE.

    L1 totals include cases attributed to the L1 alone, so they can be larger than the sum of their L2s.
    """
    out = defaultdict(Counter)
    for fid, automated in attributed.values():
        keys = ["L1:" + fid.split(".")[0]] if fid else [NO_FEATURE]
        if "." in fid:
            keys.append(fid)
        for k in keys:
            out[k]["total"] += 1
            out[k]["automated"] += automated
    return out


# ---- TestRail ------------------------------------------------------------------------------------------------

class TestRail:
    def __init__(self, base_url, user, key):
        import requests

        self.base = base_url.rstrip("/") + "/index.php?/api/v2/"
        self.session = requests.Session()
        self.session.auth = (user, key)
        self.session.headers.update({"Content-Type": "application/json"})

    def get(self, endpoint):
        for _ in range(5):
            resp = self.session.get(self.base + endpoint, timeout=60)
            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", 10))
                print(f"  rate limited, waiting {wait}s", file=sys.stderr)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        raise RuntimeError(f"gave up after rate limits on {endpoint}")

    def get_paged(self, endpoint, key):
        items, offset, limit = [], 0, 250
        while True:
            payload = self.get(f"{endpoint}&limit={limit}&offset={offset}")
            if isinstance(payload, list):
                return payload
            batch = payload.get(key, [])
            items.extend(batch)
            if len(batch) < limit:
                return items
            offset += limit


def option_labels(field):
    """{id: label} from a dropdown field's "1, Completed" option lines."""
    out = {}
    for config in field.get("configs", []):
        for line in config.get("options", {}).get("items", "").splitlines():
            raw, sep, label = line.partition(",")
            if sep and raw.strip().isdigit():
                out[int(raw.strip())] = label.strip()
    return out


def credentials():
    found, missing = {}, []
    for setting, names in CREDENTIALS.items():
        value = next((os.environ[n].strip() for n in names if os.environ.get(n, "").strip()), None)
        if value is None:
            missing.append(" or ".join(names))
        found[setting] = value
    if missing:
        sys.exit("Missing TestRail credentials: " + "; ".join(missing))
    url = found["url"] if found["url"].startswith(("http://", "https://")) else "https://" + found["url"]
    return url, found["user"], found["key"]


def fetch(suite_id):
    """Sections and cases of a suite, keeping only what attribution needs (no titles or steps)."""
    api = TestRail(*credentials())
    field = next((f for f in api.get("get_case_fields") if f.get("system_name") == AUTOMATION_FIELD), None)
    labels = option_labels(field) if field else {}
    project_id = api.get(f"get_suite/{suite_id}")["project_id"]
    sections = api.get_paged(f"get_sections/{project_id}&suite_id={suite_id}", "sections")
    cases = api.get_paged(f"get_cases/{project_id}&suite_id={suite_id}", "cases")
    return {
        "suite_id": suite_id,
        "sections": [{k: s.get(k) for k in ("id", "name", "parent_id", "description")} for s in sections],
        "cases": [{"id": f"C{c['id']}", "section_id": c["section_id"],
                   "automation": labels.get(c.get(AUTOMATION_FIELD), "")} for c in cases],
    }


def load_data(platform, cache):
    if cache and os.path.exists(cache):
        with open(cache) as f:
            return json.load(f)
    print(f"Fetching {platform} suite {SUITES[platform]} from TestRail...", file=sys.stderr)
    data = fetch(SUITES[platform])
    if cache:
        with open(cache, "w") as f:
            json.dump(data, f)
    return data


# ---- feature-mapping workbook --------------------------------------------------------------------------------

def read_sheet(path):
    """{case_id: (feature_id, automated)} from a workbook's "Feature Mapping" sheet.

    The feature is the Proposed Feature ID when it is an L2, else the L1 ID; "OUT" counts as no feature.
    """
    import openpyxl

    ws = openpyxl.load_workbook(path, read_only=True)["Feature Mapping"]
    rows = ws.iter_rows(values_only=True)
    header = [str(h).strip() if h else "" for h in next(rows)]
    col = {name: header.index(name) for name in ("Case ID", "Automation", "Proposed Feature ID", "L1 ID")}
    out = {}
    for r in rows:
        case_id = r[col["Case ID"]]
        if not case_id:
            continue
        l2, l1 = r[col["Proposed Feature ID"]] or "", r[col["L1 ID"]] or ""
        fid = l2 if "." in l2 and not l2.startswith("OUT") else ("" if l1 in ("", "OUT") else l1)
        out[str(case_id)] = (fid, r[col["Automation"]] == COMPLETED)
    return out


# ---- suggestions from a workbook -----------------------------------------------------------------------------

def suggest_ids(sections, cases, sheet):
    """Section IDs that reproduce a per-case mapping, writing an ID only where it changes.

    Top-down: a section takes the most common feature of its own cases and gets a suggestion only when that
    differs from what it would inherit. A section with no cases of its own (a container such as "Browsing")
    gets an ID only when its whole subtree is one feature; otherwise each subsection gets its own, so new
    subsections of a mixed container don't silently inherit one feature. Cases
    the sheet doesn't know (added later) don't vote. Returns {section_id: feature_id}.
    """
    by_id = {s["id"]: s for s in sections}
    children = defaultdict(list)
    for s in sections:
        children[s.get("parent_id") if s.get("parent_id") in by_id else None].append(s["id"])
    direct = defaultdict(Counter)
    for c in cases:
        if c["id"] in sheet:
            direct[c["section_id"]][sheet[c["id"]][0]] += 1

    cache = {}

    def subtree_votes(sid):
        if sid not in cache:
            votes = Counter(direct[sid])
            for k in children[sid]:
                votes.update(subtree_votes(k))
            cache[sid] = votes
        return cache[sid]

    suggestions = {}

    def walk(sid, inherited):
        label = inherited
        if direct[sid]:
            top = direct[sid].most_common(1)[0][0]
            label = top or NO_FEATURE
        elif children[sid]:
            whole = set(subtree_votes(sid))
            label = whole.pop() if len(whole) == 1 else NO_FEATURE
        if label != inherited and label:
            suggestions[sid] = label
        for k in children[sid]:
            walk(k, label)

    for root in children[None]:
        walk(root, NO_FEATURE)
    return suggestions


# ---- commands ------------------------------------------------------------------------------------------------

def pct(c):
    return 100 * c["automated"] / c["total"] if c["total"] else None


def fmt_pct(value):
    return "—" if value is None else f"{value:.0f}%"


def find_problems(attributed, tree, data):
    """What `check` reports: {"unknown": {section_id: word}, "unmapped": Counter(section_id -> cases),
    "l1_only": Counter(section_id -> cases)}. Unknown IDs and unmapped cases are errors; L1-only is advice."""
    unmapped, l1_only = Counter(), Counter()
    for c in data["cases"]:
        fid = attributed[c["id"]][0]
        if not fid:
            unmapped[c["section_id"]] += 1
        elif "." not in fid:
            l1_only[c["section_id"]] += 1
    return {"unknown": dict(tree.unknown), "unmapped": unmapped, "l1_only": l1_only}


def cmd_check(attributed, tree, data, ids):
    found = find_problems(attributed, tree, data)
    unmapped, l1_only = found["unmapped"], found["l1_only"]
    problems = 0
    if tree.unknown:
        problems += len(tree.unknown)
        print(f"## Sections with an ID that isn't in features.yml ({len(tree.unknown)})\n")
        for sid, word in sorted(tree.unknown.items(), key=lambda kv: tree.path(kv[0])):
            print(f"- `{word}` in {tree.path(sid)}")
        print()

    if unmapped:
        problems += sum(unmapped.values())
        print(f"## Cases with no feature ({sum(unmapped.values())}): add an ID to the section or a parent\n")
        for sid, n in sorted(unmapped.items(), key=lambda kv: tree.path(kv[0])):
            print(f"- {n:4}  {tree.path(sid)}")
        print()
    if l1_only:
        print(f"## Cases attributed to an L1 area only ({sum(l1_only.values())}): an L2 would be more precise\n")
        for sid, n in sorted(l1_only.items(), key=lambda kv: tree.path(kv[0])):
            print(f"- {n:4}  `{tree.feature(sid)}`  {tree.path(sid)}")
        print()

    mapped = len(attributed) - sum(unmapped.values())
    print(f"{len(tree.own)} of {len(tree.sections)} sections carry an ID; "
          f"{mapped} of {len(attributed)} cases reach a feature ({sum(l1_only.values())} only an L1).")
    unused = [k for k in ids if "." in k and k not in {f for f, _ in attributed.values()}]
    if unused:
        print(f"L2 features with no TestRail case: {', '.join(sorted(unused))}")
    return 1 if problems else 0


def cmd_counts(attributed, taxonomy, as_csv):
    counts = count(attributed)
    rows = []
    for k in feature_order(taxonomy):
        key = k if "." in k else "L1:" + k
        c = counts.get(key, Counter())
        name = taxonomy[k]["name"] if "." in k else taxonomy[k]["area"]
        rows.append(("L2" if "." in k else "L1", k, name, c["total"], c["automated"], pct(c)))
    c = counts.get(NO_FEATURE, Counter())
    rows.append(("", "", "No feature", c["total"], c["automated"], pct(c)))

    if as_csv:
        w = csv.writer(sys.stdout)
        w.writerow(["level", "id", "name", "testrail_cases", "automated", "automated_pct"])
        for level, k, name, total, auto, p in rows:
            w.writerow([level, k, name, total, auto, "" if p is None else round(p, 1)])
        return 0
    print(f"| Feature | Name | TestRail cases | UI automation |\n|---|---|--:|--:|")
    for level, k, name, total, auto, p in rows:
        label = f"**{k}**" if level == "L1" else k
        print(f"| {label} | {name} | {total} | {fmt_pct(p)} |")
    return 0


def cmd_compare(attributed, tree, data, taxonomy, sheet_path):
    sheet = read_sheet(sheet_path)
    ours, theirs = count(attributed), count(sheet)

    print("## Counts per feature (sheet → TestRail)\n")
    print("| Feature | Cases (sheet) | Cases (TestRail) | Δ | Automated (sheet) | Automated (TestRail) |")
    print("|---|--:|--:|--:|--:|--:|")
    for k in feature_order(taxonomy) + [NO_FEATURE]:
        key = k if "." in k or k == NO_FEATURE else "L1:" + k
        a, b = theirs.get(key, Counter()), ours.get(key, Counter())
        if not a["total"] and not b["total"]:
            continue
        label = k or "No feature"
        if "." not in k and k:
            label = f"**{k}**"
        print(f"| {label} | {a['total']} | {b['total']} | {b['total'] - a['total']:+d} "
              f"| {fmt_pct(pct(a))} | {fmt_pct(pct(b))} |")

    section_of = {c["id"]: c["section_id"] for c in data["cases"]}
    both = sheet.keys() & attributed.keys()
    moved = Counter()
    automation_changed = 0
    for cid in both:
        (f_sheet, a_sheet), (f_tr, a_tr) = sheet[cid], attributed[cid]
        automation_changed += a_sheet != a_tr
        if f_sheet != f_tr:
            moved[(f_sheet, f_tr, section_of[cid])] += 1
    new = Counter((attributed[cid][0], section_of[cid]) for cid in attributed.keys() - sheet.keys())

    print(f"\nCases: {len(sheet)} in the sheet, {len(attributed)} in TestRail, {len(both)} in both, "
          f"{len(attributed.keys() - sheet.keys())} new, {len(sheet.keys() - attributed.keys())} gone.")
    print(f"Automation changed to or from Completed since the sheet: {automation_changed} cases.\n")
    if moved:
        print(f"## Cases attributed to a different feature ({sum(moved.values())})\n")
        print("| Cases | Sheet | TestRail | Section |\n|--:|---|---|---|")
        for (a, b, sid), n in moved.most_common():
            print(f"| {n} | {a or '—'} | {b or '—'} | {tree.path(sid)} |")
    if new:
        print(f"\n## Cases added since the sheet ({sum(new.values())})\n")
        print("| Cases | TestRail | Section |\n|--:|---|---|")
        for (f, sid), n in new.most_common():
            print(f"| {n} | {f or '—'} | {tree.path(sid)} |")
    return 0


def cmd_suggest(tree, data, taxonomy, ids, sheet_path):
    sheet = read_sheet(sheet_path)
    suggestions = suggest_ids(data["sections"], data["cases"], sheet)
    existing = {sid: fid for sid, fid in tree.own.items()}

    # Simulate: the suggested IDs on top of whatever the sections already carry.
    proposed = SectionTree(data["sections"], ids)
    proposed.own.update(suggestions)
    proposed._resolved.clear()
    source = {}
    for c in data["cases"]:
        sid = c["section_id"]
        while sid in proposed.sections and sid not in proposed.own:
            sid = proposed.sections[sid].get("parent_id")
        source[c["id"]] = sid if sid in proposed.own else None
    reach = Counter(source.values())

    by_feature = defaultdict(list)
    for sid, fid in suggestions.items():
        by_feature[fid].append(sid)
    print(f"# Suggested section IDs ({len(suggestions)} sections)\n")
    print("Write the ID as the first word of the section description. A subsection inherits it unless it has "
          "its own ID; `cases` counts the cases that get the ID through that section.\n")
    for fid in [k for k in feature_order(taxonomy) if k in by_feature]:
        name = taxonomy[fid]["name"] if "." in fid else taxonomy[fid]["area"] + " (whole area)"
        rows = sorted(by_feature[fid], key=tree.path)
        print(f"## `{fid}` {name}: {sum(reach[s] for s in rows)} cases\n")
        for sid in rows:
            note = f" (now `{existing[sid]}`)" if sid in existing and existing[sid] != fid else ""
            if sid in existing and existing[sid] == fid:
                note = " (already set)"
            print(f"- [ ] {tree.path(sid)}: {reach[sid]} cases{note}")
        print()

    disagree = Counter()
    for c in data["cases"]:
        if c["id"] in sheet and proposed.feature(c["section_id"]) != sheet[c["id"]][0]:
            disagree[(c["section_id"], sheet[c["id"]][0], proposed.feature(c["section_id"]))] += 1
    unknown = sum(1 for c in data["cases"] if c["id"] not in sheet)
    print(f"With these IDs, {sum(1 for c in data['cases'] if c['id'] in sheet) - sum(disagree.values())} of "
          f"{sum(1 for c in data['cases'] if c['id'] in sheet)} cases in the sheet get the sheet's feature; "
          f"{unknown} cases aren't in the sheet (added since) and take their section's ID.\n")
    if disagree:
        print("## Cases the sheet maps per case, not per section (decide by hand)\n")
        print("| Cases | Sheet | With the IDs | Section |\n|--:|---|---|---|")
        for (sid, a, b), n in sorted(disagree.items(), key=lambda kv: (tree.path(kv[0][0]), -kv[1])):
            print(f"| {n} | {a or 'OUT / none'} | {b or '—'} | {tree.path(sid)} |")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("platform", choices=sorted(SUITES))
    parser.add_argument("--cache", help="read sections/cases from this JSON file, or write them there")
    parser.add_argument("--taxonomy", help="features.yml to validate against (default: the one here)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check")
    p_counts = sub.add_parser("counts")
    p_counts.add_argument("--csv", action="store_true")
    p_compare = sub.add_parser("compare")
    p_compare.add_argument("--sheet", required=True, help="feature-mapping workbook (.xlsx)")
    p_suggest = sub.add_parser("suggest")
    p_suggest.add_argument("--sheet", required=True, help="feature-mapping workbook (.xlsx)")
    args = parser.parse_args(argv)

    taxonomy = load_taxonomy(args.taxonomy)
    ids = valid_ids(taxonomy)
    data = load_data(args.platform, args.cache)
    attributed, tree = attribute(data["sections"], data["cases"], ids)

    if args.command == "check":
        return cmd_check(attributed, tree, data, ids)
    if args.command == "counts":
        return cmd_counts(attributed, taxonomy, args.csv)
    if args.command == "suggest":
        return cmd_suggest(tree, data, taxonomy, ids, args.sheet)
    return cmd_compare(attributed, tree, data, taxonomy, args.sheet)


if __name__ == "__main__":
    sys.exit(main())
