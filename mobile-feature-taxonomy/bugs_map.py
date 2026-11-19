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

Android (Bugzilla): a bug takes its component's feature, or the feature of the first title rule that matches inside
a component that mixes features. Escaped = not reported from a team email domain or by a bot; duplicates and
invalid bugs aren't counted.

iOS (GitHub issues): issues with a bug label, opened by someone outside the org. There are no feature labels and
title rules are too imprecise to decide alone, so a person decides each bug's feature; title rules only suggest
one. Undecided bugs count as untriaged.

Tags on the bug itself win over everything else, so a person can set or correct a bug's feature where they triage:
  GitHub issue:  a comment by an org member or collaborator with a line "Feature affected: <name> (UI.TB)"
                 ("Feature:" works too; the latest such comment counts)
  Bugzilla bug:  "[feature:UI.TB]" in the whiteboard, or that line in a comment from a team email domain
                 (the whiteboard wins over comments)
Only the ID counts (the name is for people); "excluded" excludes the bug. ios/bugs-map.yml `issues:` holds the
decisions made before tags existed.

Commands:
    check     the map is valid (known IDs, valid regexes) and every bug in the window has a decision: its
              component is in the map (Android), or the issue is (iOS, with a suggested line to paste).
              Exit 1 otherwise. Also shows how precisely the bugs are attributed (L2, L1 only, axis, untriaged).
    counts    escaped bugs per L1/L2 and cross-cutting axis (CSV with --csv).
    compare   counts and per-bug differences against a workbook's "External Bugs" sheet
              (Android: Bug, L1 ID, L2 ID, Counted; iOS: Issue, L1 ID, L2 ID, Memory leak).

Android bugs come from the public Bugzilla REST API (no credentials, so security bugs are not visible). iOS issues
come from the GitHub API with GITHUB_TOKEN / GH_TOKEN, or the `gh` CLI's token when neither is set.

By default every run covers the current year so far: bugs created from January 1 to today.

Usage:
    uv run bugs_map.py android check
    uv run bugs_map.py ios check
    uv run bugs_map.py android counts --csv                                  # this year, up to today
    uv run bugs_map.py android --since 2026-01-01 --until 2026-10-27 counts  # a fixed window
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
GITHUB_API = "https://api.github.com"
FIELDS = "id,summary,component,creation_time,creator,status,resolution,whiteboard"
CACHE_SCHEMA = 2   # bump when fetched bug records change shape, so old caches are refetched
# How a bug is attributed.
# UNKNOWN = needs a decision in the map: an unlisted component (Android) or an undecided issue (iOS).
FEATURE, UNTRIAGED, EXCLUDED, UNKNOWN = "feature", "untriaged", "excluded", "needs a decision"
UNTRIAGED_KEY = "UNTRIAGED"
INVALID = "invalid tag"

# "Feature affected: Toolbar & address bar layout (UI.TB)" or "Feature: UI.TB", on a line of its own.
TAG_LINE_RE = re.compile(r"^[\W_]*feature(?:\s+affected)?[\W_]*:[\s*_]*(.+?)[\s*_]*$", re.I | re.M)
WHITEBOARD_RE = re.compile(r"\[feature\s*:\s*([^\]]+)\]", re.I)
DOTTED_RE = re.compile(r"\b[A-Z]{1,8}\.[A-Z0-9]{2,10}\b")


def parse_tag(text, targets):
    """(kind, feature_id) from what follows "Feature affected:" / "[feature:", or None if it isn't a tag.

    The ID is taken from the last (parenthesised) part, else from a dotted ID anywhere, else the text itself.
    A dotted word that isn't a feature ID is a typo: (INVALID, word). Plain prose ("Feature: works for me") is None.
    """
    rest = (text or "").strip()
    if not rest:
        return None
    paren = [p.strip() for p in re.findall(r"\(([^()]*)\)", rest)]
    if paren and paren[-1] in targets:
        return FEATURE, paren[-1]
    dotted = sorted({d for d in DOTTED_RE.findall(rest) if d in targets})
    if len(dotted) == 1:
        return FEATURE, dotted[0]
    if rest in targets:
        return FEATURE, rest
    if re.search(r"\bexclude(d)?\b", rest, re.I):
        return EXCLUDED, ""
    bad = [d for d in DOTTED_RE.findall(rest) if d not in targets] or \
          [p for p in paren if re.fullmatch(r"[A-Z]{1,8}(\.[A-Z0-9]{2,10})?", p)]
    if len(dotted) > 1:
        return INVALID, ", ".join(dotted)
    if bad:
        return INVALID, bad[0]
    return None


