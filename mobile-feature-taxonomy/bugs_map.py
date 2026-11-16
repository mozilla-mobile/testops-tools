#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml", "requests", "openpyxl"]
# ///
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""Attribute escaped bugs to the feature taxonomy, using <platform>/bugs-map.yml.

A bug takes its component's feature, or the feature of the first title rule that matches inside a component
that mixes features (see android/bugs-map.yml). Escaped = reported by someone outside the team (not a team email
domain, not a bot); duplicates and invalid bugs aren't counted.

Commands:
    check     the map is valid (known IDs, valid regexes) and every component in the window has a decision.
              Exit 1 otherwise. Also shows how precisely the bugs are attributed (L2, L1 only, axis, untriaged).
    counts    escaped bugs per L1/L2 and cross-cutting axis (CSV with --csv).
    compare   counts and per-bug differences against a workbook's "External Bugs" sheet
              (Bug, Summary, Resolution, L1 ID, L2 ID, Counted).

Bugs come from the public Bugzilla REST API (no credentials, so security bugs are not visible).

Usage:
    uv run bugs_map.py android check
    uv run bugs_map.py android --since 2026-01-01 --until 2026-10-27 counts --csv
    uv run bugs_map.py android --cache /tmp/fenix.json compare --sheet firefox_android_feature_mapping_with_L1_and_bugs.xlsx
