#!/usr/bin/env python3
"""
Generate prioritized work list for reviewing duplicates
"""
import json
import os
import pandas as pd


def load_csv(path: str) -> pd.DataFrame:
    """Load a CSV file, returning an empty DataFrame if the file doesn't exist."""
    if not os.path.exists(path):
        print(f"Warning: {path} not found — skipping (no results for this category).")
        return pd.DataFrame()
    return pd.read_csv(path)


def generate_work_list():
    # Load data
    exact = load_csv('duplicates_exact.csv')
    similar = load_csv('similar_pairs.csv')

    if exact.empty and similar.empty:
        raise RuntimeError("No duplicate data found. Run find-duplicates.py first.")

    # Load total case count from stats file (written by find-duplicates.py)
    total_cases = 0
    if os.path.exists('analysis_stats.json'):
        with open('analysis_stats.json') as f:
            stats = json.load(f)
        total_cases = stats.get('total_cases', 0)

    print("=" * 80)
    print("WORK LIST - TEST CASE DEDUPLICATION")
    print("=" * 80)
    print()

    # PART 1: Exact Duplicates
    print("PHASE 1: EXACT DUPLICATES")
    print("-" * 80)

    total_to_archive = 0

    if exact.empty:
        print("  No exact duplicates found.")
    else:
        group_sizes = exact.groupby('duplicate_group_id').size().sort_values(ascending=False)
        priority = 1

        # Large groups first (4+)
        print("\n🔴 PRIORITY 1: Large groups (4+ duplicates)")
        print()
        for group_id, size in group_sizes[group_sizes >= 4].items():
            group = exact[exact['duplicate_group_id'] == group_id].sort_values('_case_id')
            title = group.iloc[0]['_title']
            case_ids = list(group['_case_id'].values)

            print(f"{priority}. Group {group_id}: {size} duplicates")
            print(f"   Title: {title}")
            print(f"   ✅ KEEP: {case_ids[0]} (lowest ID)")
            print(f"   🗑️  ARCHIVE: {', '.join(case_ids[1:])}")
            print(f"   Savings: {size - 1} test cases")
            print()

            priority += 1
            total_to_archive += size - 1

        # Medium groups (3)
        print("\n🟠 PRIORITY 2: Medium groups (3 duplicates)")
        print()
        for group_id, size in group_sizes[group_sizes == 3].items():
            group = exact[exact['duplicate_group_id'] == group_id].sort_values('_case_id')
            title = group.iloc[0]['_title']
            case_ids = list(group['_case_id'].values)

            print(f"{priority}. Group {group_id}: {title[:60]}")
            print(f"   ✅ KEEP: {case_ids[0]}")
            print(f"   🗑️  ARCHIVE: {', '.join(case_ids[1:])}")
            print()

            priority += 1
            total_to_archive += size - 1

            if priority > 25:  # Limit output
                remaining = len(group_sizes[group_sizes == 3]) - (priority - len(group_sizes[group_sizes >= 4]) - 1)
                if remaining > 0:
                    print(f"   ... and {remaining} more groups of 3")
                break

        # Small groups (2)
        print(f"\n🟡 PRIORITY 3: Small groups (2 duplicates)")
        print(f"   {(group_sizes == 2).sum()} groups")
        print(f"   Savings: {(group_sizes == 2).sum()} test cases")
        print()

        total_to_archive += (group_sizes == 2).sum()

        print(f"\n📊 PHASE 1 SUMMARY:")
        print(f"   Total groups: {len(group_sizes)}")
        print(f"   Total cases to archive: {total_to_archive}")
        print()

    # PART 2: High Similarity
    print("\n" + "=" * 80)
    print("PHASE 2: HIGH SIMILARITY PAIRS")
    print("-" * 80)

    if similar.empty:
        print("  No similar pairs found.")
    else:
        perfect = similar[similar['similarity'] == 1.0]
        print(f"\n🔴 PRIORITY 1: Perfect semantic matches (100%)")
        print(f"   {len(perfect)} pairs")
        print(f"   Estimated savings: ~{len(perfect) // 2} test cases")
        print()

        print("   Top 5 examples:")
        for i, (_, row) in enumerate(perfect.head(5).iterrows(), 1):
            print(f"   {i}. {row['case_id_1']} vs {row['case_id_2']}")
            print(f"      {row['title_1'][:60]}")
            print()

        near_perfect = similar[(similar['similarity'] >= 0.95) & (similar['similarity'] < 1.0)]
        print(f"🟠 PRIORITY 2: Near-perfect matches (95-100%)")
        print(f"   {len(near_perfect)} pairs")
        print(f"   Recommended: Review top 50")
        print(f"   Estimated savings: ~{len(near_perfect) // 3} test cases")
        print()

        high_overlap = similar[(similar['similarity'] >= 0.90) & (similar['step_overlap'] >= 0.8)]
        print(f"🟡 PRIORITY 3: High step overlap (≥90% sim, ≥80% overlap)")
        print(f"   {len(high_overlap)} pairs")
        print(f"   These share most execution steps")
        print()

    # Compute Phase 2 estimate from real data (perfect + ~1/3 of near-perfect)
    if not similar.empty:
        perfect_savings = len(similar[similar['similarity'] == 1.0]) // 2
        near_perfect_savings = len(similar[(similar['similarity'] >= 0.95) & (similar['similarity'] < 1.0)]) // 3
        phase2_estimate = perfect_savings + near_perfect_savings
    else:
        phase2_estimate = 0

    # Overall summary
    print("\n" + "=" * 80)
    print("ESTIMATED TOTALS")
    print("-" * 80)
    print(f"Phase 1 (Exact):      ~{total_to_archive} cases")
    if phase2_estimate > 0:
        print(f"Phase 2 (Similar):    ~{phase2_estimate} cases")
    estimated_total = total_to_archive + phase2_estimate
    if total_cases > 0:
        pct = estimated_total / total_cases * 100
        print(f"GRAND TOTAL:          ~{estimated_total} cases ({pct:.1f}% reduction out of {total_cases} total)")
    else:
        print(f"GRAND TOTAL:          ~{estimated_total} cases")
    print("=" * 80)


if __name__ == "__main__":
    import argparse
    import sys
    parser = argparse.ArgumentParser(description="Generate prioritized work list from deduplication results.")
    parser.add_argument(
        "--output-dir", default=".",
        help="Directory containing duplicates_exact.csv and similar_pairs.csv (default: current directory)"
    )
    cli_args = parser.parse_args()
    os.chdir(cli_args.output_dir)
    try:
        generate_work_list()
    except RuntimeError as e:
        print(f"Error: {e}")
        sys.exit(1)