def comment_tag(text):
    """The text after "Feature affected:" in the last such line of a comment, or None."""
    found = TAG_LINE_RE.findall(text or "")
    return found[-1] if found else None


# ---- the map -------------------------------------------------------------------------------------------------

def valid_targets(taxonomy):
    """L2 features, L1 areas and cross-cutting axes."""
    return {k for k, v in taxonomy.items() if v["group"] in ("features", "area", "crosscutting")}


class BugsMap:
    def __init__(self, data, taxonomy):
        self.data = data
        self.targets = valid_targets(taxonomy)
        self.names = {k: (v["name"] if v["group"] != "area" else v["area"]) for k, v in taxonomy.items()}
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
        self.source = data.get("source", "bugzilla")
        self.hints = []
        for t in data.get("title_hints", []):
            try:
                self.hints.append((re.compile(t["match"], re.I), t["feature"]))
            except re.error as e:
                self.errors.append(f"title hint: bad regex {t['match']!r} ({e})")
                continue
            if t["feature"] not in self.targets:
                self.errors.append(f"title hint: unknown feature ID {t['feature']}")
        self.issues = {}
        for number, decision in (data.get("issues") or {}).items():
            if isinstance(decision, dict) and decision.get("excluded"):
                self.issues[str(number)] = (EXCLUDED, "")
            elif isinstance(decision, str) and decision in self.targets:
                self.issues[str(number)] = (FEATURE, decision)
            else:
                self.errors.append(f"issue {number}: needs a feature ID or {{excluded: reason}}, got {decision!r}")
        self.bug_labels = set(data.get("bug_labels", []))
        self.spam_phrases = tuple(p.lower() for p in data.get("spam_phrases", []))
        esc = data.get("escaped", {})
        self.team_associations = set(esc.get("team_associations", []))
        self.team_domains = tuple("@" + d.lower() for d in esc.get("team_email_domains", []))
        self.bot_suffixes = tuple(s.lower() for s in esc.get("bot_email_suffixes", []))
        self.bot_emails = {e.lower() for e in esc.get("bot_emails", [])}
        self.not_counted = set(data.get("not_counted_resolutions", []))

    @classmethod
    def load(cls, platform, path=None, taxonomy_path=None):
        with open(path or os.path.join(HERE, platform, "bugs-map.yml")) as f:
            return cls(yaml.safe_load(f), load_taxonomy(taxonomy_path))

    def tag(self, bug):
        """(kind, feature_id) from the bug's own tag (comment or whiteboard), or None."""
        return parse_tag(bug.get("tag_text"), self.targets) if bug.get("tag_text") else None

    def classify(self, bug):
        """(kind, feature_id): kind is FEATURE, UNTRIAGED, EXCLUDED or UNKNOWN. A valid tag on the bug wins."""
        tag = self.tag(bug)
        if tag and tag[0] in (FEATURE, EXCLUDED):
            return tag
        if self.source == "github":
            return self.issues.get(str(bug["id"]), (UNKNOWN, ""))
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

    def assigned_by(self, bug):
        """How the bug got (or didn't get) its feature, following the same order as classify()."""
        tag = self.tag(bug)
        if tag and tag[0] in (FEATURE, EXCLUDED):
            return "tag"
        if self.source == "github":
            return "decision" if str(bug["id"]) in self.issues else "waiting for a decision"
        rule = self.components.get(bug.get("component"))
        if rule is None:
            return "needs a decision"
        if rule[0] != FEATURE:
            return rule[0]
        return "title rule" if self.classify(bug)[1] != rule[1] else "component"

    def suggest(self, bug):
        """A feature ID from the title hints, or "" (suggestions for new decisions only)."""
        for rx, fid in self.hints:
            if rx.search(bug.get("summary") or ""):
                return fid
        return ""

    def is_spam(self, title):
        s = (title or "").strip().lower()
        if any(p in s for p in self.spam_phrases):
            return True
        if re.search(r"\S+@\S+\.\S+|https?://", s) and len(s.split()) <= 3:
            return True
        return len(s.split()) == 1 and len(s) <= 12

    def is_escaped(self, bug):
        if self.source == "github":
            return bug.get("assoc") not in self.team_associations and not self.is_spam(bug.get("summary"))
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
        return "needs a decision"
    if kind != FEATURE:
        return "untriaged"
    if fid.startswith("X."):
        return "cross-cutting axis"
    return "L2" if "." in fid else "L1 only"


