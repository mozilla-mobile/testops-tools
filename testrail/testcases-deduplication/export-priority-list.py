#!/usr/bin/env python3
"""
Export filtered priority lists to CSV for easy review in Excel
"""
import pandas as pd

def export_priority_lists():
    # Load data
    exact = pd.read_csv('duplicates_exact.csv')
    similar = pd.read_csv('similar_pairs.csv')

    # 1. Exact duplicates - sorted by group size
    group_sizes = exact.groupby('duplicate_group_id').size()
    exact['group_size'] = exact['duplicate_group_id'].map(group_sizes)
    exact = exact.sort_values(['group_size', 'duplicate_group_id', '_case_id'], ascending=[False, True, True])

    # Add decision columns
    def get_keep_archive(group):
        case_ids = sorted(group['_case_id'].tolist())
        keep = case_ids[0]
        archive = ', '.join(case_ids[1:])
        group['KEEP'] = keep
        group['ARCHIVE'] = archive
        return group

    exact = exact.groupby('duplicate_group_id').apply(get_keep_archive).reset_index(drop=True)

    # Reorder columns
    exact = exact[['duplicate_group_id', 'group_size', '_case_id', '_title', 'KEEP', 'ARCHIVE']]
    exact.columns = ['Group_ID', 'Group_Size', 'Case_ID', 'Title', 'Suggested_KEEP', 'Suggested_ARCHIVE']

    # Add empty tracking columns
    exact['Decision'] = ''
    exact['Status'] = 'TODO'
    exact['Notes'] = ''

    # Save
    exact.to_csv('WORK_LIST_EXACT.csv', index=False)
    print(f"✅ Created WORK_LIST_EXACT.csv ({len(exact)} cases in {exact['Group_ID'].nunique()} groups)")

    # 2. High priority similar pairs (>= 95% similarity)
    high_sim = similar[similar['similarity'] >= 0.95].copy()
    high_sim = high_sim.sort_values('similarity', ascending=False)

    # Add decision columns
    high_sim['Suggested_Action'] = ''
    high_sim['Decision'] = ''
    high_sim['Status'] = 'TODO'
    high_sim['Notes'] = ''

    # Reorder columns
    cols = ['case_id_1', 'title_1', 'case_id_2', 'title_2', 'similarity', 'step_overlap',
            'relation', 'shares_most_steps', 'Suggested_Action', 'Decision', 'Status', 'Notes']
    high_sim = high_sim[cols]

    high_sim.to_csv('WORK_LIST_SIMILAR_HIGH_PRIORITY.csv', index=False)
    print(f"✅ Created WORK_LIST_SIMILAR_HIGH_PRIORITY.csv ({len(high_sim)} pairs)")

    # 3. Perfect matches (100% similarity) - these are basically exact duplicates
    perfect = similar[similar['similarity'] == 1.0].copy()
    perfect = perfect.sort_values('step_overlap', ascending=False)

    perfect['Suggested_KEEP'] = perfect['case_id_1']  # Keep lower ID
    perfect['Suggested_ARCHIVE'] = perfect['case_id_2']
    perfect['Decision'] = ''
    perfect['Status'] = 'TODO'
    perfect['Notes'] = ''

    cols = ['case_id_1', 'title_1', 'case_id_2', 'title_2', 'similarity', 'step_overlap',
            'Suggested_KEEP', 'Suggested_ARCHIVE', 'Decision', 'Status', 'Notes']
    perfect = perfect[cols]

    perfect.to_csv('WORK_LIST_PERFECT_MATCHES.csv', index=False)
    print(f"✅ Created WORK_LIST_PERFECT_MATCHES.csv ({len(perfect)} pairs)")

    # Summary
    print("\n" + "="*60)
    print("WORK LISTS CREATED")
    print("="*60)
    print("\n1. WORK_LIST_EXACT.csv")
    print(f"   - {len(exact)} cases in {exact['Group_ID'].nunique()} groups")
    print(f"   - Suggested savings: ~{len(exact) - exact['Group_ID'].nunique()} cases")
    print("\n2. WORK_LIST_PERFECT_MATCHES.csv")
    print(f"   - {len(perfect)} pairs with 100% similarity")
    print(f"   - Suggested savings: ~{len(perfect)} cases")
    print("\n3. WORK_LIST_SIMILAR_HIGH_PRIORITY.csv")
    print(f"   - {len(high_sim)} pairs with ≥95% similarity")
    print(f"   - Review and decide case by case")
    print("\n💡 TIP: Open these in Excel and use filters/sorting to prioritize")
    print("="*60)

if __name__ == "__main__":
    export_priority_lists()
