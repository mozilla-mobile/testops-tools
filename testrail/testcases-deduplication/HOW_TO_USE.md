# How to Use the Duplicate Detection Results

**Updated:** 2026-04-21

---

## Running the Pipeline

### Full pipeline (recommended)

```bash
cd testrail/testcases-deduplication
pip install -r requirements.txt

python run_all.py /path/to/testrail_export.xlsx
```

This runs all three steps and writes output files to the script directory by default.

### Custom output directory

Use `--output-dir` to control where output CSVs are written — useful for CI or when you want to keep results from different runs separate:

```bash
python run_all.py /path/to/export.xlsx --output-dir /tmp/dedup-2024-01-15
```

### Adjust detection thresholds

```bash
python run_all.py export.xlsx \
  --dup-threshold 0.92 \
  --sim-threshold 0.85 \
  --overlap-threshold 0.80
```

| Flag | Default | Description |
|------|---------|-------------|
| `--dup-threshold` | 0.90 | Minimum similarity to label a pair as `semantic_duplicate` |
| `--sim-threshold` | 0.80 | Minimum similarity to include a pair in the report at all |
| `--overlap-threshold` | 0.80 | Minimum step overlap to set `shares_most_steps = True` |

### Run individual steps

Each step can also be run standalone if you already have intermediate CSVs:

```bash
python generate-work-list.py --output-dir /path/to/results
python export-priority-list.py --output-dir /path/to/results
```

> **Note:** Output CSVs contain TestRail test case data — do not commit them to the repository. They are covered by `.gitignore`.

---

## Automated Monitoring (GitHub Action)

The workflow `testrail-ff-tests-deduplication.yml` runs automatically every **Monday at 9am UTC** and can also be triggered manually from GitHub Actions.

### What it does

1. Fetches test cases from TestRail via API
2. Runs the full deduplication pipeline
3. Uploads result CSVs to GCS (`mobile-reports/public/testrail-ff-test-deduplication/{project}/{date}/`)
4. Stores run stats in BigQuery (`moz-mobile-tools.testops_stats.testrail_deduplication_runs`)
5. Sends Slack notifications to `#mobile-alerts-sandbox`

### Slack notifications

There are three types of notifications:

#### 1. Weekly digest (every Monday, on success)

Sent after every successful run. Shows the current stats with week-over-week deltas so you can track trends at a glance.

```
🔍 TestRail Deduplication — 2026-04-28

Project: firefox-ios (ID: 14)
Total cases: 1,620 (+5 vs last week)
Exact duplicates: 42 (+3 vs last week)
Similar pairs: 310 (no change)
Duplicate rate: 2.6%
Download results from GCS
```

#### 2. Spike alert (only when exact duplicates jump by more than 10)

Sent in addition to the digest when there's a significant increase in exact duplicates — this usually means a bulk import or copy-paste of test cases happened.

```
⚠️ Duplicate spike detected — firefox-ios

Exact duplicates jumped by 23 this week (42 → 65)
Project: firefox-ios (ID: 14) | Date: 2026-04-28
Download results · View run
```

> This alert is skipped on the very first run (no previous data to compare against).

#### 3. Failure notification (any step fails)

```
❌ TestRail Deduplication failed (project 14)
View run
```

### Triggering manually

Go to **Actions → TestRail Test Case Deduplication → Run workflow** and select:
- **Project ID**: 14 (Firefox iOS), 59 (Fenix), 27 (Focus iOS), 48 (Focus Android)
- **Suite ID** (optional): leave empty to fetch all suites

---

## Quick Start Guide (reviewing results)

### Step 1: Open the Data Files

Two CSV files contain the raw data:

#### duplicates_exact.csv
- Each row is a test case that belongs to a duplicate group
- All cases with the same `duplicate_group_id` are exact duplicates
- **Action:** Keep one test per group, archive the rest

#### similar_pairs.csv
- Each row is a pair of similar tests with their similarity scores
- **Action:** Review high-similarity pairs (≥95%) for potential consolidation

### Step 3: Understand the Columns

#### duplicates_exact.csv

| Column | What it means |
|--------|---------------|
| **_case_id** | TestRail case ID (e.g., C2575167) |
| **_title** | Test case title |
| **duplicate_group_id** | Group identifier - same ID = exact duplicates |

**Usage:**
1. Sort by `duplicate_group_id`
2. For each group, choose one test to keep
3. Archive all others in that group

#### similar_pairs.csv

| Column | What it means |
|--------|---------------|
| **case_id_1**, **case_id_2** | The two test case IDs being compared |
| **title_1**, **title_2** | Their titles |
| **similarity** | Semantic similarity score (0.0-1.0) |
| **step_overlap** | Percentage of shared steps (0.0-1.0) |
| **relation** | "semantic_duplicate" (≥90%) or "similar" (80-90%) |
| **shares_most_steps** | True if ≥80% of steps are identical |

**Usage:**
```python
# In Excel/Sheets, filter by:
similarity >= 0.95  # High priority duplicates
relation == "semantic_duplicate"  # Strong duplicate candidates
shares_most_steps == TRUE  # Tests with identical execution
```

---

## Action Plan

### Phase 1: Address Exact Duplicates

**Goal:** Review and archive all exact duplicate groups

**Priority Order** (use `WORK_LIST_EXACT.csv`):

1. Start with the largest groups (4+ duplicates) — biggest savings per group
2. Then medium groups (3 duplicates)
3. Finally the 2-duplicate groups

For each group: keep the case with the **lowest ID** (usually the original), archive the rest.

### Phase 2: Review High Similarity Cases

