#!/usr/bin/env python3
"""
Export filtered priority lists to CSV for easy review in Excel
"""
import os
import re
import sys
import pandas as pd


def load_csv(path: str) -> pd.DataFrame:
    """Load a CSV file, returning an empty DataFrame if the file doesn't exist."""
    if not os.path.exists(path):
        print(f"Warning: {path} not found — skipping (no results for this category).")
        return pd.DataFrame()
    return pd.read_csv(path)


def case_id_sort_key(case_id: str) -> int:
    """Extract numeric part of a case ID like 'C12345' for correct numeric sorting."""
    match = re.search(r'\d+', str(case_id))
    return int(match.group()) if match else 0


def export_priority_lists():
    # Load data
    exact = load_csv('duplicates_exact.csv')
    similar = load_csv('similar_pairs.csv')

    if exact.empty and similar.empty:
        raise RuntimeError("No duplicate data found. Run find-duplicates.py first.")

    # 1. Exact duplicates - sorted by group size
    if exact.empty:
        print("⚠️  No exact duplicates — skipping WORK_LIST_EXACT.csv")
    else:
        group_sizes = exact.groupby('duplicate_group_id').size()
        exact['group_size'] = exact['duplicate_group_id'].map(group_sizes)
        exact = exact.sort_values(['group_size', 'duplicate_group_id', '_case_id'], ascending=[False, True, True])

        # Add decision columns (sort numerically by case ID to pick the lowest-numbered case to keep)
        # Use Series.groupby to avoid pandas 2.2+ include_groups deprecation
        group_keep = (
            exact.groupby('duplicate_group_id')['_case_id']
            .apply(lambda ids: sorted(ids.tolist(), key=case_id_sort_key)[0])
        )
        group_archive = (
            exact.groupby('duplicate_group_id')['_case_id']
            .apply(lambda ids: ', '.join(sorted(ids.tolist(), key=case_id_sort_key)[1:]))
        )
        exact['KEEP'] = exact['duplicate_group_id'].map(group_keep)
        exact['ARCHIVE'] = exact['duplicate_group_id'].map(group_archive)

        # Reorder columns
        section_col = '_section' if '_section' in exact.columns else None
        base_cols = ['duplicate_group_id', 'group_size', '_case_id', '_title']
        if section_col:
            base_cols.append(section_col)
        base_cols += ['KEEP', 'ARCHIVE']
        exact = exact[base_cols]
        new_names = ['Group_ID', 'Group_Size', 'Case_ID', 'Title']
        if section_col:
            new_names.append('Section')
        new_names += ['Suggested_KEEP', 'Suggested_ARCHIVE']
        exact.columns = new_names

        # Add empty tracking columns
        exact['Decision'] = ''
        exact['Status'] = 'TODO'
        exact['Notes'] = ''

        # Save
        exact.to_csv('WORK_LIST_EXACT.csv', index=False)
        print(f"✅ Created WORK_LIST_EXACT.csv ({len(exact)} cases in {exact['Group_ID'].nunique()} groups)")

    # 2. High priority similar pairs (>= 95% similarity)
    if similar.empty:
        print("⚠️  No similar pairs — skipping WORK_LIST_SIMILAR_HIGH_PRIORITY.csv and WORK_LIST_PERFECT_MATCHES.csv")
    else:
        high_sim = similar[similar['similarity'] >= 0.95].copy()
        high_sim = high_sim.sort_values('similarity', ascending=False)

        # Add decision columns
        high_sim['Suggested_Action'] = ''
        high_sim['Decision'] = ''
        high_sim['Status'] = 'TODO'
        high_sim['Notes'] = ''

        # Reorder columns (include section if present)
        base_cols = ['case_id_1', 'title_1']
        if 'section_1' in high_sim.columns:
            base_cols.append('section_1')
        base_cols += ['case_id_2', 'title_2']
        if 'section_2' in high_sim.columns:
            base_cols.append('section_2')
        base_cols += ['similarity', 'step_overlap', 'relation', 'shares_most_steps',
                      'Suggested_Action', 'Decision', 'Status', 'Notes']
        high_sim = high_sim[base_cols]

        high_sim.to_csv('WORK_LIST_SIMILAR_HIGH_PRIORITY.csv', index=False)
        print(f"✅ Created WORK_LIST_SIMILAR_HIGH_PRIORITY.csv ({len(high_sim)} pairs)")

        # 3. Perfect matches (100% similarity) - these are basically exact duplicates
        perfect = similar[similar['similarity'] == 1.0].copy()
        perfect = perfect.sort_values('step_overlap', ascending=False)

        # Keep the case with the lower numeric ID
        perfect['Suggested_KEEP'] = perfect.apply(
            lambda r: r['case_id_1'] if case_id_sort_key(r['case_id_1']) <= case_id_sort_key(r['case_id_2']) else r['case_id_2'],
            axis=1,
        )
        perfect['Suggested_ARCHIVE'] = perfect.apply(
            lambda r: r['case_id_2'] if case_id_sort_key(r['case_id_1']) <= case_id_sort_key(r['case_id_2']) else r['case_id_1'],
            axis=1,
        )
        perfect['Decision'] = ''
        perfect['Status'] = 'TODO'
        perfect['Notes'] = ''

        base_cols = ['case_id_1', 'title_1']
        if 'section_1' in perfect.columns:
            base_cols.append('section_1')
        base_cols += ['case_id_2', 'title_2']
        if 'section_2' in perfect.columns:
            base_cols.append('section_2')
        base_cols += ['similarity', 'step_overlap', 'Suggested_KEEP', 'Suggested_ARCHIVE',
                      'Decision', 'Status', 'Notes']
        perfect = perfect[base_cols]

        perfect.to_csv('WORK_LIST_PERFECT_MATCHES.csv', index=False)
        print(f"✅ Created WORK_LIST_PERFECT_MATCHES.csv ({len(perfect)} pairs)")

    # Summary
    print("\n" + "="*60)
    print("WORK LISTS CREATED")
    print("="*60)
    if not exact.empty and 'Group_ID' in exact.columns:
        print("\n1. WORK_LIST_EXACT.csv")
        print(f"   - {len(exact)} cases in {exact['Group_ID'].nunique()} groups")
        print(f"   - Suggested savings: ~{len(exact) - exact['Group_ID'].nunique()} cases")
    if not similar.empty:
        print("\n2. WORK_LIST_PERFECT_MATCHES.csv")
        print(f"   - {len(perfect)} pairs with 100% similarity")
        print(f"   - Suggested savings: ~{len(perfect)} cases")
        print("\n3. WORK_LIST_SIMILAR_HIGH_PRIORITY.csv")
        print(f"   - {len(high_sim)} pairs with ≥95% similarity")
        print(f"   - Review and decide case by case")
    print("\n💡 TIP: Open these in Excel and use filters/sorting to prioritize")
    print("="*60)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Export priority work lists from deduplication results.")
    parser.add_argument(
        "--output-dir", default=".",
        help="Directory containing input CSVs and where work lists will be written (default: current directory)"
    )
    cli_args = parser.parse_args()
    os.chdir(cli_args.output_dir)
    try:
        export_priority_lists()
    except RuntimeError as e:
        print(f"Error: {e}")
        sys.exit(1)
