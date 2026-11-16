# mobile-feature-coverage

The Firefox Mobile test coverage dashboard: one row per feature of the
[feature taxonomy](../mobile-feature-taxonomy/FEATURES.md) (L1 areas, L2 features), iOS next to Android, rebuilt from
live data. Published to Quick (staff only) at https://mte-mobile-feature-coverage.quick.mozilla.cloud/.

For now it shows the TestRail columns:

- **UI automation · % of TestRail cases**: share of the feature's Full Functional cases whose *Automation* field is
  *Completed*. It's the TestRail status, not a verified run.
- **Manual · TestRail cases**: number of Full Functional cases attributed to the feature, automated ones included.

Unit-test coverage and escaped bugs per feature will be added as more column groups (`GROUPS` in
`site/index.html`, plus a collector writing to `site/data/`).

## How cases are attributed

Through [`mobile-feature-taxonomy/testrail_map.py`](../mobile-feature-taxonomy/testrail_map.py): each section of
the Full Functional suites (iOS 45443, Android 3192) starts its description with a feature ID, and a case takes the ID
of its section or of the nearest parent that has one. See the taxonomy README ("TestRail cases per feature"). A daily
check posts to Slack when a section has none, so the dashboard doesn't silently drop cases.

Area rows count every case in the area, including cases attributed to the area alone.

## How it runs

[`mobile-feature-coverage.yml`](../.github/workflows/mobile-feature-coverage.yml) runs every Monday, or on demand
from the Actions tab (the site's **Refresh data** link goes there):

1. `collect_testrail.py` fetches both suites and writes `site/data/testrail.json`: counts per feature only.
2. `site/` is deployed to Quick. `index.html` loads the JSON and draws the table.

The data file only exists on the site, behind Mozilla SSO. It isn't committed because this repo is public, and it
holds aggregate counts only: no section names, titles or case IDs reach the output or the Actions log.

## Run locally

Needs `TESTRAIL_HOST`, `TESTRAIL_USERNAME`, `TESTRAIL_PASSWORD`.

```bash
uv run collect_testrail.py                       # writes site/data/testrail.json (git-ignored)
python3 -m http.server -d site 8000              # then open http://localhost:8000
python3 -m unittest discover -s tests -p 'test_*.py'
```

`--cache-dir DIR` keeps the fetched TestRail data for faster reruns; delete it to see TestRail changes.