def get_with_retry(session, url, params=None, attempts=5):
    """GET, retrying rate limits (429, GitHub's 403 with no quota left) and transient 5xx errors."""
    for attempt in range(attempts):
        resp = session.get(url, params=params, timeout=120)
        limited = resp.status_code == 429 or (resp.status_code == 403
                                              and resp.headers.get("X-RateLimit-Remaining") == "0")
        if not (limited or resp.status_code >= 500) or attempt == attempts - 1:
            resp.raise_for_status()
            return resp
        time.sleep(int(resp.headers.get("Retry-After", 0)) or 5 * 2 ** attempt)


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
        resp = get_with_retry(session, BUGZILLA, {**params, "limit": limit, "offset": offset})
        batch = resp.json()["bugs"]
        bugs += batch
        if len(batch) < limit:
            break
        offset += limit
    add_bugzilla_tags(bugs_map, bugs, session)
    return bugs


def add_bugzilla_tags(bugs_map, bugs, session, chunk=50):
    """Set bug["tag_text"] from "[feature:…]" in the whiteboard, else from the latest team comment with a
    "Feature affected:" line. Only escaped, counted bugs are looked at (the others never show)."""
    wanted = [b for b in bugs if bugs_map.is_escaped(b) and bugs_map.is_counted(b)]
    for b in wanted:
        m = WHITEBOARD_RE.search(b.get("whiteboard") or "")
        if m:
            b["tag_text"], b["tag_source"] = m.group(1).strip(), "whiteboard"
    todo = [b for b in wanted if "tag_text" not in b]
    by_id = {str(b["id"]): b for b in todo}
    for i in range(0, len(todo), chunk):
        ids = [str(b["id"]) for b in todo[i:i + chunk]]
        # One bug in the path, the rest as repeated ?ids= (Bugzilla rejects a comma-separated list).
        resp = get_with_retry(session, f"{BUGZILLA}/{ids[0]}/comment", [("ids", i) for i in ids[1:]] or None)
        for bid, entry in resp.json().get("bugs", {}).items():
            for c in sorted(entry.get("comments", []), key=lambda c: c.get("creation_time", "")):
                author = (c.get("creator") or "").lower()
                if not author.endswith(bugs_map.team_domains):
                    continue
                text = comment_tag(c.get("text"))
                if text and parse_tag(text, bugs_map.targets) and bid in by_id:
                    by_id[bid]["tag_text"], by_id[bid]["tag_source"] = text, "comment"


