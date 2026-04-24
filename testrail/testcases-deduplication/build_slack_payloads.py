#!/usr/bin/env python3
"""
Build Slack JSON payload files for the deduplication weekly digest and spike alert.

Reads stats from environment variables (set by insert_bq_stats.py / GITHUB_ENV)
and writes slack-digest.json and optionally slack-spike.json to the output directory.

Usage:
    python build_slack_payloads.py \
        --output-dir . \
        --today 2026-04-24 \
        --project-id 14 \
        --project-name firefox-ios \
        --gcs-url https://console.cloud.google.com/storage/browser/... \
        --run-url https://github.com/...
"""
import argparse
import json
import os
import sys
from pathlib import Path


def delta_str(current: int, previous: int, has_prev_data: bool) -> str:
    if not has_prev_data:
        return ""
    diff = current - previous
    if diff > 0:
        return f" _(+{diff} vs last week)_"
    if diff < 0:
        return f" _({diff} vs last week)_"
    return " _(no change)_"


def main():
    parser = argparse.ArgumentParser(description="Build Slack payload JSON files.")
    parser.add_argument("--output-dir",   default=".", help="Directory to write slack-*.json files")
    parser.add_argument("--today",        required=True)
    parser.add_argument("--project-id",   required=True)
    parser.add_argument("--project-name", required=True)
    parser.add_argument("--gcs-url",      required=True)
    parser.add_argument("--run-url",      required=True)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)

    # Current stats (written to GITHUB_ENV by insert_bq_stats.py)
    current_total                 = int(os.environ.get("current_total", 0))
    current_exact                 = int(os.environ.get("current_exact", 0))
    current_high_priority_similar = int(os.environ.get("current_high_priority_similar", 0))
    current_rate                  = float(os.environ.get("current_rate", 0))

    # Previous stats (written to GITHUB_ENV by the BQ query step)
    prev_exact                    = int(os.environ.get("prev_exact", 0))
    prev_high_priority_similar    = int(os.environ.get("prev_high_priority_similar", 0))
    prev_total                    = int(os.environ.get("prev_total", 0))
    has_prev_data                 = os.environ.get("has_prev_data", "false") == "true"

    digest_text = (
        f"*Project:* {args.project_name} (ID: {args.project_id})\n"
        f"*Total cases:* {current_total}{delta_str(current_total, prev_total, has_prev_data)}\n"
        f"*Exact duplicates:* {current_exact}{delta_str(current_exact, prev_exact, has_prev_data)}\n"
        f"*High-priority similar pairs:* {current_high_priority_similar}"
        f"{delta_str(current_high_priority_similar, prev_high_priority_similar, has_prev_data)}\n"
        f"*Duplicate rate:* {current_rate:.1%}\n"
        f"<{args.gcs_url}|Download results from GCS>"
    )

    digest_payload = {
        "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": f":mag: TestRail Deduplication — {args.today}"}},
            {"type": "section", "text": {"type": "mrkdwn", "text": digest_text}},
        ]
    }
    (output_dir / "slack-digest.json").write_text(json.dumps(digest_payload))
    print(f"Written slack-digest.json")

    delta_exact = current_exact - prev_exact
    send_spike = has_prev_data and delta_exact > 10

    github_env = os.environ.get("GITHUB_ENV")
    if github_env:
        with open(github_env, "a") as f:
            f.write(f"send_spike={'true' if send_spike else 'false'}\n")

    if send_spike:
        spike_payload = {
            "blocks": [
                {"type": "header", "text": {"type": "plain_text", "text": f":warning: Duplicate spike detected — {args.project_name}"}},
                {"type": "section", "text": {"type": "mrkdwn", "text": (
                    f"*Exact duplicates jumped by {delta_exact}* this week "
                    f"({prev_exact} \u2192 {current_exact})\n"
                    f"*Project:* {args.project_name} (ID: {args.project_id}) | *Date:* {args.today}\n"
                    f"<{args.gcs_url}|Download results> \u00b7 <{args.run_url}|View run>"
                )}},
            ]
        }
        (output_dir / "slack-spike.json").write_text(json.dumps(spike_payload))
        print(f"Written slack-spike.json (spike detected: +{delta_exact})")
    else:
        print("No spike detected — slack-spike.json not written")


if __name__ == "__main__":
    main()
