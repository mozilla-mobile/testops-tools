#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml", "requests"]
# ///
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""Daily check that every TestRail Full Functional case reaches a feature ID, with a Slack alert when not.

Runs `testrail_map.py check` for iOS and Android and reports, per platform:
  - sections whose description starts with an ID that isn't in features.yml (typos such as `APP.UDP`)
  - sections whose cases reach no ID: neither the section nor any parent carries one (usually a new section)

Cases attributed to an L1 area only are accepted (e.g. iOS "Library"): they don't trigger an alert.

Section names and links only go to Slack. stdout and the GitHub job summary get counts only, because this repo
and its Actions logs are public.

Environment: TestRail credentials as for testrail_map.py; SLACK_WEBHOOK_URL (optional: without it, or with
--dry-run, the Slack message is printed instead of sent; only do that locally).

Usage:
    uv run testrail_section_check.py                 # both platforms, alert if anything is wrong
    uv run testrail_section_check.py --dry-run       # print the Slack message instead of sending it
    uv run testrail_section_check.py --platform ios

Exit status: 0 when everything maps, 1 when something needs fixing (after alerting), 2 on errors.
"""

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import testrail_map  # noqa: E402
from feature_map import load_taxonomy  # noqa: E402

PLATFORM_NAMES = {"ios": "iOS", "android": "Android"}
MAX_LINES = 40          # per platform and kind, so the message stays readable (and under Slack's limits)
SLACK_TEXT_LIMIT = 2900  # a section block's text is capped at 3000 characters


def section_url(base_url, suite_id, section_id):
    return f"{base_url.rstrip('/')}/index.php?/suites/view/{suite_id}&group_by=cases:section_id&group_id={section_id}"


def slack_escape(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def check_platform(platform, data, ids):
    """{"platform", "suite_id", "sections", "cases", "unknown": [(sid, path, word)], "unmapped": [(sid, path, n)]}"""
    attributed, tree = testrail_map.attribute(data["sections"], data["cases"], ids)
    found = testrail_map.find_problems(attributed, tree, data)
    return {
        "platform": platform,
        "suite_id": data["suite_id"],
        "sections": len(tree.sections),
        "cases": len(attributed),
        "unknown": sorted(((sid, tree.path(sid), w) for sid, w in found["unknown"].items()), key=lambda r: r[1]),
        "unmapped": sorted(((sid, tree.path(sid), n) for sid, n in found["unmapped"].items()), key=lambda r: r[1]),
    }


def has_problems(result):
    return bool(result["unknown"] or result["unmapped"])


def summary_line(result):
    """Counts only: safe for public logs."""
    unmapped_cases = sum(n for _, _, n in result["unmapped"])
    status = "OK" if not has_problems(result) else "needs fixing"
    return (f"{PLATFORM_NAMES[result['platform']]} (suite {result['suite_id']}): {status}. "
            f"{result['cases']} cases in {result['sections']} sections; "
            f"{len(result['unknown'])} sections with an unknown ID; "
            f"{unmapped_cases} cases in {len(result['unmapped'])} sections with no feature ID.")


def _chunks(lines):
    """Join lines into texts under Slack's per-block limit."""
    out, current = [], ""
    for line in lines:
        if current and len(current) + len(line) + 1 > SLACK_TEXT_LIMIT:
            out.append(current)
            current = ""
        current = f"{current}\n{line}" if current else line
    if current:
        out.append(current)
    return out


def _limited(rows, render):
    lines = [render(r) for r in rows[:MAX_LINES]]
    if len(rows) > MAX_LINES:
        lines.append(f"…and {len(rows) - MAX_LINES} more: run `testrail_map.py <platform> check` locally.")
    return lines


