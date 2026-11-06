# Mobile feature taxonomy

The Firefox Mobile feature taxonomy (iOS and Android), plus maps that attribute every
Firefox iOS and Firefox for Android source file to one feature. Coverage, test counts and bug numbers can then be
reported per feature, the same way on both platforms.

## What this is for

The Mobile Testing Assessment compares how well each product feature is tested on iOS and Android: unit coverage,
UI tests, TestRail manual and automated cases, and escaped bugs. That only works if every source of data uses the
same list of features and the same rule for "which feature does this code belong to". This folder holds that:

- **`features.yml`**: the list of features, with stable IDs grouped into areas (e.g. `TABS.TRAY` in "Tabs",
  `CRED.ADDR` in "Passwords & autofill"), shared by both platforms. **[FEATURES.md](FEATURES.md)** shows the same
  list as readable L1/L2 tables.
- **`ios/feature-map.yml`, `android/feature-map.yml`**: path rules that assign every source file in firefox-ios and
  in Fenix + android-components to exactly one of those features.
- **Tooling** to check the maps, list each file's feature and lines of code per feature, and detect when the code
  has moved on so the maps can be updated. Per-feature test coverage, which needs a unit-test run, will come in a
  separate PR.

It lives here, not in the product repos, so it's one copy, maintained by Mobile Test Engineering, and kept current
by a weekly CI job instead of scripts on someone's machine. Consumers: the
Testing Assessment charts (`mobile-testing-assessment-charts/`, feature grouping), the coverage scorecards, and
later the TestRail section → feature mapping.

## Layout

```
mobile-feature-taxonomy/
├── features.yml            # the taxonomy: feature IDs (BRW.NAV, TABS.TRAY…), SHARED.* buckets, EXCLUDED
├── FEATURES.md             # generated from features.yml: readable L1/L2 list
├── taxonomy.py             # generates FEATURES.md, checks it's in sync, exports CSV
├── ios/
│   ├── feature-map.yml     # rules: firefox-ios source path → feature ID
│   └── snapshot.csv        # every file and its feature at the last accepted update
├── android/
│   ├── feature-map.yml     # rules: mozilla-firefox/firefox mobile/android path → feature ID
│   └── snapshot.csv
├── feature_map.py          # CLI: check / files / lines / drift
├── drift.py                # map-vs-code comparison and suggested fixes
└── tests/
```

Origins: `features.yml` and the iOS map come from firefox-ios branch `feature-coverage-map` (commit
`a0be3389bf`). The Android map is the port made for the Testing Assessment (2026-10-27). All rules are still
`by: ai` (a generated first pass) or `by: drift` (added from the first drift report), not yet reviewed.

## Commands

