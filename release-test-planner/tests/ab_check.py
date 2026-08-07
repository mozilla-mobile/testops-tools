#!/usr/bin/env python3

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""Prove a change did not alter the analysis it was not meant to alter.

The unit tests say the pieces behave. They cannot say "the Android report is the
same report it was before the iOS port", which is the question a reviewer of a
cross-platform change actually has. This runs the pipeline at two git revisions
over the same range and compares the decisions rather than the bytes.

    # does the current branch still produce the pre-port Android report?
    tests/ab_check.py --before 94ad20f --repo ~/Workspace/firefox \\
        --range "HEAD~300..HEAD"

    # same idea for iOS between two of your own commits
    tests/ab_check.py --before HEAD~1 --platform ios \\
        --repo ~/Workspace/firefox-ios --range "HEAD~120..HEAD"

Exit status is 0 when every decision matches. Additive fields are reported and
tolerated: a new key, or a new per-test field carrying its default, is not a
behaviour change. A changed *value* on a field both revisions have is.

Uses git worktrees, so it never touches your working tree or index.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

# Keys the port legitimately adds. Listed explicitly so that a *different* new
# key still shows up as something to look at.
EXPECTED_NEW = {
    "meta": {"platform", "platform_label", "has_factories", "platform_notes",
             "report_title"},
    "inventory": {"platform", "missing_roots", "test_plans"},
    "factories": {"platform", "has_candidate_space", "reason"},
    "_root": {"testrail"},
}

# Sections whose equality is the actual claim: if these match, the tool reached
# the same conclusions.
DECISION_SECTIONS = ("changes", "attribution", "risk", "matrix", "factories")


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw)


def analyse(tool_root: str, args, out_dir: str) -> dict:
    cmd = [sys.executable, os.path.join(tool_root, "plan.py"), "analyze",
           "--repo", args.repo, "--range", args.range, "--out", out_dir]
    if args.budget:
        cmd += ["--budget", str(args.budget)]
    # `--platform` does not exist before the port; omit it for the default so the
    # older revision can still be driven by this script.
    if args.platform != "android":
        cmd += ["--platform", args.platform]
    if args.testrail_export:
        cmd += ["--testrail-export"] + args.testrail_export
    run(cmd, cwd=tool_root)
    with open(os.path.join(out_dir, "report.json")) as fh:
        return json.load(fh)


def test_key(entry: dict):
    return (entry.get("class_name"), entry.get("name"), entry.get("feature_id"))


def compare(before: dict, after: dict) -> int:
    problems = []

    new_root = set(after) - set(before)
    unexpected = new_root - EXPECTED_NEW["_root"]
    print("new top-level keys: %s" % (sorted(new_root) or "none"))
    if unexpected:
        problems.append("unexpected new top-level keys: %s" % sorted(unexpected))
    missing_root = set(before) - set(after)
    if missing_root:
        problems.append("top-level keys disappeared: %s" % sorted(missing_root))

    for section in ("meta", "inventory", "factories"):
        if section not in before or section not in after:
            continue
        added = set(after[section]) - set(before[section])
        unexpected = added - EXPECTED_NEW.get(section, set())
        changed = [k for k in before[section]
                   if k in after[section]
                   and before[section][k] != after[section][k]
                   and k not in ("repo", "catalog")]
        print("%-11s added %-42s changed %s"
              % (section, sorted(added) or "none", changed or "none"))
        if unexpected:
            problems.append("%s: unexpected new keys %s" % (section, sorted(unexpected)))
        if changed:
            problems.append("%s: values changed for %s" % (section, changed))

    for section in DECISION_SECTIONS:
        if section not in before:
            continue
        a = json.dumps(before[section], sort_keys=True)
        b = json.dumps(after[section], sort_keys=True)
        if section == "factories":
            continue        # compared key-wise above; it gains keys by design
        same = a == b
        print("%-11s identical: %s" % (section, same))
        if not same:
            problems.append("%s differs" % section)

    pa, pb = before.get("plan", {}), after.get("plan", {})
    if pa and pb:
        print("plan        totals identical: %s" % (pa["totals"] == pb["totals"]))
        if pa["totals"] != pb["totals"]:
            problems.append("plan totals differ")
        for name in ("selected", "redundant"):
            la, lb = pa.get(name) or [], pb.get(name) or []
            same = [test_key(t) for t in la] == [test_key(t) for t in lb]
            print("plan        %-9s same tests, same order: %s (%d)"
                  % (name, same, len(lb)))
            if not same:
                problems.append("plan %s list differs" % name)
            # A field both revisions carry must not change value.
            for x, y in zip(la, lb):
                for key in set(x) & set(y):
                    if x[key] != y[key]:
                        problems.append(
                            "plan %s: %s changed on %s" % (name, key, test_key(x)))
                        break
        for name in ("gaps",):
            same = (json.dumps(pa.get(name), sort_keys=True)
                    == json.dumps(pb.get(name), sort_keys=True))
            print("plan        %-9s identical: %s" % (name, same))
            if not same:
                problems.append("plan %s differs" % name)

    print()
    if problems:
        print("DIFFERENT - %d problem(s):" % len(problems))
        for p in problems:
            print("  - %s" % p)
        return 1
    print("SAME - every decision matches; differences are additive only.")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--before", required=True,
                   help="git revision to compare against (e.g. 94ad20f, HEAD~1)")
    p.add_argument("--repo", required=True, help="app checkout to analyse")
    p.add_argument("--range", default="HEAD~300..HEAD")
    p.add_argument("--platform", default="android")
    p.add_argument("--budget", type=float, default=240)
    p.add_argument("--testrail-export", nargs="*", default=None)
    args = p.parse_args()
    args.repo = os.path.abspath(os.path.expanduser(args.repo))

    tests_dir = os.path.dirname(os.path.abspath(__file__))
    tool_root = os.path.dirname(tests_dir)
    repo_root = run(["git", "rev-parse", "--show-toplevel"],
                    cwd=tool_root).stdout.strip()
    rel_tool = os.path.relpath(tool_root, repo_root)

    tmp = tempfile.mkdtemp(prefix="rtp-ab-")
    worktree = os.path.join(tmp, "before")
    try:
        run(["git", "worktree", "add", "-q", "--detach", worktree, args.before],
            cwd=repo_root)
        print("comparing %s (before) against the working tree (after)\n"
              % args.before)
        before = analyse(os.path.join(worktree, rel_tool), args,
                         os.path.join(tmp, "out-before"))
        after = analyse(tool_root, args, os.path.join(tmp, "out-after"))
        return compare(before, after)
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", worktree],
                       cwd=repo_root, capture_output=True)
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
