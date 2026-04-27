#!/usr/bin/env python3
"""
Compute deduplication stats from output CSVs, write them to GITHUB_ENV,
and insert a row into BigQuery.

Usage:
    python insert_bq_stats.py \
        --output-dir ./output \
        --project-id 14 \
        --project-name firefox-ios \
        --run-date 2026-04-23 \
        --github-run-id 12345678 \
        --bq-project moz-mobile-tools \
        --bq-dataset testops_stats \
        --bq-table testrail_deduplication_runs
"""
import argparse
import csv
import json
import os
import subprocess
import sys
from pathlib import Path


HIGH_PRIORITY_THRESHOLD = 0.95


def compute_stats(output_dir: Path) -> dict:
    total = 0
    exact = 0
    similar = 0
    high_priority_similar = 0

    stats_file = output_dir / "analysis_stats.json"
    if stats_file.exists():
        total = json.loads(stats_file.read_text()).get("total_cases", 0)

    exact_file = output_dir / "duplicates_exact.csv"
    if exact_file.exists():
        with exact_file.open() as f:
            exact = sum(1 for _ in csv.DictReader(f))

    similar_file = output_dir / "similar_pairs.csv"
    if similar_file.exists():
        with similar_file.open() as f:
            for row in csv.DictReader(f):
                similar += 1
                try:
                    if float(row["similarity"]) >= HIGH_PRIORITY_THRESHOLD:
                        high_priority_similar += 1
                except (ValueError, KeyError):
                    pass

    duplicate_rate = round(exact / total, 4) if total > 0 else 0.0

    return {
        "total": total,
        "exact": exact,
        "similar": similar,
        "high_priority_similar": high_priority_similar,
        "duplicate_rate": duplicate_rate,
    }


def write_github_env(stats: dict) -> None:
    github_env = os.environ.get("GITHUB_ENV")
    if not github_env:
        return
    with open(github_env, "a") as f:
        f.write(f"current_total={stats['total']}\n")
        f.write(f"current_exact={stats['exact']}\n")
        f.write(f"current_similar={stats['similar']}\n")
        f.write(f"current_high_priority_similar={stats['high_priority_similar']}\n")
        f.write(f"current_rate={stats['duplicate_rate']}\n")


def insert_bigquery(stats: dict, args: argparse.Namespace) -> None:
    payload = json.dumps({
        "run_date":                    args.run_date,
        "project_id":                  args.project_id,
        "project_name":                args.project_name,
        "total_cases":                 stats["total"],
        "exact_duplicate_cases":       stats["exact"],
        "similar_pairs":               stats["similar"],
        "high_priority_similar_pairs": stats["high_priority_similar"],
        "duplicate_rate":              stats["duplicate_rate"],
        "github_run_id":               args.github_run_id,
    })

    result = subprocess.run(
        ["bq", "insert",
         f"--project_id={args.bq_project}",
         f"{args.bq_dataset}.{args.bq_table}"],
        input=payload.encode(),
        capture_output=True,
    )

    if result.returncode != 0:
        print(f"BigQuery insert failed: {result.stderr.decode()}", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Compute dedup stats and insert into BigQuery.")
    parser.add_argument("--output-dir",     required=True, help="Directory with output CSVs")
    parser.add_argument("--project-id",     required=True, help="TestRail project ID")
    parser.add_argument("--project-name",   required=True, help="Project name (e.g. firefox-ios)")
    parser.add_argument("--run-date",       required=True, help="Run date (YYYY-MM-DD)")
    parser.add_argument("--github-run-id",  required=True, help="GitHub Actions run ID")
    parser.add_argument("--bq-project",     default="moz-mobile-tools")
    parser.add_argument("--bq-dataset",     default="testops_stats")
    parser.add_argument("--bq-table",       default="testrail_deduplication_runs")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    if not output_dir.exists():
        print(f"Error: output directory '{output_dir}' does not exist.", file=sys.stderr)
        sys.exit(1)

    stats = compute_stats(output_dir)

    print(f"Total cases:                {stats['total']}")
    print(f"Exact duplicates:           {stats['exact']}")
    print(f"Similar pairs:              {stats['similar']}")
    print(f"High-priority similar pairs:{stats['high_priority_similar']}")
    print(f"Duplicate rate:             {stats['duplicate_rate']:.1%}")

    write_github_env(stats)
    insert_bigquery(stats, args)
    print("BigQuery insert successful.")


if __name__ == "__main__":
    main()
