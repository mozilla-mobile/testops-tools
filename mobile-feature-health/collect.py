#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml", "requests"]
# ///
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""Build every data file of the feature health dashboard: one command, all sources.

Writes to site/data/:
  features.json   the taxonomy rows: L1 areas, L2 features, cross-cutting axes (from features.yml, no network)
  testrail.json   TestRail cases and UI automation per feature (collect_testrail.py; needs TestRail credentials)
  bugs.json       escaped bugs per feature this year, with the list of bugs (collect_bugs.py; GitHub token for iOS)
  coverage.json   unit-test line coverage per feature, iOS (collect_coverage.py; needs a Bitrise token)
  status.json     when it ran and which sources succeeded

A source that fails doesn't stop the others: the page shows "no data" for its columns and a notice. The exit status
is 1 when any source failed, unless --allow-partial (the workflow deploys what it has, then fails the run so someone
notices). Errors are logged by type only: messages can carry URLs or response bodies, and the log is public.

Usage:
    uv run collect.py                          # everything, fresh
    uv run collect.py --cache-dir /tmp/fh      # reuse fetched data between local runs
    uv run collect.py --only bugs
"""

import argparse
import json
import os
import sys
import traceback
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "mobile-feature-taxonomy"))

import collect_bugs  # noqa: E402
import collect_coverage  # noqa: E402
import collect_testrail  # noqa: E402
import taxonomy  # noqa: E402

SOURCES = {"testrail": collect_testrail, "bugs": collect_bugs, "coverage": collect_coverage}


def feature_rows():
    """{"features": [{"type": "l1"|"l2", ...}], "crosscutting", "shared", "excluded": [{"id", "name"}]} in
    features.yml order."""
    data = taxonomy.load()
    rows = []
    for l1, area, features in taxonomy.areas(data):
        rows.append({"type": "l1", "id": l1, "name": area})
        rows += [{"type": "l2", "id": f["id"], "l1": l1, "name": f["name"]} for f in features]
    named = lambda key: [{"id": x["id"], "name": x["name"]} for x in data.get(key, [])]
    return {"features": rows, "crosscutting": named("crosscutting"), "shared": named("shared"),
            "excluded": named("excluded")}


def write(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def run(out_dir, cache_dir=None, only=None):
    """Build the data files; returns status.json's content."""
    os.makedirs(out_dir, exist_ok=True)
    write(os.path.join(out_dir, "features.json"), feature_rows())
    status = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "sources": {}}
    for name, module in SOURCES.items():
        if only and name not in only:
            continue
        cache = os.path.join(cache_dir, name) if cache_dir else None
        if cache:
            os.makedirs(cache, exist_ok=True)
        print(f"== {name}", flush=True)
        try:
            out = module.build(cache)
        except Exception as e:  # noqa: BLE001 - one source failing must not stop the others
            print(f"   FAILED: {type(e).__name__}", file=sys.stderr)
            if os.environ.get("COLLECT_DEBUG"):
                traceback.print_exc()
            status["sources"][name] = {"ok": False, "error": type(e).__name__}
            stale = os.path.join(out_dir, f"{name}.json")
            if os.path.exists(stale):
                os.remove(stale)   # never show last run's numbers as if they were today's
            continue
        write(os.path.join(out_dir, f"{name}.json"), out)
        for line in module.summary(out):
            print("   " + line)
        status["sources"][name] = {"ok": True}
    write(os.path.join(out_dir, "status.json"), status)
    return status


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out-dir", default=os.path.join(HERE, "site", "data"))
    parser.add_argument("--cache-dir", help="keep fetched data in <dir>/<source>/ for faster local reruns")
    parser.add_argument("--only", action="append", choices=sorted(SOURCES), help="build only this source")
    parser.add_argument("--allow-partial", action="store_true", help="exit 0 even if a source failed")
    args = parser.parse_args(argv)
    status = run(args.out_dir, args.cache_dir, args.only)
    failed = [k for k, v in status["sources"].items() if not v["ok"]]
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a") as f:
            f.write("## Feature health data\n\n")
            for k, v in status["sources"].items():
                f.write(f"- {'✅' if v['ok'] else '❌'} {k}" + ("" if v["ok"] else f": {v['error']}") + "\n")
    if failed:
        print(f"Failed sources: {', '.join(failed)}", file=sys.stderr)
        return 0 if args.allow_partial else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
