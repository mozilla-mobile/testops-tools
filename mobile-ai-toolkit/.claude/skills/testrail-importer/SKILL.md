---
name: testrail-importer
description: Imports a reviewed test-case CSV into TestRail. Creates a root section named after the feature and adds the entire section structure and all test cases inside it. Triggers when the user asks to import, upload, or push manual test cases to TestRail.
argument-hint: [feature_name (e.g., google-lens)]
---

# Import test cases into TestRail

This skill imports the reviewed CSV for a feature into TestRail in a single action. There are **no modes** — running it creates a section named after themfeature and adds the whole structure and every test case inside that section.

The importer never modifies the reviewed CSV, manifest, or review report.

---

## Invocation

```text
/testrail-importer <feature_name>
```

Example:

```text
/testrail-importer google-lens
```

The importer is a thin wrapper over `scripts/testrail_import.py`. Run:

```text
python3 scripts/testrail_import.py <feature_name>
```

---

## Input files

Resolve paths from `<feature_name>`:

* Input directory: `work/outputs/<feature_name>/`
* CSV: `work/outputs/<feature_name>/<feature_name>-testcases.csv`. If that exact
  name is absent, use the single `*.csv` in the directory (ignore files starting
  with `~` or `.`). Stop with an error if zero or more than one CSV exists.

Never modify any input file.

Generated output:

* `work/outputs/<feature_name>/testrail_import_report.md`

---

## Environment variables

Required:

```text
TESTRAIL_URL
TESTRAIL_USER
TESTRAIL_API_KEY
TESTRAIL_PROJECT_ID
TESTRAIL_SUITE_ID            # target suite for Critical / High / Medium priority cases
TESTRAIL_SUITE_ID_LOW       # target suite for Low priority cases (required only when the CSV contains any Low-priority case)
```

**Priority-based suite routing:** cases with `Critical`, `High`, or `Medium` priority are created in `TESTRAIL_SUITE_ID`; cases with `Low` priority are created in `TESTRAIL_SUITE_ID_LOW`. Each suite gets its own root section + section structure. If the CSV has Low-priority cases and `TESTRAIL_SUITE_ID_LOW` is not set, the import fails before creating anything.

Optional (with defaults):

```text
TESTRAIL_TEMPLATE_ID
TESTRAIL_USE_SEPARATED_STEPS   = false
TESTRAIL_EXTERNAL_ID_FIELD     = custom_external_id
TESTRAIL_PRECONDITIONS_FIELD   = custom_preconds
TESTRAIL_STEPS_FIELD           = custom_steps
TESTRAIL_EXPECTED_FIELD        = custom_expected
TESTRAIL_SEPARATED_STEPS_FIELD = custom_steps_separated
TESTRAIL_SUB_TEST_SUITE_FIELD  = custom_sub_test_suites
TESTRAIL_REFERENCES_FIELD      = refs
TESTRAIL_REQUEST_TIMEOUT       = 30
TESTRAIL_MAX_RETRIES           = 3
```

**Sub Test Suite(s):** the CSV `Sub Test Suite(s)` labels (e.g. `Special Case, Regression, Telemetry`) are mapped to the option ids of the `TESTRAIL_SUB_TEST_SUITE_FIELD` multi-select case field and imported. If that field does not exist in the project it is skipped; any label that isn't a valid option is skipped with a warning (the case is still created).

A local `.env` is loaded automatically when `python-dotenv` is installed.
Never print the API key or write it to any file.

**Steps rendering:** set `TESTRAIL_USE_SEPARATED_STEPS=true` together with a
separated-steps `TESTRAIL_TEMPLATE_ID` (e.g. "Test Case (Steps)") to store each
step paired with its expected result. Otherwise Steps and Expected Results are
written to the plain-text fields (`custom_steps` / `custom_expected`), which
requires a text template.

---

## CSV format

Eight columns (order may vary; headers matched by alias):

```text
Section (Folder), Title, Preconditions, Steps, Expected Results, Priority, Type, Sub Test Suite(s)
```

* `Section (Folder)` may use `/`, `>`, or `::` to express nested sub-sections.
* `Steps` and `Expected Results` use matching line indices (`1.`, `2.`, …).
* `Priority` is one of `Critical`, `High`, `Medium`, `Low` (P0–P3 aliases accepted); it drives suite routing (see Environment variables).
* `Sub Test Suite(s)` is a comma-separated list of tags (e.g. `Special Case, Regression, Telemetry`).

---

## What the importer does

1. Parse and validate the CSV (required columns present; every row has a
   section, title, steps, expected results, priority, and type; steps pair with
   expected results).
2. Connect to TestRail and read priorities, case types, case fields, templates,
   and existing sections.
3. Verify the configured content custom fields exist. The External ID and
   Sub Test Suite fields are optional — if they do not exist, they are skipped.
4. Split cases by priority: `Critical`/`High`/`Medium` → `TESTRAIL_SUITE_ID`;
   `Low` → `TESTRAIL_SUITE_ID_LOW`.
5. In **each** target suite that has cases, **create a root section named after
   the feature** (e.g. `Google Lens`).
6. Recreate the CSV's section structure **inside** that root section (per suite),
   reusing any sections that already exist and creating parents before children.
7. Create every test case inside its section in its routed suite, mapping
   Priority and Type to TestRail ids (with `P0..P3` aliases and optional
   defaults).
8. Write `testrail_import_report.md` summarizing, per suite, sections created,
   cases created, and any failures.

The feature name is turned into the root section's display name by splitting on
`-`/`_`/space and capitalizing each word (`google-lens` → `Google Lens`).

---

## Report

`work/outputs/<feature_name>/testrail_import_report.md` records the target
project/suite, the root section, counts (sections created, cases created, cases
failed), the created case ids, and any failures. Status is `COMPLETED` or
`COMPLETED_WITH_ERRORS`.

---

## Notes

* Re-running imports again; it does not deduplicate. To reimport cleanly, remove
  the previously created feature section in TestRail first.
* Deletions and updates are out of scope — the importer only creates.
