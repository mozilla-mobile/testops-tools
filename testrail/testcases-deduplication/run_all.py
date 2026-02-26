#!/usr/bin/env python3
"""
Full deduplication pipeline: find duplicates → generate work list → export CSVs.

Usage:
    python run_all.py /path/to/testrail_export.xlsx
    python run_all.py /path/to/export.xlsx --sim-threshold 0.85
"""
import argparse
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(
        description="Run the full test case deduplication pipeline."
    )
    parser.add_argument("input_xlsx", help="Path to the TestRail Excel export (.xlsx)")
    parser.add_argument(
        "--dup-threshold", type=float, default=0.90,
        help="Semantic similarity threshold for 'duplicate' label (default: 0.90)"
    )
    parser.add_argument(
        "--sim-threshold", type=float, default=0.80,
        help="Minimum similarity threshold to report a pair (default: 0.80)"
    )
    parser.add_argument(
        "--overlap-threshold", type=float, default=0.80,
        help="Step overlap threshold for 'shares_most_steps' flag (default: 0.80)"
    )
    args = parser.parse_args()

    steps = [
        {
            "name": "Step 1/3: Finding duplicates",
            "cmd": [
                sys.executable, "find-duplicates.py",
                args.input_xlsx,
                "--dup-threshold", str(args.dup_threshold),
                "--sim-threshold", str(args.sim_threshold),
                "--overlap-threshold", str(args.overlap_threshold),
            ],
        },
        {
            "name": "Step 2/3: Generating work list report",
            "cmd": [sys.executable, "generate-work-list.py"],
        },
        {
            "name": "Step 3/3: Exporting priority CSVs",
            "cmd": [sys.executable, "export-priority-list.py"],
        },
    ]

    for step in steps:
        print(f"\n{'='*60}")
        print(f"  {step['name']}")
        print(f"{'='*60}")
        result = subprocess.run(step["cmd"])
        if result.returncode != 0:
            print(f"\nERROR: {step['name']} failed with exit code {result.returncode}. Aborting.")
            sys.exit(result.returncode)

    print(f"\n{'='*60}")
    print("  Pipeline complete.")
    print("  Output files:")
    print("    - duplicates_exact.csv")
    print("    - similar_pairs.csv")
    print("    - WORK_LIST_EXACT.csv")
    print("    - WORK_LIST_PERFECT_MATCHES.csv")
    print("    - WORK_LIST_SIMILAR_HIGH_PRIORITY.csv")
    print("    - analysis_stats.json")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