def slack_payload(results, base_url, run_url=None):
    failing = [r for r in results if has_problems(r)]
    blocks = [{"type": "header", "text": {"type": "plain_text", "text": "TestRail sections without a feature ID"}},
              {"type": "section", "text": {"type": "mrkdwn", "text":
               "Every section in the Full Functional suites should start its description with an L2 ID "
               "(e.g. `LIB.BMK`) or an L1 ID (e.g. `CRED`) from "
               "<https://github.com/mozilla-mobile/testops-tools/blob/main/mobile-feature-taxonomy/FEATURES.md"
               "|FEATURES.md>, or inherit one from a parent section."}}]
    for r in failing:
        name = PLATFORM_NAMES[r["platform"]]
        lines = []
        if r["unknown"]:
            lines.append(f"*{name}: ID not in the taxonomy ({len(r['unknown'])} sections)*")
            lines += _limited(r["unknown"], lambda row: (
                f"• `{slack_escape(row[2])}` in <{section_url(base_url, r['suite_id'], row[0])}|"
                f"{slack_escape(row[1])}>"))
        if r["unmapped"]:
            if lines:
                lines.append("")
            cases = sum(n for _, _, n in r["unmapped"])
            lines.append(f"*{name}: {cases} cases with no feature ({len(r['unmapped'])} sections)*")
            lines += _limited(r["unmapped"], lambda row: (
                f"• <{section_url(base_url, r['suite_id'], row[0])}|{slack_escape(row[1])}>: "
                f"{row[2]} case{'s' if row[2] != 1 else ''}"))
        blocks += [{"type": "section", "text": {"type": "mrkdwn", "text": t}} for t in _chunks(lines)]
    ok = [PLATFORM_NAMES[r["platform"]] for r in results if not has_problems(r)]
    context = []
    if ok:
        context.append(f"{' and '.join(ok)}: all sections OK.")
    if run_url:
        context.append(f"<{run_url}|Workflow run>")
    if context:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": " · ".join(context)}]})
    text = "TestRail sections without a feature ID: " + ", ".join(PLATFORM_NAMES[r["platform"]] for r in failing)
    return {"text": text, "blocks": blocks}


def post_to_slack(webhook, payload):
    import requests

    resp = requests.post(webhook, json=payload, timeout=30)
    resp.raise_for_status()


def write_job_summary(results):
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    with open(path, "a") as f:
        f.write("## TestRail section feature IDs\n\n")
        for r in results:
            f.write(f"- {'✅' if not has_problems(r) else '⚠️'} {summary_line(r)}\n")
        if any(has_problems(r) for r in results):
            f.write("\nThe sections are listed in the Slack alert (not here: this log is public).\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--platform", choices=sorted(testrail_map.SUITES), action="append",
                        help="platform to check (repeatable; default: all)")
    parser.add_argument("--dry-run", action="store_true", help="print the Slack message instead of sending it")
    parser.add_argument("--cache-dir", help="read/write <platform>.json here (see testrail_map.py --cache)")
    args = parser.parse_args(argv)

    ids = testrail_map.valid_ids(load_taxonomy())
    results = []
    for platform in args.platform or sorted(testrail_map.SUITES):
        cache = os.path.join(args.cache_dir, f"{platform}.json") if args.cache_dir else None
        results.append(check_platform(platform, testrail_map.load_data(platform, cache), ids))

    for r in results:
        print(summary_line(r))
    write_job_summary(results)

    if not any(has_problems(r) for r in results):
        return 0

    run_url = None
    if os.environ.get("GITHUB_RUN_ID"):
        run_url = (f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/"
                   f"{os.environ.get('GITHUB_REPOSITORY')}/actions/runs/{os.environ['GITHUB_RUN_ID']}")
    payload = slack_payload(results, testrail_map.credentials()[0], run_url)
    webhook = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
    if args.dry_run or not webhook:
        if not webhook and not args.dry_run:
            print("SLACK_WEBHOOK_URL not set: not sending the alert.", file=sys.stderr)
            return 1
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        post_to_slack(webhook, payload)
        print("Slack alert sent.")
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001 - report the type only: messages can carry URLs or response bodies
        print(f"Error: {type(e).__name__}", file=sys.stderr)
        sys.exit(2)