"""

import argparse
import csv
import datetime
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from feature_map import load_taxonomy  # noqa: E402

BUGZILLA = "https://bugzilla.mozilla.org/rest/bug"
FIELDS = "id,summary,component,creation_time,creator,status,resolution"
# How a bug is attributed.
FEATURE, UNTRIAGED, EXCLUDED, UNKNOWN = "feature", "untriaged", "excluded", "unknown component"
UNTRIAGED_KEY = "UNTRIAGED"


# ---- the map -------------------------------------------------------------------------------------------------

def valid_targets(taxonomy):
    """L2 features, L1 areas and cross-cutting axes."""
    return {k for k, v in taxonomy.items() if v["group"] in ("features", "area", "crosscutting")}


class BugsMap:
    def __init__(self, data, taxonomy):
        self.data = data
        self.targets = valid_targets(taxonomy)
        self.errors = []
        self.components = {}
        for name, rule in (data.get("components") or {}).items():
            kinds = [k for k in ("feature", "untriaged", "excluded") if rule.get(k)]
            if len(kinds) != 1:
                self.errors.append(f"{name}: needs exactly one of feature / untriaged / excluded")
                continue
            titles = []
            for t in rule.get("titles", []):
                try:
                    titles.append((re.compile(t["match"], re.I), t["feature"]))
                except re.error as e:
                    self.errors.append(f"{name}: bad regex {t['match']!r} ({e})")
                    continue
                if t["feature"] not in self.targets:
                    self.errors.append(f"{name}: unknown feature ID {t['feature']} in a title rule")
            if kinds[0] == "feature" and rule["feature"] not in self.targets:
                self.errors.append(f"{name}: unknown feature ID {rule['feature']}")
            if titles and kinds[0] != "feature":
                self.errors.append(f"{name}: title rules only make sense with a feature")
            self.components[name] = (kinds[0], rule.get("feature", ""), titles)
        esc = data.get("escaped", {})
        self.team_domains = tuple("@" + d.lower() for d in esc.get("team_email_domains", []))
        self.bot_suffixes = tuple(s.lower() for s in esc.get("bot_email_suffixes", []))
        self.bot_emails = {e.lower() for e in esc.get("bot_emails", [])}
        self.not_counted = set(data.get("not_counted_resolutions", []))

    @classmethod
    def load(cls, platform, path=None, taxonomy_path=None):
        with open(path or os.path.join(HERE, platform, "bugs-map.yml")) as f:
            return cls(yaml.safe_load(f), load_taxonomy(taxonomy_path))

    def classify(self, bug):
        """(kind, feature_id): kind is FEATURE, UNTRIAGED, EXCLUDED or UNKNOWN."""
        rule = self.components.get(bug["component"])
        if rule is None:
            return UNKNOWN, ""
        kind, feature, titles = rule
        if kind != FEATURE:
            return kind, ""
        summary = bug.get("summary") or ""
        for rx, fid in titles:
            if rx.search(summary):
                return FEATURE, fid
        return FEATURE, feature

    def is_escaped(self, bug):
        email = (bug.get("creator") or "").lower()
        if email in self.bot_emails or email.endswith(self.bot_suffixes):
            return False
        return not email.endswith(self.team_domains)

    def is_counted(self, bug):
        return bug.get("resolution") not in self.not_counted


def attribute(bugs, bugs_map, escaped_only=True):
    """{bug_id: (kind, feature_id)} for the bugs that count: escaped (unless escaped_only is False), not a
    duplicate/invalid, and not in an excluded component."""
    out = {}
    for b in bugs:
        if escaped_only and not bugs_map.is_escaped(b):
            continue
        if not bugs_map.is_counted(b):
            continue
        kind, fid = bugs_map.classify(b)
        if kind != EXCLUDED:
            out[str(b["id"])] = (kind, fid)
    return out


def count(attributed):
    """Counter keyed by L2 ID, "L1:<area>", cross-cutting axis ID and UNTRIAGED. An area counts its L2 bugs and
    the bugs attributed to the area alone."""
    out = Counter()
    for kind, fid in attributed.values():
        if kind != FEATURE:
            out[UNTRIAGED_KEY] += 1
        elif fid.startswith("X."):
            out[fid] += 1
        else:
            out["L1:" + fid.split(".")[0]] += 1
            if "." in fid:
                out[fid] += 1
    return out


def level(kind, fid):
    if kind == UNKNOWN:
        return "unknown component"
    if kind != FEATURE:
        return "untriaged"
    if fid.startswith("X."):
        return "cross-cutting axis"
    return "L2" if "." in fid else "L1 only"


# ---- Bugzilla ------------------------------------------------------------------------------------------------

def fetch(bugs_map, since, until):
    import requests

    params = {"product": bugs_map.data["product"], "bug_type": bugs_map.data.get("bug_type", "defect"),
              "f1": "creation_ts", "o1": "greaterthaneq", "v1": since,
              "f2": "creation_ts", "o2": "lessthaneq", "v2": f"{until} 23:59:59",
              "include_fields": FIELDS, "order": "bug_id"}
    bugs, offset, limit = [], 0, 500
    session = requests.Session()
    while True:
        for attempt in range(5):
            resp = session.get(BUGZILLA, params={**params, "limit": limit, "offset": offset}, timeout=120)
            if resp.status_code != 429:
                break
            time.sleep(int(resp.headers.get("Retry-After", 10)))
        resp.raise_for_status()
        batch = resp.json()["bugs"]
        bugs += batch
        if len(batch) < limit:
            return bugs
        offset += limit


def in_window(bugs, since, until):
    return [b for b in bugs if since <= b["creation_time"][:10] <= until]


def load_bugs(bugs_map, since, until, cache):
    if cache and os.path.exists(cache):
        with open(cache) as f:
            return in_window(json.load(f), since, until)
    print(f"Fetching {bugs_map.data['product']} {bugs_map.data.get('bug_type', 'defect')}s "
          f"{since} → {until} from Bugzilla...", file=sys.stderr)
    bugs = fetch(bugs_map, since, until)
    if cache:
        with open(cache, "w") as f:
            json.dump(bugs, f)
    return bugs


# ---- workbook ------------------------------------------------------------------------------------------------

def read_sheet(path):
    """{bug_id: (kind, feature_id)} for the Counted = Y rows of an "External Bugs" sheet."""
    import openpyxl

    ws = openpyxl.load_workbook(path, read_only=True)["External Bugs"]
    rows = ws.iter_rows(values_only=True)
    header = [str(h).strip() if h else "" for h in next(rows)]
    col = {k: header.index(k) for k in ("Bug", "L1 ID", "L2 ID", "Counted")}
    out = {}
    for r in rows:
        if not r[col["Bug"]] or r[col["Counted"]] != "Y":
            continue
        l2, l1 = r[col["L2 ID"]] or "", r[col["L1 ID"]] or ""
        fid = l2 or l1
        out[str(r[col["Bug"]])] = (FEATURE, fid) if fid else (UNTRIAGED, "")
    return out


# ---- commands ------------------------------------------------------------------------------------------------

def row_keys(taxonomy):
    """[(key, label, name)] in features.yml order, then cross-cutting axes, then untriaged."""
    out, seen = [], set()
    for k, v in taxonomy.items():
        if v["group"] != "features":
            continue
        l1 = k.split(".")[0]
        if l1 not in seen:
            seen.add(l1)
            out.append(("L1:" + l1, l1, v["area"]))
        out.append((k, k, v["name"]))
    out += [(k, k, v["name"]) for k, v in taxonomy.items() if v["group"] == "crosscutting"]
    out.append((UNTRIAGED_KEY, "", "Untriaged (no component yet)"))
    return out


def cmd_check(bugs_map, bugs):
    problems = 0
    if bugs_map.errors:
        problems += len(bugs_map.errors)
        print(f"## Errors in the map ({len(bugs_map.errors)})\n")
        for e in bugs_map.errors:
            print(f"- {e}")
        print()
    unknown = Counter(b["component"] for b in bugs if bugs_map.classify(b)[0] == UNKNOWN)
    if unknown:
        problems += len(unknown)
        print(f"## Components with no decision in the map ({len(unknown)}): add them to bugs-map.yml\n")
        for comp, n in unknown.most_common():
            print(f"- {comp}: {n} bugs")
        print()
    attributed = attribute(bugs, bugs_map)
    levels = Counter(level(*v) for v in attributed.values())
    total = sum(levels.values()) or 1
    print(f"{len(bugs)} bugs in the window; {len(attributed)} escaped and counted:")
    for k in ("L2", "L1 only", "cross-cutting axis", "untriaged", "unknown component"):
        if levels[k]:
            print(f"  {k:<20}{levels[k]:>5}  {100 * levels[k] / total:5.1f}%")
    return 1 if problems else 0


def cmd_counts(bugs_map, bugs, taxonomy, as_csv):
    counts = count(attribute(bugs, bugs_map))
    rows = [(key, label, name, counts.get(key, 0)) for key, label, name in row_keys(taxonomy)]
    if as_csv:
        w = csv.writer(sys.stdout)
        w.writerow(["level", "id", "name", "escaped_bugs"])
        for key, label, name, n in rows:
            lv = "L1" if key.startswith("L1:") else "axis" if key.startswith("X.") else "" if key == UNTRIAGED_KEY \
                else "L2"
            w.writerow([lv, label, name, n])
        return 0
    print("| Feature | Name | Escaped bugs |\n|---|---|--:|")
    for key, label, name, n in rows:
        print(f"| {('**' + label + '**') if key.startswith('L1:') else label} | {name} | {n} |")
    return 0


def cmd_compare(bugs_map, bugs, taxonomy, sheet_path):
    sheet = read_sheet(sheet_path)
    ours_all = attribute(bugs, bugs_map)
    ours, theirs = count(ours_all), count(sheet)
    print("## Escaped bugs per feature (sheet → Bugzilla now)\n")
    print("| Feature | Sheet | Now | Δ |\n|---|--:|--:|--:|")
    for key, label, name in row_keys(taxonomy):
        a, b = theirs.get(key, 0), ours.get(key, 0)
        if a or b:
            shown = f"**{label}**" if key.startswith("L1:") else (label or name)
            print(f"| {shown} | {a} | {b} | {b - a:+d} |")
    by_id = {str(b["id"]): b for b in bugs}
    both = sheet.keys() & ours_all.keys()
    moved = Counter()
    for bid in both:
        a, b = sheet[bid], ours_all[bid]
        # The sheet has no feature for cross-cutting bugs: treat "untriaged" there and an axis here as the same.
        if a != b and not (a[0] == UNTRIAGED and b[1].startswith("X.")):
            moved[(a[1] or "untriaged", b[1] or "untriaged", by_id[bid]["component"])] += 1
    only_sheet, only_now = sheet.keys() - ours_all.keys(), ours_all.keys() - sheet.keys()
    print(f"\nBugs: {len(sheet)} counted in the sheet, {len(ours_all)} now, {len(both)} in both; "
          f"{len(only_now)} only now (filed since, or reopened/re-resolved), "
          f"{len(only_sheet)} only in the sheet (resolved as duplicate/invalid since, or outside the window).")
    if moved:
        print(f"\n## Bugs attributed differently ({sum(moved.values())})\n")
        print("| Bugs | Sheet | Now | Component |\n|--:|---|---|---|")
        for (a, b, comp), n in moved.most_common():
            print(f"| {n} | {a} | {b} | {comp} |")
    return 0


def main(argv=None):
    today = datetime.date.today()
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("platform", choices=["android"])
    parser.add_argument("--since", default=f"{today.year}-01-01", help="first creation date (default: Jan 1)")
    parser.add_argument("--until", default=today.isoformat(), help="last creation date (default: today)")
    parser.add_argument("--cache", help="read the bugs from this JSON file, or write them there")
    parser.add_argument("--map", help="bugs-map.yml to use (default: <platform>/bugs-map.yml)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check")
    p_counts = sub.add_parser("counts")
    p_counts.add_argument("--csv", action="store_true")
    p_compare = sub.add_parser("compare")
    p_compare.add_argument("--sheet", required=True)
    args = parser.parse_args(argv)

    taxonomy = load_taxonomy()
    bugs_map = BugsMap.load(args.platform, args.map)
    if args.command == "check" and bugs_map.errors and not args.cache:
        return cmd_check(bugs_map, [])
    bugs = load_bugs(bugs_map, args.since, args.until, args.cache)
    if args.command == "check":
        return cmd_check(bugs_map, bugs)
    if args.command == "counts":
        return cmd_counts(bugs_map, bugs, taxonomy, args.csv)
    return cmd_compare(bugs_map, bugs, taxonomy, args.sheet)


if __name__ == "__main__":
    sys.exit(main())
