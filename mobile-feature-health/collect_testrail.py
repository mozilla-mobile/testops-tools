#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml", "requests"]
# ///
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""TestRail cases and UI automation per L1/L2 feature, iOS and Android, for the feature health dashboard.

Cases are attributed with ../mobile-feature-taxonomy/testrail_map.py: the feature ID at the start of each Full
Functional section's description (or of its nearest parent). Only aggregate counts are written: no section names,
titles or case IDs reach the output file or the log, because this repo and its Actions logs are public.

Normally run through collect.py, which builds every data file of the dashboard. On its own:
    python collect_testrail.py --out site/data/testrail.json
    python collect_testrail.py --cache-dir /tmp/tr --out site/data/testrail.json   # reuse fetched data locally
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
TAXONOMY_DIR = os.path.join(os.path.dirname(HERE), "mobile-feature-taxonomy")
sys.path.insert(0, TAXONOMY_DIR)

import testrail_map  # noqa: E402
from feature_map import load_taxonomy  # noqa: E402

JSON_SCHEMA_VERSION = 1
PLATFORMS = ("ios", "android")


def platform_counts(data, ids):
    """Aggregates for one suite: {"suite_id", "cases", "no_feature", "features": {key: {"total", "automated"}}}.

    Keys are L2 IDs and "L1:<area>"; an area includes the cases attributed to the area alone.
    """
    attributed, _ = testrail_map.attribute(data["sections"], data["cases"], ids)
    counts = testrail_map.count(attributed)
    no_feature = counts.pop(testrail_map.NO_FEATURE, {}).get("total", 0)
    return {
        "suite_id": data["suite_id"],
        "cases": len(attributed),
        "no_feature": no_feature,
        "features": {k: {"total": v["total"], "automated": v["automated"]} for k, v in sorted(counts.items())},
    }


def collect(data_by_platform):
    ids = testrail_map.valid_ids(load_taxonomy())
    return {
        "schema_version": JSON_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "platforms": {p: platform_counts(d, ids) for p, d in data_by_platform.items()},
    }


def build(cache_dir=None):
    """Fetch both suites (or read them from cache_dir/<platform>.json) and return the data file's content."""
    data_by_platform = {}
    for p in PLATFORMS:
        cache = os.path.join(cache_dir, f"{p}.json") if cache_dir else None
        data_by_platform[p] = testrail_map.load_data(p, cache)
    return collect(data_by_platform)


def summary(out):
    """One line per platform, totals only."""
    lines = []
    for p, c in out["platforms"].items():
        automated = sum(v["automated"] for k, v in c["features"].items() if k.startswith("L1:"))
        lines.append(f"{p}: {c['cases']} cases, {automated} automated, {c['no_feature']} with no feature")
    return lines


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", default=os.path.join(HERE, "site", "data", "testrail.json"))
    parser.add_argument("--cache-dir", help="read/write <platform>.json here instead of always fetching")
    args = parser.parse_args(argv)

    out = build(args.cache_dir)
    print("\n".join(summary(out)))
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
