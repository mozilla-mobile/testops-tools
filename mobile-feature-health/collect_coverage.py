#!/usr/bin/env python3
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""Unit-test line coverage per L1/L2 feature for the feature health dashboard (iOS for now).

iOS: the `unit-test-coverage.json` artifact (`xcrun xccov view --report --json`) of the latest run of the Bitrise
workflow firefox_unit_tests_ios_versions (weekly, on the app's default Xcode stack, iOS 27 simulator), attributed
to features with ../mobile-feature-taxonomy/ios/feature-map.yml. The latest finished run that has the artifact is
used whatever its status: a failing test step on another iOS version doesn't invalidate the coverage. Only line
counts (per feature and per source file), the names of the functions with the most uncovered lines and build
metadata are written; URLs and tokens never reach the output file or the log.

Needs BITRISE_TOKEN (can read the firefox-ios app) and BITRISE_APP_SLUG. BITRISE_COVERAGE_BRANCH picks the branch
(default main), e.g. to try a workflow change from a branch.

Normally run through collect.py, which builds every data file of the dashboard. On its own:
    python collect_coverage.py --out site/data/coverage.json
    python collect_coverage.py --cache-dir /tmp/cov --branch my-branch
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
TAXONOMY_DIR = os.path.join(os.path.dirname(HERE), "mobile-feature-taxonomy")
sys.path.insert(0, TAXONOMY_DIR)

from feature_map import FeatureMap, coverage_from_xccov  # noqa: E402

JSON_SCHEMA_VERSION = 1
API = "https://api.bitrise.io/v0.1"
WORKFLOW = "firefox_unit_tests_ios_versions"
ARTIFACT = "unit-test-coverage.json"
LOOKBACK = 10   # builds of the workflow to look through for one with the artifact


def _get(path, token, params=None):
    r = requests.get(API + path, headers={"Authorization": token}, params=params, timeout=60)
    r.raise_for_status()
    return r.json()


def fetch_report(token, app, branch, workflow=WORKFLOW):
    """(xccov report, build metadata) of the newest finished build of `workflow` on `branch` with the artifact."""
    builds = _get(f"/apps/{app}/builds", token, {"workflow": workflow, "branch": branch, "limit": LOOKBACK})["data"]
    for b in builds:   # newest first
        if not b.get("finished_at"):
            continue
        artifacts = _get(f"/apps/{app}/builds/{b['slug']}/artifacts", token)["data"]
        artifact = next((a for a in artifacts if a["title"] == ARTIFACT), None)
        if not artifact:
            continue
        url = _get(f"/apps/{app}/builds/{b['slug']}/artifacts/{artifact['slug']}", token)["data"]["expiring_download_url"]
        r = requests.get(url, timeout=120)
        r.raise_for_status()
        build = {"number": b["build_number"], "url": f"https://app.bitrise.io/build/{b['slug']}", "workflow": workflow,
                 "branch": b.get("branch"), "commit": (b.get("commit_hash") or "")[:12], "finished_at": b["finished_at"],
                 "stack": b.get("stack_identifier"), "status": b.get("status_text")}
        return r.json(), build
    raise LookupError(f"no finished {workflow} build on {branch} with a {ARTIFACT} artifact in the last {LOOKBACK}")


def platform_coverage(report, build, fm):
    """{"build", "files", "outside_roots", "unmapped", "ambiguous", "features": {key: {"executable", "covered"}},
    "totals", "by_file"}.

    Keys are L2 IDs, area-only IDs, "L1:<area>" (the whole area), SHARED.*, EXCLUDED, UNMAPPED (no rule matches) and
    AMBIGUOUS (two rules tie). totals["features"] adds up the area rows (feature code, what the scorecards report);
    totals["shared"] the SHARED.* buckets. by_file lists each file's lines per feature and its functions with the most
    uncovered lines (see coverage_from_xccov), most uncovered first, for the dashboard's per-file tab.
    """
    result = coverage_from_xccov(fm, report)
    features = result["features"]

    def total(keys):
        keys = list(keys)
        return {"executable": sum(features[k]["executable"] for k in keys),
                "covered": sum(features[k]["covered"] for k in keys)}

    return {
        "build": build,
        "files": result["files"],
        "outside_roots": result["outside_roots"],
        "unmapped": sorted(result["unmapped"]),
        "ambiguous": sorted(result["ambiguous"], key=lambda a: a["path"]),
        "features": dict(sorted(features.items())),
        "totals": {"features": total(k for k in features if k.startswith("L1:")),
                   "shared": total(k for k in features if k.startswith("SHARED."))},
        "by_file": sorted(result["by_file"], key=lambda e: (e["feature"], e["covered"] - e["executable"], e["path"])),
    }


def collect(report, build, fm):
    return {
        "schema_version": JSON_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "platforms": {"ios": platform_coverage(report, build, fm)},
    }


def build(cache_dir=None, branch=None):
    """Fetch the latest iOS report (or read it from cache_dir/ios.json) and return the data file's content."""
    branch = branch or os.environ.get("BITRISE_COVERAGE_BRANCH") or "main"
    cache = os.path.join(cache_dir, "ios.json") if cache_dir else None
    if cache and os.path.exists(cache):
        with open(cache) as f:
            cached = json.load(f)
        report, build_meta = cached["report"], cached["build"]
    else:
        token, app = os.environ.get("BITRISE_TOKEN"), os.environ.get("BITRISE_APP_SLUG")
        if not token or not app:
            raise RuntimeError("BITRISE_TOKEN and BITRISE_APP_SLUG are needed for the iOS coverage")
        report, build_meta = fetch_report(token, app, branch)
        if cache:
            os.makedirs(cache_dir, exist_ok=True)
            with open(cache, "w") as f:
                json.dump({"report": report, "build": build_meta}, f)
    return collect(report, build_meta, FeatureMap("ios", None))


def summary(out):
    """One line per platform, totals only."""
    lines = []
    for p, c in out["platforms"].items():
        t, b = c["totals"]["features"], c["build"]
        pct = 100 * t["covered"] / t["executable"] if t["executable"] else 0
        lines.append(f"{p}: {pct:.1f}% of {t['executable']:,} feature lines, Bitrise #{b['number']} ({b['branch']}, "
                     f"{b['finished_at'][:10]}), {c['files']} files, {len(c['unmapped'])} unmapped, "
                     f"{len(c['ambiguous'])} ambiguous")
    return lines


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", default=os.path.join(HERE, "site", "data", "coverage.json"))
    parser.add_argument("--cache-dir", help="read/write ios.json here instead of always fetching")
    parser.add_argument("--branch", help="Bitrise branch to read (default: $BITRISE_COVERAGE_BRANCH or main)")
    args = parser.parse_args(argv)

    out = build(args.cache_dir, args.branch)
    print("\n".join(summary(out)))
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
