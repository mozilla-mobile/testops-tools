#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml", "requests"]
# ///
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""Escaped bugs per L1/L2 feature, iOS and Android, for the feature health dashboard.

Bugs are attributed with ../mobile-feature-taxonomy/bugs_map.py (Bugzilla components and title rules on Android,
a decision per GitHub issue on iOS) and cover the current year so far: created from January 1 to today. Bugs are
public on Bugzilla and GitHub, so unlike TestRail the data file lists them: ID, title, link, state, created date,
and which feature they count under, so the dashboard can show the bugs behind each number.

Normally run through collect.py, which builds every data file of the dashboard. On its own:
    python collect_bugs.py --out site/data/bugs.json
"""

import argparse
import json
import os
import sys
import urllib.parse
from datetime import date, datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "mobile-feature-taxonomy"))

import bugs_map  # noqa: E402

JSON_SCHEMA_VERSION = 1
PLATFORMS = ("ios", "android")
BUGZILLA = "https://bugzilla.mozilla.org"
CLOSED_STATUSES = {"RESOLVED", "VERIFIED", "CLOSED"}


def is_open(m, bug):
    if m.source == "github":
        return bug.get("state") == "open"
    return (bug.get("status") or "").upper() not in CLOSED_STATUSES


def bug_url(m, bug):
    if m.source == "github":
        return f"https://github.com/{m.data['repo']}/issues/{bug['id']}"
    return f"{BUGZILLA}/show_bug.cgi?id={bug['id']}"


def query_url(m, since):
    """The tracker's own search for this year's escaped bugs. Approximate: Bugzilla can't express the title
    rules, and GitHub can't filter out authors from the org, so its search also shows team-filed issues."""
    if m.source == "github":
        labels = ",".join(f'"{lab}"' for lab in sorted(m.bug_labels))
        q = f"is:issue label:{labels} created:>={since}"
        return f"https://github.com/{m.data['repo']}/issues?" + urllib.parse.urlencode({"q": q})
    excluded = sorted(c for c, (kind, _, _) in m.components.items() if kind == bugs_map.EXCLUDED)
    params = {"product": m.data["product"], "bug_type": m.data.get("bug_type", "defect"),
              "chfield": "[Bug creation]", "chfieldfrom": since, "chfieldto": "Now"}
    filters = [("reporter", "notsubstring", d) for d in m.team_domains + m.bot_suffixes]
    filters += [("reporter", "notequals", e) for e in sorted(m.bot_emails)]
    filters += [("resolution", "notequals", r) for r in sorted(m.not_counted)]
    filters += [("component", "notequals", c) for c in excluded]
    for i, (f, o, v) in enumerate(filters, 1):
        params.update({f"f{i}": f, f"o{i}": o, f"v{i}": v})
    return f"{BUGZILLA}/buglist.cgi?" + urllib.parse.urlencode(params)


def assigned_by(m, bug, kind, fid):
    """How the bug got its feature, to make reviewing easier."""
    if m.source == "github":
        return "decision" if kind == bugs_map.FEATURE else "waiting for a decision"
    if kind != bugs_map.FEATURE:
        return "untriaged"
    default = m.components.get(bug.get("component"), (None, "", []))[1]
    return "component" if fid == default else "title rule"


def keys_for(kind, fid):
    """Rows a bug counts in: its L2 and its area, an axis, or "untriaged"."""
    if kind != bugs_map.FEATURE:
        return [bugs_map.UNTRIAGED_KEY]
    if fid.startswith("X."):
        return [fid]
    return ["L1:" + fid.split(".")[0]] + ([fid] if "." in fid else [])


def platform_bugs(m, bugs, since):
    attributed = bugs_map.attribute(bugs, m)
    by_id = {str(b["id"]): b for b in bugs}
    features = {}
    for bid, (kind, fid) in attributed.items():
        for k in keys_for(kind, fid):
            features.setdefault(k, []).append(bid)
    listed = {}
    for bid in sorted(attributed, key=int):
        b = by_id[bid]
        kind, fid = attributed[bid]
        listed[bid] = {"title": b.get("summary") or "", "url": bug_url(m, b), "created": b["creation_time"][:10],
                       "feature": fid if kind == bugs_map.FEATURE else "", "how": assigned_by(m, b, kind, fid),
                       "open": is_open(m, b), "state": (b.get("state") or b.get("status") or "").lower(),
                       "resolution": b.get("resolution") or "", "component": b.get("component") or ""}
    return {
        "source": m.source,
        "query_url": query_url(m, since),
        "list_url": f"{BUGZILLA}/buglist.cgi?bug_id=" if m.source != "github" else None,
        "escaped": len(attributed),
        "undecided": sum(1 for kind, _ in attributed.values() if kind == bugs_map.UNKNOWN),
        "features": {k: sorted(v, key=int) for k, v in sorted(features.items())},
        "bugs": listed,
    }


def build(cache_dir=None, today=None):
    """Fetch this year's bugs for both platforms (cache_dir/<platform>.json is reused while it covers the window)
    and return the data file's content."""
    today = today or date.today()
    since, until = f"{today.year}-01-01", today.isoformat()
    out = {"schema_version": JSON_SCHEMA_VERSION,
           "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "since": since, "until": until, "platforms": {}}
    for p in PLATFORMS:
        m = bugs_map.BugsMap.load(p)
        if m.errors:
            raise ValueError(f"{p}/bugs-map.yml has {len(m.errors)} errors: run bugs_map.py {p} check")
        cache = os.path.join(cache_dir, f"{p}.json") if cache_dir else None
        out["platforms"][p] = platform_bugs(m, bugs_map.load_bugs(m, since, until, cache), since)
    return out


def summary(out):
    lines = []
    for p, c in out["platforms"].items():
        n_open = sum(b["open"] for b in c["bugs"].values())
        lines.append(f"{p}: {c['escaped']} escaped bugs {out['since']} → {out['until']} ({n_open} open)"
                     + (f", {c['undecided']} waiting for a feature decision" if c["undecided"] else ""))
    return lines


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", default=os.path.join(HERE, "site", "data", "bugs.json"))
    parser.add_argument("--cache-dir", help="reuse fetched bugs from <dir>/<platform>.json while they cover the window")
    args = parser.parse_args(argv)
    out = build(args.cache_dir)
    print("\n".join(summary(out)))
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
        f.write("\n")
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