**Goal:** Identify consolidation opportunities in near-duplicates

**Priority** (use `WORK_LIST_PERFECT_MATCHES.csv` and `WORK_LIST_SIMILAR_HIGH_PRIORITY.csv`):

1. **Perfect semantic matches (100% similarity)** — treat as exact duplicates; likely differ only in formatting
2. **Near-perfect matches (95-99%)** — review manually; small differences may be intentional
3. **High step overlap (≥80%)** — consider parameterization if tests differ only by a variable

### Phase 3: Pattern Analysis

**Goal:** Understand root causes to prevent future duplication

**Tasks:**
1. Identify which sections/suites have the most duplicates
2. Map duplicates to test creation periods (bulk imports, copy-paste)
3. Create process guidelines to prevent recurrence

---

## How to Archive Tests in TestRail

### Option 1: Individual Archive
1. Open the test case in TestRail
2. Click "Edit"
3. Check the "Archived" checkbox
4. Add a comment: "Archived - exact duplicate of [CASE_ID]"
5. Save

### Option 2: Bulk Archive
1. Go to the test suite in TestRail
2. Select multiple test cases (checkbox selection)
3. Click "Bulk Update"
4. Set "Archived" = Yes
5. Add comment: "Archived - duplicate cleanup [DATE]"
6. Apply

### Best Practices
- ✅ Always add a comment explaining why you archived
- ✅ Reference the test you're keeping
- ✅ Archive rather than delete (can be restored)
- ✅ Verify automation coverage before archiving
- ✅ Update any test runs or plans that reference archived cases

---

## Example Walkthrough

### Example 1: Exact Duplicate Group

**From duplicates_exact.csv:**
```
_case_id,  _title,                            duplicate_group_id
C1000001,  "Select and save System auto theme", 5
C1000045,  "Select and save System auto theme", 5
C1000089,  "Select and save System auto theme", 5
```

**Steps:**
1. Open all 3 cases in TestRail
2. Verify they are truly identical (check steps, expected results)
3. Choose to keep: **C1000001** (lowest ID = original)
4. Archive C1000045 with comment: "Archived - exact duplicate of C1000001"
5. Archive C1000089 with comment: "Archived - exact duplicate of C1000001"
6. Result: 2 fewer test cases ✅

### Example 2: High Similarity Pair

**From similar_pairs.csv:**
```
case_id_1, title_1,                          case_id_2, title_2,                        similarity, step_overlap
C1000010,  "Verify CFR displayed - bottom toolbar", C1000011, "Verify CFR displayed - top toolbar", 1.000, 1.000
```

**Steps:**
1. Open both cases
2. Review: They test the same thing with different toolbar positions
3. **Decision:** These are intentional variants - KEEP BOTH
4. No action needed

**Alternative scenario:**
If the toolbar position isn't critical, consider:
- Create one parameterized test: "Verify CFR displayed [toolbar_position]"
- Archive both originals
- Result: 1 test instead of 2 ✅

---

## Using the Data Files

### In Excel/Google Sheets

**duplicates_exact.csv:**
1. Open in Excel
2. Sort by `duplicate_group_id`
3. For each group:
   - Highlight the row you'll KEEP (lowest case_id)
   - Mark others for archive
4. Track progress with a "Status" column

**similar_pairs.csv:**
1. Open in Excel
2. Add filters to all columns
3. Filter: `similarity >= 0.95`
4. Sort by `similarity` descending
5. Review top matches first

### In Python

```python
import pandas as pd

# Load exact duplicates
exact = pd.read_csv('duplicates_exact.csv')

# Find largest groups
group_sizes = exact.groupby('duplicate_group_id').size()
largest_groups = group_sizes[group_sizes >= 3].sort_values(ascending=False)

# Load similar pairs
similar = pd.read_csv('similar_pairs.csv')

# High priority: near-perfect matches
high_priority = similar[similar['similarity'] >= 0.95].sort_values('similarity', ascending=False)

# Cases that share most steps
high_overlap = similar[similar['shares_most_steps'] == True]

# Semantic duplicates only
duplicates = similar[similar['relation'] == 'semantic_duplicate']
```

---

## FAQs

### Q: Which test should I keep if they're all identical?
**A:** Keep the one with the **lowest Case ID** (e.g., C2575167 instead of C3193560). The lowest ID is usually the original test, and higher IDs are copies.

### Q: What if one duplicate has automation coverage and the other doesn't?
**A:** Keep the one with automation coverage, or migrate the automation to the version you want to keep before archiving.

### Q: What if the tests are 100% similar but have different titles?
**A:** Review carefully - they might be testing subtly different scenarios. If truly identical, consolidate to one and update the title to be more descriptive.

### Q: Should I delete or archive?
**A:** **Always archive** (never delete). Archiving allows you to restore if you make a mistake or discover the "duplicate" was actually testing something different.

### Q: What if I disagree with a suggested duplicate?
**A:** Trust your judgment! The script uses semantic analysis, but you have domain knowledge. If two tests seem similar but test different things, keep both and document why.

### Q: How do I prevent future duplicates?
**A:** See "Priority 4" in DEDUPLICATION_REPORT.md for prevention strategies:
- Search before creating new tests
- Use consistent naming conventions
- Run quarterly deduplication audits
- Consider automated duplicate detection in CI/CD

---

## Need Help?

If you encounter issues or have questions:

1. Check the script source: `find-duplicates.py`
2. Re-run the pipeline with updated data: `python run_all.py export.xlsx`
3. Adjust thresholds if results seem off (see the table above)
