# mobile-feature-health

The Firefox Mobile feature health dashboard: one row per feature of the
[feature taxonomy](../mobile-feature-taxonomy/FEATURES.md) (L1 areas, L2 features), iOS next to Android, rebuilt
from live data every week. Published to Quick (staff only) at https://mte-mobile-feature-health.quick.mozilla.cloud/.

Columns:

- **UI automation · % of TestRail cases**: share of the feature's Full Functional cases whose *Automation* field is
  *Completed*. It's the TestRail status, not a verified run.
- **Manual · TestRail cases**: number of Full Functional cases attributed to the feature, automated ones included.
- **Escaped bugs · this year**: bugs reported by people outside the team, created from January 1 to the day of the
  run, shown as "N open · total". The header links to each tracker's search for the year.

The **Escaped bugs** tab lists every bug: platform, number, title, feature, how it got its feature (*tag* on the bug, *component* or
*title rule* on Android, *decision* or *waiting for a decision* on iOS), component, created date and state. It filters
by platform, open/closed, area or feature, assignment, date range and text, sorts by any column, opens the Android
bugs in Bugzilla in one click and downloads the list as CSV. Clicking a count in the overview opens the tab filtered
to those bugs. Filters are kept in the URL, so a view can be shared, e.g. `…/#bugs?p=android&h=title+rule&s=all`
lists the Android bugs whose feature came from a title rule, to review the rules.

Extra rows hold the escaped bugs that don't belong to one feature: cross-cutting axes (`X.PERF`, `X.L10N`…) and bugs
without a feature yet (Android's General component, iOS issues waiting for a decision). Unit-test coverage per
feature will be another column group.

## Where the numbers come from

Both use the taxonomy's attribution tools, so the dashboard, the checks and the local CLIs always agree:

- **TestRail** — [`testrail_map.py`](../mobile-feature-taxonomy/testrail_map.py): each Full Functional section
  (iOS 45443, Android 3192) starts its description with a feature ID; a case takes the ID of its section or nearest
  parent. A daily check alerts on Slack when a section has none.
- **Escaped bugs** — [`bugs_map.py`](../mobile-feature-taxonomy/bugs_map.py): on Android, Bugzilla *Firefox for
  Android* defects (reporter not @mozilla.com, no bots, no duplicates / invalid) by component and title rules; on
  iOS, firefox-ios issues with a bug label from authors outside the org, with a feature decided per issue in
  `ios/bugs-map.yml`. See the taxonomy README, "Escaped bugs per feature".

Area rows count every case or bug in the area, including the ones attributed to the area alone.

## How it runs

[`mobile-feature-health.yml`](../.github/workflows/mobile-feature-health.yml) runs every Monday, or on demand from
the Actions tab (the site's **Refresh data** link goes there):

1. `collect.py` builds every data file in `site/data/`: `features.json` (taxonomy rows), `testrail.json`,
   `bugs.json` and `status.json`. If one source fails, the others are still written.
2. `site/` is deployed to Quick. `index.html` loads the JSON files and draws the table; columns of a source that
   failed show "no data" with a notice at the top.
3. The run fails if a source couldn't be refreshed, after deploying the rest.

The data files only exist on the site, behind Mozilla SSO, and aren't committed because this repo is public.
TestRail data is aggregate counts only (no section names, titles or case IDs). Bugs are public on Bugzilla and
GitHub, so `bugs.json` lists their IDs, titles and links.

| File | Built by | Needs |
|---|---|---|
| `features.json` | `collect.py` | nothing (reads `features.yml`) |
| `testrail.json` | `collect_testrail.py` | `TESTRAIL_HOST`, `TESTRAIL_USERNAME`, `TESTRAIL_PASSWORD` |
| `bugs.json` | `collect_bugs.py` | a GitHub token for iOS (`GITHUB_TOKEN`, `GH_TOKEN` or the `gh` CLI's) and who is in the iOS teams: the `IOS_TEAM_LOGINS` secret in CI, locally read with the `gh` CLI; Bugzilla is public |

## Run locally

```bash
uv run collect.py --cache-dir /tmp/fh            # writes site/data/ (git-ignored); --only bugs for one source
python3 -m http.server -d site 8000              # then open http://localhost:8000
python3 -m unittest discover -s tests -p 'test_*.py'
```

`--cache-dir` keeps fetched data between runs: bugs are refetched when the day changes; delete the TestRail cache
to see TestRail edits.

**Refreshing the team** (who doesn't count as escaped on iOS): the workflow's token can't read GitHub org teams, so a
repo admin stores the members of the teams listed in `ios/bugs-map.yml` as the `IOS_TEAM_LOGINS` secret:

```bash
uv run mobile-feature-taxonomy/bugs_map.py ios team --update-secret    # from the repo root, with `gh` logged in
```

Run it again when people join or leave the iOS / QA teams (monthly is enough). If a team in the list is deleted or
renamed, the command says which one.

## Adding a column

Add a collector with `build(cache_dir)` and `summary(out)` to `SOURCES` in `collect.py`, and a group to `GROUPS`
in `site/index.html` (each group has an iOS and an Android column).