def github_token():
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        return token
    import subprocess
    try:
        return subprocess.run(["gh", "auth", "token"], check=True, capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def fetch_github(bugs_map, since, until):
    """Bug-labelled issues (not PRs) created in the window, as {id, summary, creation_time, creator, assoc, ...}."""
    import requests

    session = requests.Session()
    session.headers["Accept"] = "application/vnd.github+json"
    token = github_token()
    if token:
        session.headers["Authorization"] = f"Bearer {token}"
    found = {}
    for label in sorted(bugs_map.bug_labels):
        # `since` filters on last update, which is always on or after creation: filter on creation below.
        url = f"{GITHUB_API}/repos/{bugs_map.data['repo']}/issues"
        params = {"labels": label, "state": "all", "since": f"{since}T00:00:00Z", "per_page": 100}
        while url:
            resp = get_with_retry(session, url, params)
            for i in resp.json():
                if "pull_request" in i or not since <= i["created_at"][:10] <= until:
                    continue
                found[i["number"]] = {
                    "id": i["number"], "summary": i["title"], "creation_time": i["created_at"],
                    "creator": i["user"]["login"], "assoc": i["author_association"], "state": i["state"],
                    "labels": [lab["name"] for lab in i["labels"]], "component": "", "resolution": "",
                    "n_comments": i.get("comments", 0),
                }
            url, params = resp.links.get("next", {}).get("url"), None
    bugs = sorted(found.values(), key=lambda b: b["id"])
    # Tags: the latest "Feature affected:" comment by an org member or collaborator, on escaped issues only.
    for b in bugs:
        if not b.pop("n_comments") or not bugs_map.is_escaped(b):
            continue
        url = f"{GITHUB_API}/repos/{bugs_map.data['repo']}/issues/{b['id']}/comments"
        params = {"per_page": 100}
        while url:
            resp = get_with_retry(session, url, params)
            for c in resp.json():
                if c.get("author_association") not in bugs_map.team_associations:
                    continue
                text = comment_tag(c.get("body"))
                if text and parse_tag(text, bugs_map.targets):
                    b["tag_text"], b["tag_source"] = text, "comment"
            url, params = resp.links.get("next", {}).get("url"), None
    return bugs


def in_window(bugs, since, until):
    return [b for b in bugs if since <= b["creation_time"][:10] <= until]


def load_bugs(bugs_map, since, until, cache):
    """Bugs created in [since, until]. A cache is reused only if it covers that window, so a cache saved on an
    earlier day is refreshed instead of silently freezing the numbers."""
    if cache and os.path.exists(cache):
        with open(cache) as f:
            cached = json.load(f)
        if isinstance(cached, list):  # a plain list of bugs (e.g. an older export): trust it, filter by date
            return in_window(cached, since, until)
        if cached.get("schema") == CACHE_SCHEMA and cached.get("since", "9999") <= since \
                and until <= cached.get("until", ""):
            return in_window(cached["bugs"], since, until)
    if bugs_map.source == "github":
        print(f"Fetching {bugs_map.data['repo']} bug issues {since} → {until} from GitHub...", file=sys.stderr)
        bugs = fetch_github(bugs_map, since, until)
    else:
        print(f"Fetching {bugs_map.data['product']} {bugs_map.data.get('bug_type', 'defect')}s "
              f"{since} → {until} from Bugzilla...", file=sys.stderr)
        bugs = fetch(bugs_map, since, until)
    if cache:
        with open(cache, "w") as f:
            json.dump({"schema": CACHE_SCHEMA, "since": since, "until": until, "bugs": bugs}, f)
    return bugs


# ---- workbook ------------------------------------------------------------------------------------------------

def read_sheet(path):
    """{bug_id: (kind, feature_id)} for the counted rows of an "External Bugs" sheet: Android sheets have
    Bug / Counted (Y), iOS sheets have Issue / Memory leak (Y = not counted)."""
    import openpyxl

    ws = openpyxl.load_workbook(path, read_only=True)["External Bugs"]
    rows = ws.iter_rows(values_only=True)
    header = [str(h).strip() if h else "" for h in next(rows)]
    id_col = header.index("Bug") if "Bug" in header else header.index("Issue")
    col = {k: header.index(k) for k in ("L1 ID", "L2 ID")}
    counted = (lambda r: r[header.index("Counted")] == "Y") if "Counted" in header else \
        (lambda r: r[header.index("Memory leak")] != "Y")
    out = {}
    for r in rows:
        if not r[id_col] or not counted(r):
            continue
        l2, l1 = r[col["L2 ID"]] or "", r[col["L1 ID"]] or ""
        fid = l2 or l1
        out[str(r[id_col])] = (FEATURE, fid) if fid else (UNTRIAGED, "")
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


def cmd_check(bugs_map, bugs, window=""):
    problems = 0
    if bugs_map.errors:
        problems += len(bugs_map.errors)
        print(f"## Errors in the map ({len(bugs_map.errors)})\n")
        for e in bugs_map.errors:
            print(f"- {e}")
        print()
    counted = [b for b in bugs if bugs_map.is_escaped(b) and bugs_map.is_counted(b)]
    invalid = [(b, bugs_map.tag(b)[1]) for b in counted if bugs_map.tag(b) and bugs_map.tag(b)[0] == INVALID]
    if invalid:
        problems += len(invalid)
        print(f"## Bugs whose feature tag isn't a feature ID ({len(invalid)}): fix the comment / whiteboard\n")
        for b, word in invalid:
            print(f"- {b['id']} ({b.get('tag_source', 'tag')}): `{word}` in \"{b['tag_text'][:80]}\"")
        print()
    if bugs_map.source == "github":
        undecided = [b for b in counted if bugs_map.classify(b)[0] == UNKNOWN]
        if undecided:
            problems += len(undecided)
            print(f"## Escaped bugs with no feature yet ({len(undecided)}): review the suggestion, then comment on "
                  f"the issue\n")
            for b in undecided:
                hint = bugs_map.suggest(b)
                title = (b["summary"] or "").replace("\n", " ")[:90]
                line = f"Feature affected: {bugs_map.names[hint]} ({hint})" if hint else "Feature affected: ? (TODO)"
                print(f"- #{b['id']} {title}\n    {line}")
            print()
    unknown = Counter(b["component"] for b in bugs
                      if bugs_map.source != "github" and bugs_map.classify(b)[0] == UNKNOWN)
    if unknown:
        problems += len(unknown)
        print(f"## Components with no decision in the map ({len(unknown)}): add them to bugs-map.yml\n")
        for comp, n in unknown.most_common():
            print(f"- {comp}: {n} bugs")
        print()
    attributed = attribute(bugs, bugs_map)
    levels = Counter(level(*v) for v in attributed.values())
    total = sum(levels.values()) or 1
    tagged = sum(1 for b in counted if bugs_map.tag(b) and bugs_map.tag(b)[0] in (FEATURE, EXCLUDED))
    print(f"{len(bugs)} bugs created {window}; {len(attributed)} escaped and counted"
          + (f" ({tagged} with a feature tag on the bug)" if tagged else "") + ":")
    for k in ("L2", "L1 only", "cross-cutting axis", "untriaged", "needs a decision"):
        if levels[k]:
            print(f"  {k:<20}{levels[k]:>5}  {100 * levels[k] / total:5.1f}%")
    return 1 if problems else 0


def cmd_counts(bugs_map, bugs, taxonomy, as_csv, window=""):
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
    print(f"Escaped bugs created {window}\n")
    print("| Feature | Name | Escaped bugs |\n|---|---|--:|")
    for key, label, name, n in rows:
        print(f"| {('**' + label + '**') if key.startswith('L1:') else label} | {name} | {n} |")
    return 0


def cmd_compare(bugs_map, bugs, taxonomy, sheet_path, window=""):
    sheet = read_sheet(sheet_path)
    ours_all = attribute(bugs, bugs_map)
    ours, theirs = count(ours_all), count(sheet)
    print(f"## Escaped bugs per feature, created {window} (sheet → now)\n")
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
            moved[(a[1] or "untriaged", b[1] or "untriaged", by_id[bid]["component"] or f"#{bid}")] += 1
    only_sheet, only_now = sheet.keys() - ours_all.keys(), ours_all.keys() - sheet.keys()
    print(f"\nBugs: {len(sheet)} counted in the sheet, {len(ours_all)} now, {len(both)} in both; "
          f"{len(only_now)} only now (filed since, or reopened/re-resolved), "
          f"{len(only_sheet)} only in the sheet (resolved as duplicate/invalid since, or outside the window).")
    if moved:
        print(f"\n## Bugs attributed differently ({sum(moved.values())})\n")
        print(f"| Bugs | Sheet | Now | {'Component' if bugs_map.source != 'github' else 'Issue'} |\n|--:|---|---|---|")
        for (a, b, comp), n in moved.most_common():
            print(f"| {n} | {a} | {b} | {comp} |")
    return 0


def main(argv=None):
    today = datetime.date.today()
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("platform", choices=["android", "ios"])
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
    if args.since > args.until:
        parser.error(f"--since {args.since} is after --until {args.until}")
    bugs = load_bugs(bugs_map, args.since, args.until, args.cache)
    window = f"{args.since} → {args.until}"
    if args.command == "check":
        return cmd_check(bugs_map, bugs, window)
    if args.command == "counts":
        return cmd_counts(bugs_map, bugs, taxonomy, args.csv, window)
    return cmd_compare(bugs_map, bugs, taxonomy, args.sheet, window)


if __name__ == "__main__":
    sys.exit(main())
