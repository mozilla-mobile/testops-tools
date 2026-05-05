#!/usr/bin/env python3
"""
Full deduplication pipeline: find duplicates → generate work list → export CSVs.

Usage:
    python run_all.py /path/to/testrail_export.xlsx
    python run_all.py /path/to/export.xlsx --sim-threshold 0.85
"""
import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent


def load_module(filename: str):
    """Load a module from a hyphen-named file in the same directory as this script."""
    path = SCRIPT_DIR / filename
    module_name = filename.removesuffix(".py").replace("-", "_")
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_find_duplicates(input_xlsx: str, dup_threshold: float, sim_threshold: float, overlap_threshold: float):
    fd = load_module("find-duplicates.py")

    # Set thresholds before calling any function (they are module-level constants)
    fd.SEMANTIC_DUP_THRESHOLD = dup_threshold
    fd.SEMANTIC_SIM_THRESHOLD = sim_threshold
    fd.STEP_OVERLAP_THRESHOLD = overlap_threshold

    print("Loading and normalizing data...")
    df = fd.load_and_normalize(input_xlsx)
    print(f"Total test cases loaded: {len(df)}")

    if len(df) == 0:
        print("Warning: No test cases found in the input file.")
        return

    print("Searching for exact duplicates...")
    exact_dups = fd.find_exact_duplicates(df)
    if not exact_dups.empty:
        exact_dups[["_case_id", "_title", "_section", "duplicate_group_id"]].to_csv("duplicates_exact.csv", index=False)
        print("Exact duplicates saved to duplicates_exact.csv")
    else:
        print("No exact duplicates found.")

    print("Searching for similar tests (semantic + steps)...")
    similar_pairs = fd.compute_semantic_pairs(df)
    if not similar_pairs.empty:
        similar_pairs.to_csv("similar_pairs.csv", index=False)
        print("Similar pairs saved to similar_pairs.csv")
    else:
        print("No similar pairs found with the defined thresholds.")

    stats = {"total_cases": len(df), "input_file": input_xlsx}
    with open("analysis_stats.json", "w") as f:
        json.dump(stats, f, indent=2)
    print("Stats saved to analysis_stats.json")


def run_generate_work_list():
    gwl = load_module("generate-work-list.py")
    gwl.generate_work_list()


def run_export_priority_lists():
    epl = load_module("export-priority-list.py")
    epl.export_priority_lists()


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
    parser.add_argument(
        "--output-dir", default=str(SCRIPT_DIR),
        help="Directory where output CSVs will be written (default: script directory)"
    )
    args = parser.parse_args()

    # Resolve both paths before chdir, in case they are relative to the caller's CWD
    input_xlsx = str(Path(args.input_xlsx).resolve())
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    # All sub-scripts use relative paths for their CSVs — chdir so they resolve to output_dir
    os.chdir(output_dir)

    print(f"\n{'='*60}")
    print("  Step 1/3: Finding duplicates")
    print(f"{'='*60}")
    run_find_duplicates(input_xlsx, args.dup_threshold, args.sim_threshold, args.overlap_threshold)

    for name, fn in [
        ("Step 2/3: Generating work list",    run_generate_work_list),
        ("Step 3/3: Exporting priority CSVs", run_export_priority_lists),
    ]:
        print(f"\n{'='*60}")
        print(f"  {name}")
        print(f"{'='*60}")
        try:
            fn()
        except RuntimeError as e:
            print(f"  Skipped: {e}")

    print(f"\n{'='*60}")
    print("  Pipeline complete.")
    print(f"  Output directory: {output_dir}")
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