Point `--repo` at a checkout of the platform's repository. A shallow, sparse clone is enough (see the workflow).
[`uv`](https://docs.astral.sh/uv/) installs PyYAML automatically, or `pip install -r requirements.txt`.

```bash
uv run feature_map.py ios     --repo ~/git/firefox-ios               check   # every file maps to exactly one feature
uv run feature_map.py android --repo ~/git/mozilla-firefox/firefox   check

uv run feature_map.py ios --repo ~/git/firefox-ios files    # CSV: feature, area and matching rule per file
uv run feature_map.py ios --repo ~/git/firefox-ios lines    # CSV: files and source lines per feature (and layer)
uv run feature_map.py ios --repo ~/git/firefox-ios drift    # Markdown report: where the map and the code disagree
```

`--map PATH` uses another feature-map.yml, for trying rule changes.

## Keeping the maps in sync with the code

The code changes every day; the maps only stay useful if drift is caught and fixed. The
[workflow](../.github/workflows/mobile-feature-taxonomy.yml) runs `drift` for both platforms against today's `main`
every Monday (and on demand) and puts the report in the job summary. It only fails when something needs a decision;
changes that existing rules already cover are listed for review.
PRs in this repo only run the unit tests. Drift only reads file paths, so it needs no build and no test run.

`drift` reports two kinds of difference:

1. **Needs a decision** (`check` fails until it's fixed):
   - *Unmapped code*, grouped: a new directory gets one `dir/**` rule, a new file in an existing directory gets an
     exact-path rule. Each comes with a suggested feature and a confidence:
     - **high**: at least 80% of the neighbouring mapped code is one feature
     - **medium**: a majority of neighbours, and the names point to the same feature
     - **low**: anything else. The best guess comes from matching the new directory and file names against each
       feature's name and the paths already mapped to it.
   - *Rules that match nothing*: the code moved or was deleted. For exact paths it looks for the same file name
     elsewhere ("probably moved to…").
   - *Ambiguous files*, and *unknown feature IDs*.
2. **Review** (`check` passes, but compared to `snapshot.csv`):
   - new files that an existing glob picked up silently (is that glob still right for them?)
   - moved files, and especially moved files whose feature changed
   - files whose feature changed, and removed files

To update a map:

```bash
uv run feature_map.py android --repo ~/git/mozilla-firefox/firefox drift --apply
```

`--apply` writes the **high** and **medium** suggestions into `feature-map.yml` with `by: drift`, updates paths of
moved files, and refreshes `snapshot.csv`. Low-confidence groups are never written: they stay in the report, and
`check` keeps failing until someone decides. Review the result as a normal PR: the map diff shows new and changed
rules, and the snapshot diff shows exactly which files moved between features. Running the workflow manually with
`open_pr` does the same in CI and opens the PR.

Same idea as the test recommender's `align.py` (detect drift → propose → a person accepts), but non-interactive and
reviewed in a PR, so it can run in CI and nothing depends on one person's machine.

## How rules resolve

- **The most specific rule wins, and rule order doesn't matter.** An exact file path beats a glob. Among globs, the
  one with more literal path segments wins, then the longer pattern. Two equally specific rules matching one file is
  an error.
- **Folder rules don't need to cover every file.** If a new file matches no rule, `check` fails, so someone has to
  decide where it belongs.
- **`optional: true`** lets a rule match nothing, for directories created by the build (iOS `Generated/`).
- **`symbols` split one file across features** (iOS only). Each entry is a regex matched against function names.
  They're checked for valid feature IDs here, but only take effect in per-feature coverage, which comes in a
  separate PR. No rule uses them yet.

```yaml
- path: "firefox-ios/Client/Frontend/Browser/BrowserViewController/Views/BrowserViewController.swift"
  feature: SHARED.SHELL
  symbols:
    - {match: "(?i)readerMode", feature: BRW.READ}
```

Each map's header sets the platform details: `repo`, `base` (the directory rule paths are relative to), `roots`,
`extensions`, and for Android `require_path_segment: src/main` (production code only), `skip_dirs` and `layers`.

## Choosing a feature

- **Ask which feature breaks if this code breaks.** A settings row belongs to the feature it configures:
  `AddressAutofillSetting.swift` is `CRED.ADDR`, not `SET.FRAME`.
- **Telemetry for one feature goes with that feature.** `SHARED.TELEMETRY` is only for telemetry infrastructure.
- **Use a `SHARED.*` bucket only when the code genuinely serves many features.** They are reported separately, so
  the amount of shared code stays visible.
- An L1 area alone (e.g. `CRED`) is allowed for code that serves the whole area.

## Changing the taxonomy

`features.yml` is shared by both platforms and by everything that reports per feature. IDs must stay stable: rename
`name`, never `id`. Adding a feature is safe. Removing or splitting one means updating both maps in the same PR; the
unit tests fail if a map uses an ID that no longer exists.

Whether a feature exists on iOS or Android isn't set by hand: `FEATURES.md` shows a check mark when that platform's map
assigns code to the feature. After changing `features.yml` or a map by hand, regenerate the list in the same PR
(`drift --apply` does it for you). CI fails if `FEATURES.md` doesn't match:

```bash
uv run taxonomy.py           # rewrites FEATURES.md
uv run taxonomy.py --csv     # the L1/L2 list as CSV, e.g. to import into a spreadsheet
```

## Review status

Rules marked `by: ai` (generated) or `by: drift` (suggested by `drift --apply`) haven't been checked by a person.
Delete the marker once you've reviewed a rule. `check` and `drift` report how many are left, per area.
